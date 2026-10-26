"""The plugin ships with no sources, no agents and no storage of anyone: all of it is a setting (hub.json extensions.<account>:motion-gallery),
and a hub without settings gets a working gallery that sends nothing anywhere."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["HUB_WEB_PORT"] = "18787"
os.environ["HUB_STATE_DIR"] = tempfile.mkdtemp(prefix="mg-state-")   # never the live hub
import dav  # noqa: E402
import fetcher  # noqa: E402
import firstrun  # noqa: E402
import linkctl  # noqa: E402
import links as linkmem  # noqa: E402
import server  # noqa: E402
import tgpost  # noqa: E402

ENV = ("MOTION_GALLERY_DIR", "MOTION_GALLERY_BASE", "MOTION_GALLERY_DAV_LOGIN", "MOTION_GALLERY_DAV_FOLDER", "MOTION_GALLERY_DELETE",
       "MOTION_GALLERY_SOURCES", "MOTION_GALLERY_AGENTS", "MOTION_GALLERY_COMPOSER_BUTTON")


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.keep = {k: os.environ.pop(k, None) for k in ENV}
        self.cfg = {}
        self.config = server.config
        server.config = lambda: {"extensions": {"acct:motion-gallery": self.cfg}} if self.cfg is not None else {}

    def tearDown(self):
        server.config = self.config
        for k, v in self.keep.items():
            if v is not None:
                os.environ[k] = v
        self.tmp.cleanup()

    def ctl(self):
        return server.make_ctl()


class Defaults(Case):
    """No settings at all."""

    def test_nothing_of_ours_without_settings(self):
        self.assertEqual(server.sources_setting(), [])
        self.assertEqual(server.agents_setting(), [])
        self.assertTrue(server.composer_button())
        self.assertIsNone(server.make_dav())            # no login file: no storage
        self.assertEqual(dav.DEFAULT_FOLDER, "motion-gallery")

    def test_no_links_no_question_no_post(self):
        os.environ["HUB_STATE_DIR"] = self.root
        c = server.make_ctl()
        c.watch = False
        self.assertEqual(c.startup(), "")
        self.assertEqual(c.links.urls(), [])
        self.assertIsNone(c.question())
        self.assertIsNone(c.to_post())
        self.assertEqual(c.links.first, "")
        self.assertFalse(c.links.seeded, "nothing was put: the links by default may still come when the owner sets them")

    def test_the_defaults_come_when_the_owner_sets_them_later(self):
        m = linkmem.Links(os.path.join(self.root, "links.json"))
        self.assertEqual(m.seed([]), [])
        self.assertEqual(m.seed(["https://a.test"]), ["https://a.test"])


class FromHubJson(Case):
    def test_lists_are_read_as_a_list_or_a_comma_string(self):
        self.cfg = {"sources": ["https://a.test/x", " https://b.test ", "ftp://c.test", "file:///etc/passwd", 5, "javascript:x", ""], "agents": "writer, designer ,"}
        self.assertEqual(server.sources_setting(), ["https://a.test/x", "https://b.test"])   # only http(s)
        self.assertEqual(server.agents_setting(), ["writer", "designer"])
        self.cfg = {"sources": "https://a.test, https://b.test;file:///x"}
        self.assertEqual(server.sources_setting(), ["https://a.test", "https://b.test"])

    def test_the_environment_wins(self):
        self.cfg = {"sources": ["https://a.test"], "agents": ["x"]}
        os.environ["MOTION_GALLERY_SOURCES"] = "https://env.test"
        os.environ["MOTION_GALLERY_AGENTS"] = "y"
        self.assertEqual(server.sources_setting(), ["https://env.test"])
        self.assertEqual(server.agents_setting(), ["y"])

    def test_a_real_false_is_false(self):
        self.cfg = {"allow_delete": False, "composer_button": False}
        self.assertFalse(server.deleting_allowed())
        self.assertFalse(server.composer_button())
        self.cfg = {"allow_delete": "off", "composer_button": "no"}
        self.assertFalse(server.deleting_allowed())
        self.assertFalse(server.composer_button())
        self.cfg = {"allow_delete": True, "composer_button": True}
        self.assertTrue(server.deleting_allowed())
        self.assertTrue(server.composer_button())

    def test_the_storage_is_the_owners_login_and_folder(self):
        login = os.path.join(self.root, "login.json")
        Path(login).write_text(json.dumps({"server": "https://dav.test", "user": "u", "password": "p"}), encoding="utf-8")
        self.cfg = {"dav_login": login, "dav_folder": "My Gallery"}
        d = server.make_dav()
        self.assertIsNotNone(d)
        self.assertTrue(d.base.endswith("/My%20Gallery"), d.base)

    def test_sources_and_agents_reach_the_question(self):
        os.environ["HUB_STATE_DIR"] = self.root
        self.cfg = {"sources": ["https://skillry.dev/ai-videos", "https://github.com/a/b"], "agents": ["writer"]}
        c = server.make_ctl()
        c.watch = False
        self.assertEqual(c.startup(), "seeded")
        q = c.question()
        self.assertEqual((q["sources"], q["agents"]), (2, ["writer"]))
        self.assertEqual(q["links"], ["https://skillry.dev/ai-videos", "https://github.com/a/b"])


class Estimate(unittest.TestCase):
    """The numbers of the question follow the sources the downloader reads: about 23 examples, 22 MB and a minute for each."""

    def test_by_the_readable_sources(self):
        self.assertEqual(firstrun.facts(2, 1), {"items": 23, "mb": 22, "minutes": 1})
        self.assertEqual(firstrun.facts(8, 3), {"items": 69, "mb": 66, "minutes": 3})

    def test_no_readable_source_counts_the_links(self):
        self.assertEqual(firstrun.facts(2, 0), {"items": 46, "mb": 44, "minutes": 2})


class Agents(unittest.TestCase):
    def test_the_missing_ones_are_of_the_list_given(self):
        sessions = {"hub": {"kind": "hub"}, "a": {}, "b": {"kind": "hub"}}
        self.assertEqual(firstrun.missing(sessions, ["a", "b", "c"]), ["b", "c"])
        self.assertEqual(firstrun.missing(sessions, []), [])
        self.assertEqual(firstrun.missing(None, ["a"]), ["a"])

    def test_the_text_names_only_the_agents_asked_for(self):
        t = firstrun.text("en", 2, 1, ["b"], ["a", "b"])
        self.assertIn("a, b", t)
        self.assertIn("Not in the hub yet: b", t)
        self.assertNotIn("screenwriter", t + firstrun.text("ru", 2, 1, [], []))
        self.assertNotIn("agents", firstrun.text("en", 2, 1, [], []).split("\n\n")[-1].lower())   # no agents wanted: no word about them
        self.assertNotIn("Preinstalled", firstrun.text("en", 2, 1, [], []))

    def test_a_post_for_a_hub_that_wants_no_agents_has_no_agent_part(self):
        c = linkctl.Ctl(linkmem.Links(os.path.join(tempfile.mkdtemp(prefix="mg-l-"), "links.json")),
                        fetcher.Fetcher(tempfile.mkdtemp(prefix="mg-f-")), defaults=["https://skillry.dev/ai-videos"])
        c.watch = False
        c.startup()
        sent = []
        original = tgpost.rules
        tgpost.rules = lambda: object()
        try:
            p = tgpost.Poster(tempfile.mkdtemp(prefix="mg-s-"), lambda: c, state=lambda: {"sessions": {}}, emit=lambda k, d: sent.append((k, d)))
            p.first_question()
        finally:
            tgpost.rules = original
        self.assertEqual(len(sent), 1)
        self.assertNotIn("agents", sent[0][1]["text"].lower())


class Limits(unittest.TestCase):
    def test_a_prompt_is_cut_at_a_sane_size(self):
        self.assertLessEqual(server.PROMPT_MAX, 20000)


class Http(Case):
    def test_the_status_carries_the_settings(self):
        os.environ["HUB_STATE_DIR"] = self.root
        self.cfg = {"agents": ["writer"], "composer_button": False}
        old = server.CTL
        server.CTL = server.make_ctl()
        server.CTL.watch = False
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        srv.daemon_threads = True
        port0 = server.PORT
        server.PORT = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/fetch", headers={"Host": f"localhost:{port}", "Origin": sorted(server.page_origins())[0]})
            r = c.getresponse()
            body = json.loads(r.read())
            self.assertEqual(r.status, 200)
            self.assertEqual(body["settings"], {"agents": ["writer"], "composer_button": False})
        finally:
            srv.shutdown()
            srv.server_close()
            server.PORT = port0
            server.CTL = old


if __name__ == "__main__":
    unittest.main()
