"""The downloader, the question of the first start and the links: nothing touches the net, ffmpeg or the live hub."""
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HUB_WEB_PORT", "18787")
os.environ["HUB_STATE_DIR"] = tempfile.mkdtemp(prefix="mg-state-")   # never the live hub
os.environ["HUB_CONFIG"] = os.path.join(os.environ["HUB_STATE_DIR"], "no-hub.json")   # nor its settings (a gallery folder, a storage link)
for _k in ("MOTION_GALLERY_DIR", "MOTION_GALLERY_BASE"):
    os.environ.pop(_k, None)
import fetcher  # noqa: E402
import firstrun  # noqa: E402
import linkctl  # noqa: E402
import links as linkmem  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
import sources  # noqa: E402
import tgpost  # noqa: E402

LIST = "https://skillry.dev/ai-videos/opus"


def ld(video, poster, name="A video", seconds="PT6S", author="Anna"):
    data = {"@type": "VideoObject", "name": name, "contentUrl": video, "thumbnailUrl": [poster], "duration": seconds, "author": {"name": author}}
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def item_page(n):
    return f"<html>{ld(f'https://cdn.test/v{n}.mp4', f'https://cdn.test/p{n}.jpg')}<pre>Prompt number {n} &amp; more</pre></html>"


def pages(count):
    """A list page of skillry.dev with `count` items and the item pages."""
    web = {LIST: "".join(f'<a href="/ai-videos/opus/i{n}">x</a>' for n in range(count))}
    for n in range(count):
        web[f"https://skillry.dev/ai-videos/opus/i{n}"] = item_page(n)
    return web


class Fakes:
    """get / head / save / which / run over a dict of pages; every call is written down."""

    def __init__(self, web, size=1000, ffmpeg=None):
        self.web, self.size, self.exe = web, size, ffmpeg
        self.gets, self.saved, self.ran = [], [], []

    def get(self, url):
        self.gets.append(url)
        if url not in self.web:
            raise net.NetError("http_404", "no such page")
        return self.web[url]

    def head(self, url):
        return self.size

    def save(self, url, path, limit):
        self.saved.append(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * self.size)
        return self.size

    def which(self, name):
        return self.exe if name == "ffmpeg" else None

    def run(self, cmd, **kw):   # a fake ffmpeg: the output is a third of the input
        self.ran.append(cmd)
        src, out = cmd[cmd.index("-i") + 1], cmd[-1]
        with open(out, "wb") as f:
            f.write(b"y" * (os.path.getsize(src) // 3))
        return subprocess.CompletedProcess(cmd, 0)

    def fetcher(self, root):
        return fetcher.Fetcher(root, get=self.get, head=self.head, save=self.save, which=self.which, run=self.run, sleep=lambda s: None)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()


class Readers(unittest.TestCase):
    def test_every_source_is_found_by_its_address(self):
        self.assertEqual(sources.for_url("https://skillry.dev/ai-videos").name, "skillry.dev")
        self.assertEqual(sources.for_url("https://www.prompt-motion.com").name, "prompt-motion.com")
        self.assertEqual(sources.for_url("https://claude-motion.com/gallery").name, "claude-motion.com")

    def test_sites_without_a_reader_are_named_as_such(self):
        for url in ("https://www.remotion.dev/prompts", "https://github.com/heygen-com/hyperframes"):
            self.assertIsNone(sources.for_url(url))

    def test_the_plugin_brings_no_links_of_its_own(self):
        self.assertFalse(hasattr(linkctl, "DEFAULTS"))

    def test_skillry_item_page_to_an_entry(self):
        site = sources.for_url(LIST)
        entry = site.read(LIST + "/i1", item_page(1))
        self.assertEqual(entry["video_url"], "https://cdn.test/v1.mp4")
        self.assertEqual(entry["poster_url"], "https://cdn.test/p1.jpg")
        self.assertEqual((entry["prompt"], entry["seconds"], entry["author"]), ("Prompt number 1 & more", 6, "Anna"))
        self.assertEqual(entry["slug"], "skillry-i1")

    def test_a_page_without_a_video_is_none(self):
        self.assertIsNone(sources.for_url(LIST).read(LIST + "/i1", "<html>nothing</html>"))

    def test_a_list_opens_the_item_pages_and_an_item_is_itself(self):
        site = sources.for_url(LIST)
        web = pages(3)
        self.assertEqual(site.list(LIST, web.__getitem__), [f"https://skillry.dev/ai-videos/opus/i{n}" for n in range(3)])
        self.assertEqual(site.list(LIST + "/i2", web.__getitem__), [LIST + "/i2"])

    def test_prompt_motion_takes_the_prompt_from_the_page_data_and_the_tags(self):
        inner = '0:{"prompt":"Spin the logo \\"slowly\\"","x":1}'
        page = f'<html>{ld("https://cdn.test/v.mp4", "https://cdn.test/p.jpg")}<script>self.__next_f.push([1,{json.dumps(inner)}])</script><a href="/tags/logo">logo</a></html>'
        entry = sources.for_url("https://prompt-motion.com").read("https://prompt-motion.com/anna-0a1b2c", page)
        self.assertEqual(entry["prompt"], 'Spin the logo "slowly"')
        self.assertEqual(entry["tags"], ["logo"])


class Plan(TmpCase):
    def test_the_estimate_counts_examples_and_uses_the_real_size(self):
        fk = Fakes(pages(5), size=2 * 1024 * 1024)
        plan = fk.fetcher(self.root).plan([LIST])
        self.assertEqual(plan["n"], 5)
        self.assertEqual(plan["bytes"], (2 * 1024 * 1024 + 60 * 1024) * 5)   # Content-Length of the sampled videos plus a poster
        self.assertFalse(plan["exact"])
        self.assertEqual(plan["links"][0]["n"], 5)
        self.assertEqual(fk.saved, [])   # an estimate saves nothing

    def test_a_short_list_is_exact(self):
        plan = Fakes(pages(2), size=1000).fetcher(self.root).plan([LIST])
        self.assertTrue(plan["exact"])

    def test_without_a_size_the_average_stands_in(self):
        plan = Fakes(pages(4), size=0).fetcher(self.root).plan([LIST])
        self.assertEqual(plan["bytes"], fetcher.AVG_BYTES * 4)

    def test_a_link_without_a_reader_is_skipped_and_a_dead_one_is_an_error(self):
        plan = Fakes(pages(1)).fetcher(self.root).plan(["https://github.com/a/b", "https://skillry.dev/ai-videos/none"])
        self.assertEqual(plan["skipped"], ["https://github.com/a/b"])
        self.assertEqual(plan["links"][0]["error"], "no such page")
        self.assertEqual(plan["n"], 0)

    def test_a_link_brings_at_most_per_link(self):
        plan = Fakes(pages(fetcher.PER_LINK + 9)).fetcher(self.root).plan([LIST])
        self.assertEqual(plan["n"], fetcher.PER_LINK)

    def test_ffmpeg_and_the_squeezed_size_are_in_the_plan(self):
        plan = Fakes(pages(3), ffmpeg="/bin/ffmpeg").fetcher(self.root).plan([LIST])
        self.assertTrue(plan["ffmpeg"])
        self.assertEqual(plan["small"], int(plan["bytes"] * fetcher.SMALL))
        self.assertFalse(Fakes(pages(3)).fetcher(self.root).plan([LIST])["ffmpeg"])


class Download(TmpCase):
    def run_fetch(self, count=3, compress=False, ffmpeg=None):
        fk = Fakes(pages(count), size=3000, ffmpeg=ffmpeg)
        f = fk.fetcher(self.root)
        self.assertTrue(f.start([LIST], compress=compress))
        f.join(10)
        return fk, f

    def gallery(self):
        with open(os.path.join(fetcher.library(self.root), "gallery.json"), encoding="utf-8") as fh:
            return json.load(fh)["items"]

    def test_as_is_saves_the_video_the_poster_and_the_prompt(self):
        fk, f = self.run_fetch(3)
        st = f.status()
        self.assertEqual((st["state"], st["done"], st["total"], st["added"]), ("done", 3, 3, 3))
        items = self.gallery()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["prompt"], "Prompt number 0 & more")
        lib = fetcher.library(self.root)
        self.assertTrue(os.path.isfile(os.path.join(lib, *items[0]["video"].split("/"))))
        self.assertTrue(os.path.isfile(os.path.join(lib, *items[0]["poster"].split("/"))))
        self.assertEqual(fk.ran, [])   # "as is": ffmpeg is not touched even when it is there
        self.assertEqual(st["bytes"], 3 * 6000)

    def test_as_is_with_ffmpeg_present_does_not_compress(self):
        fk, f = self.run_fetch(2, compress=False, ffmpeg="/bin/ffmpeg")
        self.assertEqual(fk.ran, [])
        self.assertFalse(f.status()["compress"])

    def test_squeeze_runs_ffmpeg_and_keeps_the_smaller_file(self):
        fk, f = self.run_fetch(2, compress=True, ffmpeg="/bin/ffmpeg")
        self.assertEqual(len(fk.ran), 2)
        self.assertTrue(f.status()["compress"])
        self.assertEqual(f.status()["bytes"], 2 * (1000 + 3000))   # the video became a third, the poster stayed
        items = self.gallery()
        self.assertTrue(all(i["video"].endswith(".mp4") for i in items))
        self.assertEqual(len(os.listdir(os.path.join(fetcher.library(self.root), "videos"))), 2)   # no .small leftovers

    def test_squeeze_without_ffmpeg_downloads_as_is(self):
        fk, f = self.run_fetch(2, compress=True, ffmpeg=None)
        self.assertEqual(fk.ran, [])
        self.assertFalse(f.status()["compress"])
        self.assertEqual(f.status()["added"], 2)

    def test_a_squeeze_that_does_not_help_leaves_the_original(self):
        fk = Fakes(pages(1), size=3000, ffmpeg="/bin/ffmpeg")
        fk.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1)   # ffmpeg fails
        f = fk.fetcher(self.root)
        f.start([LIST], compress=True)
        f.join(10)
        self.assertEqual(f.status()["added"], 1)
        self.assertEqual(f.status()["bytes"], 6000)

    def test_what_is_in_the_library_is_not_downloaded_again(self):
        fk, f = self.run_fetch(2)
        self.assertEqual(f.plan([LIST])["n"], 0)
        f.start([LIST])
        f.join(10)
        self.assertEqual(len(self.gallery()), 2)

    def test_a_run_goes_one_at_a_time_and_stops(self):
        fk = Fakes(pages(3), size=10)
        f = fk.fetcher(self.root)
        gate = threading.Event()
        inner = fk.save

        def slow(url, path, limit):
            gate.wait(5)
            return inner(url, path, limit)
        f.save = slow
        self.assertTrue(f.start([LIST]))
        self.assertFalse(f.start([LIST]))   # busy
        f.stop()
        self.assertEqual(f.status()["state"], "stopping")
        gate.set()
        f.join(10)
        self.assertEqual(f.status()["state"], "stopped")


class Memory(TmpCase):
    def links(self):
        return linkmem.Links(os.path.join(self.root, "links.json"))

    def test_links_are_remembered_and_a_removed_default_does_not_come_back(self):
        m = self.links()
        m.seed(["https://a.test", "https://b.test"])
        m.remove("https://a.test")
        again = self.links()
        self.assertEqual(again.urls(), ["https://b.test"])
        self.assertEqual(again.seed(["https://a.test"]), [])

    def test_the_answer_is_remembered_and_an_old_file_counts_as_answered(self):
        m = self.links()
        m.seed(["https://a.test"])
        m.set_first("yes")
        self.assertEqual(self.links().first, "yes")
        with open(os.path.join(self.root, "links.json"), "w", encoding="utf-8") as f:
            json.dump({"links": [{"url": "https://a.test"}], "seeded": True}, f)
        self.assertEqual(self.links().first, "legacy")


class Question(TmpCase):
    def ctl(self, web=None, configured=False, ffmpeg=None):
        self.fk = Fakes(web or pages(2), size=500, ffmpeg=ffmpeg)
        self.sent = []
        c = linkctl.Ctl(linkmem.Links(os.path.join(self.root, "links.json")), self.fk.fetcher(self.root),
                        notify=lambda kind, data: self.sent.append((kind, data)), defaults=[LIST, "https://github.com/a/b"], agents=["writer", "designer"], configured=lambda: configured)
        c.watch = False
        return c

    def test_the_first_start_asks_and_downloads_nothing(self):
        c = self.ctl()
        self.assertEqual(c.startup(), "seeded")
        self.assertEqual(c.links.first, "pending")
        self.assertEqual(c.question()["items"], 23)   # one source of two is read: about 23 examples
        self.assertEqual(self.fk.gets, [])   # not a single page was read
        self.assertEqual(self.fk.saved, [])
        self.assertFalse(c.fetch.running())
        self.assertEqual(c.status()["firstrun"]["sources"], 2)
        self.assertEqual(c.status()["firstrun"]["ready"], 1)
        self.assertEqual(c.status()["firstrun"]["agents"], ["writer", "designer"])

    def test_the_question_is_not_asked_twice_nor_after_a_restart(self):
        c = self.ctl()
        c.startup()
        self.assertEqual(c.answer("no"), "no")
        again = self.ctl()
        self.assertEqual(again.startup(), "")
        self.assertIsNone(again.question())
        self.assertEqual(again.answer("yes"), "no")   # the second answer changes nothing
        self.assertEqual(self.fk.saved, [])

    def test_a_hub_with_a_gallery_already_is_not_asked(self):
        c = self.ctl(configured=True)
        c.startup()
        self.assertEqual(c.links.first, "config")
        self.assertIsNone(c.question())

    def test_no_and_settings_download_nothing(self):
        for choice in ("no", "settings"):
            with self.subTest(choice):
                c = self.ctl()
                c.links.set_first("pending")
                c.answer(choice)
                self.assertEqual(self.fk.saved, [])
                self.assertIsNone(c.question())

    def test_yes_downloads_the_default_links_as_they_are(self):
        c = self.ctl(ffmpeg="/bin/ffmpeg")
        c.startup()
        self.assertEqual(c.answer("yes"), "yes")
        c.fetch.join(10)
        self.assertEqual(c.fetch.status()["added"], 2)
        self.assertEqual(self.fk.ran, [])
        self.assertEqual(c.status()["fetch"]["state"], "done")

    def test_the_question_can_be_asked_again_from_the_settings(self):
        c = self.ctl()
        c.startup()
        c.answer("no")
        self.assertEqual(c.act({"action": "firstrun", "choice": "again"})[0], 200)
        self.assertEqual(c.links.first, "pending")
        self.assertFalse(c.links.ask_posted)
        self.assertEqual(c.act({"action": "firstrun", "choice": "nonsense"})[0], 400)

    def test_an_answer_on_the_page_erases_the_telegram_post_but_a_press_does_not(self):
        c = self.ctl()
        c.startup()
        c.mark_posted()
        c.answer("no", via="tg")
        self.assertEqual(self.sent, [])
        c.again()
        c.mark_posted()
        c.answer("yes", via="page")
        c.fetch.join(10)
        self.assertEqual(self.sent, [("telegram.unpost", {"ref": firstrun.REF})])

    def test_a_download_started_by_hand_settles_the_question(self):
        c = self.ctl()
        c.startup()
        code, out = c.act({"action": "start", "urls": [LIST], "compress": False})
        self.assertEqual((code, out["started"]), (200, True))
        c.fetch.join(10)
        self.assertEqual(c.links.first, "settings")

    def test_act_plan_start_and_bad_input(self):
        c = self.ctl(ffmpeg="/bin/ffmpeg")
        c.startup()
        c.links.set_first("no")
        code, plan = c.act({"action": "plan", "urls": [LIST]})
        self.assertEqual((code, plan["n"], plan["ffmpeg"]), (200, 2, True))
        self.assertEqual(self.fk.saved, [])
        self.assertEqual(c.act({"action": "plan", "urls": []})[0], 400)
        self.assertEqual(c.act({"action": "add", "url": "not a link"})[1]["error"], "bad_link")
        self.assertEqual(c.act({"action": "add", "url": "https://skillry.dev/ai-videos/"})[1]["site"], "skillry.dev")
        self.assertIn("https://skillry.dev/ai-videos", c.links.urls())
        self.assertEqual(c.act({"action": "dance"})[0], 400)
        code, out = c.act({"action": "start", "urls": [LIST], "compress": True})
        self.assertEqual((code, out["compress"]), (200, True))
        c.fetch.join(10)
        self.assertEqual(len(self.fk.ran), 2)

    def test_a_finished_download_tells_the_owner_once_in_the_hub_language(self):
        c = self.ctl()
        c.startup()
        c.answer("yes")
        c.fetch.join(10)
        c.finished()
        kind, data = self.sent[-1]
        self.assertEqual((kind, data["id"], data["asked"]), ("owner.notify", linkctl.NOTE_ID, True))
        self.assertIn("2", data["title"])


class Telegram(TmpCase):
    """A press of a button comes back as telegram.pressed; the question goes once, and only where the bot has the post rules."""

    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.root, "state")
        os.makedirs(self.state)
        open(os.path.join(self.state, "journal.jsonl"), "w").close()
        self.fk = Fakes(pages(1), size=100)
        self.ctl = linkctl.Ctl(linkmem.Links(os.path.join(self.root, "links.json")), self.fk.fetcher(self.root), defaults=[LIST], agents=["writer", "designer"])
        self.ctl.watch = False
        self.ctl.startup()
        self.facts = []
        self.poster = tgpost.Poster(self.state, lambda: self.ctl, state=lambda: {"sessions": {"hub": {"kind": "hub"}, "designer": {}}},
                                    emit=lambda kind, data: self.facts.append((kind, data)))

    def press(self, seq, button, src="telegram", ext="motion-gallery", ref=firstrun.REF):
        return {"seq": seq, "type": "telegram.pressed", "src": src, "data": {"ext": ext, "ref": ref, "button": button}}

    def test_a_press_answers_in_any_language(self):
        self.poster.handle([self.press(1, firstrun.tr("ru", "no"))])
        self.assertEqual(self.ctl.links.first, "no")

    def test_a_foreign_press_does_nothing(self):
        self.poster.handle([self.press(1, "Download", ext="other"), self.press(2, "Download", ref="x"), self.press(3, "Download", src="ext:x"), self.press(4, "Sure")])
        self.assertEqual(self.ctl.links.first, "pending")

    def test_the_post_goes_once_with_the_buttons_and_a_bump(self):
        original = tgpost.rules
        tgpost.rules = lambda: object()   # a bot that knows the post
        try:
            self.poster.first_question()
            self.poster.first_question()
        finally:
            tgpost.rules = original
        self.assertEqual(len(self.facts), 1)
        kind, data = self.facts[0]
        self.assertEqual((kind, data["ref"], data["bump"]), ("telegram.post", firstrun.REF, True))
        self.assertEqual(len(data["buttons"]), 3)
        self.assertIn("writer", data["text"])   # the agents the hub lacks are named

    def test_no_post_where_the_bot_has_no_rules(self):
        original = tgpost.rules
        tgpost.rules = lambda: None
        try:
            self.poster.first_question()
        finally:
            tgpost.rules = original
        self.assertEqual(self.facts, [])
        self.assertFalse(self.ctl.links.ask_posted)

    def test_the_agents_the_hub_lacks(self):
        self.assertEqual(firstrun.missing({"hub": {"kind": "hub"}, "designer": {}, "writer": {"kind": "hub"}}, ["writer", "designer"]), ["writer"])
        self.assertEqual(firstrun.missing(None, ["writer", "designer"]), ["writer", "designer"])


class Http(TmpCase):
    def setUp(self):
        super().setUp()
        self.old = (server.CTL, os.environ.get("HUB_STATE_DIR"))
        os.environ["HUB_STATE_DIR"] = self.root
        self.fk = Fakes(pages(2), size=500)
        self.ctl = linkctl.Ctl(linkmem.Links(os.path.join(server.plugin_dir(), "links.json")), self.fk.fetcher(server.plugin_dir()), defaults=[LIST])
        self.ctl.watch = False
        server.CTL = self.ctl
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        server.PORT = self.port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        server.CTL = self.old[0]
        os.environ["HUB_STATE_DIR"] = self.old[1]
        super().tearDown()

    def call(self, method, path, body=None, origin=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"localhost:{self.port}", **({"Origin": sorted(server.page_origins())[0]} if origin else {})}
        data = json.dumps(body) if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, r.read())
        c.close()
        return out

    def test_status_and_actions_only_for_the_page_origin(self):
        self.assertEqual(self.call("GET", "/fetch", origin=False)[0], 403)
        self.assertEqual(self.call("POST", "/fetch", {"action": "plan", "urls": [LIST]}, origin=False)[0], 403)

    def test_the_question_is_in_the_status_and_the_answer_settles_it(self):
        self.ctl.startup()
        st, body = self.call("GET", "/fetch")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["firstrun"]["items"], 23)
        st, body = self.call("POST", "/fetch", {"action": "firstrun", "choice": "no"})
        self.assertEqual((st, json.loads(body)["first"]), (200, "no"))
        self.assertIsNone(json.loads(self.call("GET", "/fetch")[1])["firstrun"])
        self.assertEqual(self.fk.saved, [])

    def test_the_downloads_are_served_and_join_the_gallery(self):
        self.ctl.startup()
        self.ctl.links.set_first("no")
        self.assertEqual(self.call("POST", "/fetch", {"action": "start", "urls": [LIST], "compress": False})[0], 200)
        self.ctl.fetch.join(10)
        items = json.loads(self.call("GET", "/gallery.json")[1])["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["video"].startswith("/lib/videos/"))
        self.assertEqual(self.call("GET", items[0]["video"], origin=False)[0], 200)

    def test_a_broken_body_is_a_400(self):
        self.assertEqual(self.call("POST", "/fetch", ["not", "a", "dict"])[0], 400)


class NoCloudLink(unittest.TestCase):
    """The plugin is public: no storage address, no private storage name ships in it."""

    def test_no_private_address_in_the_repo(self):
        bad = re.compile("|".join(["yan" + "dex", "cloud\\." + "icons8", "public\\." + "php"]), re.I)
        found = []
        for p in ROOT.rglob("*"):
            if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts or p.suffix in (".png", ".apng", ".gif", ".svg", ".pyc"):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if bad.search(text):
                found.append(str(p.relative_to(ROOT)))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
