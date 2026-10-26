"""The plugin in a real browser, on a sandbox hub page (needs the hub code and a headless Chrome).

  HUB_CODE=<hub code dir> MG_STUB=<gallery dir> MG_SHOTS=<dir for screenshots> python3 tests/e2e_page.py

HUB_CODE is a checkout of the hub (core, modules, tests); MG_STUB is a gallery folder (gallery.json, previews/, posters/).
Without them the tests are skipped. Own Chrome on its own port, a sandbox journal: the live hub and the owner's Chrome are not touched.
"""
import json
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
CODE = os.environ.get("HUB_CODE", "")
STUB = os.environ.get("MG_STUB", "")
SHOTS = os.environ.get("MG_SHOTS", "")
READY = bool(CODE) and os.path.isdir(os.path.join(CODE, "core")) and os.path.isdir(STUB)

if READY:
    os.chdir(CODE)
    sys.path.insert(0, CODE)
    from tests.test_web_e2e import PageInChrome, READY as CHROME_READY   # noqa: E402
    BASE = PageInChrome
else:
    CHROME_READY = False
    BASE = unittest.TestCase


# What the page throws on its own. The driver's "errors" step reloads the page first and sees only the reload, so a collector is
# installed before the page scripts ({"go": ..., "init": COLLECT}) and read with eval. A <video> that fails is expected for a
# preview that is not uploaded yet (the card must go calm: data-nopreview), it is not an error of the page.
COLLECT = ("window.__mg = []; addEventListener('error', e => { if (!(e.target && e.target.tagName === 'VIDEO')) "
           "window.__mg.push(String(e.message || (e.target && e.target.src) || 'error')); }, true); "
           "addEventListener('unhandledrejection', e => window.__mg.push(String(e.reason))); "
           "const ce = console.error; console.error = (...a) => { window.__mg.push(a.join(' ')); ce.apply(console, a); };")


def cards_visible(sel="document"):
    return f"[...{sel}.querySelectorAll('.mg-card')].filter(c => !c.hidden).length"


class Sandbox(BASE):
    def ext_config(self):
        return {"gallery_dir": STUB}

    def setUp(self):
        from unittest import mock
        super().setUp()   # the page reads hub.json per request, so it can be written after
        cfg = os.path.join(self.state, "hub.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"extensions": {"motion-gallery": {"path": PLUGIN, "web": "main.js", **self.ext_config()}}}, f)
        env = mock.patch.dict(os.environ, {"HUB_CONFIG": cfg, "HUB_STATE_DIR": self.state, "HUB_WEB_PORT": str(self.port)})
        env.start()
        self.addCleanup(env.stop)
        self.proc = subprocess.Popen([sys.executable, os.path.join(PLUGIN, "server.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_proc)
        self.url = f"http://localhost:{self.port}/"
        for name in ("a", "b"):
            self.ev("session.requested", name, session_id=f"s-{name}", cwd="/w")
            self.ev("session.started", name, session_id=f"s-{name}")
        end = time.time() + 8
        while time.time() < end:
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{self.port + 12}/ping", timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    def stop_proc(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def shot(self, name, **kw):
        return {"shot": os.path.join(SHOTS, name), **kw} if SHOTS else {"sleep": 1}

    def run_steps(self, steps):
        """steps: [(label or None, step)] -> {label: result}"""
        got = self.page(*[s for _, s in steps])
        return {label: r for (label, _), r in zip(steps, got) if label}

    def sent(self):
        """What the page put into the journal as a message: nothing is expected, the owner sends it himself."""
        out = []
        with open(os.path.join(self.state, "journal.jsonl"), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                t = json.loads(line).get("type") or ""
                if t.startswith("message.") or t.startswith("owner."):
                    out.append(t)
        return out


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Page(Sandbox):
    def test_view_hover_filter_and_pick(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/a"}),
            (None, {"until": "!!document.querySelector('form.composer textarea')", "ms": 10000}),
            (None, {"eval": "location.hash = '#/x/motion-gallery'; 1"}),
            ("cards", {"until": "document.querySelectorAll('.mg-card').length >= 8", "ms": 10000}),
            (None, {"sleep": 1200}),
            ("posters", {"eval": "[...document.querySelectorAll('.mg-poster')].filter(i => i.complete && i.naturalWidth > 0).length"}),
            (None, self.shot("gallery.png", width=1300, height=900)),
            # hover: a synthetic mouseenter (the driver has no hover step); a video appears after the delay, one at a time
            (None, {"eval": "document.querySelectorAll('.mg-card')[1].dispatchEvent(new MouseEvent('mouseenter')); 1"}),
            ("video1", {"until": "document.querySelectorAll('.mg-card video').length === 1", "ms": 3000}),
            (None, {"eval": "document.querySelectorAll('.mg-card')[2].dispatchEvent(new MouseEvent('mouseenter')); 1"}),
            (None, {"sleep": 600}),
            ("one", {"eval": "[document.querySelectorAll('video').length, document.querySelectorAll('.mg-card')[1].querySelector('video') === null]"}),
            ("playing", {"until": "!!document.querySelector('.mg-card.playing video')", "ms": 6000}),
            ("props", {"eval": "(() => { const v = document.querySelector('.mg-card video'); return v ? [v.readyState, v.muted, v.loop, v.error && v.error.code, v.canPlayType('video/mp4; codecs=avc1.42E01E')] : null; })()"}),
            (None, self.shot("gallery-hover.png", width=1300, height=900)),
            ("left", {"eval": "document.querySelectorAll('.mg-card')[2].dispatchEvent(new MouseEvent('mouseleave')); document.querySelectorAll('video').length"}),
            (None, {"click": "Kinetic type"}),
            ("cat", {"eval": cards_visible()}),
            (None, {"click": "Kinetic type"}),
            ("srcchips", {"eval": "[...document.querySelectorAll('.mg-sources .mg-chip')].map(b => b.textContent)"}),
            ("nolink", {"eval": "[document.querySelectorAll('.mg-card .mg-link').length, document.querySelectorAll('.mg-card .mg-prompt').length]"}),
            (None, {"click": "remotion"}),
            ("src", {"eval": cards_visible()}),
            (None, {"click": "remotion"}),
            ("search", {"eval": "(() => { const s = document.querySelector('.mg-search'); s.value = 'prompt 3:'; s.dispatchEvent(new Event('input')); return [...document.querySelectorAll('.mg-card')].filter(c => !c.hidden).map(c => c.dataset.slug); })()"}),
            ("count", {"eval": "(() => { const s = document.querySelector('.mg-search'); s.value = ''; s.dispatchEvent(new Event('input')); return document.querySelector('.mg-count').textContent; })()"}),
            # pick: goes to the chat opened last (a); a click puts a tag "(Name)" at the cursor, nothing is sent
            (None, {"eval": "document.querySelectorAll('.mg-card')[0].click(); 1"}),
            (None, {"until": "location.hash === '#/s/a' && /^[(].+[)] $/.test(document.querySelector('form.composer textarea').value)", "ms": 10000}),
            ("picked", {"eval": "[location.hash, document.querySelector('form.composer textarea').value]"}),
            (None, self.shot("composer.png", width=1300, height=900)),
            ("errors", {"errors": 1500}),
        ])
        self.assertTrue(r["cards"]["until"], r["cards"])
        self.assertEqual(r["posters"]["eval"], 8, "all eight posters loaded")
        self.assertTrue(r["video1"]["until"], "a video is created on hover")
        self.assertEqual(r["one"]["eval"], [1, True], r["one"])        # one video at a time; the first card is back to its poster
        self.assertTrue(r["playing"]["until"], "the video plays (card has the playing class): %s" % r["props"])
        props = r["props"]["eval"]
        self.assertTrue(props and props[1] and props[2], r["props"])   # muted, looped
        self.assertEqual(r["left"]["eval"], 0)                         # the mouse left: no video in the DOM
        self.assertEqual(r["cat"]["eval"], 2, r["cat"])
        self.assertEqual(len(r["srcchips"]["eval"]), 4, r["srcchips"])   # skillry, prompt-motion, claude-motion, remotion
        self.assertEqual(r["nolink"]["eval"], [0, 0], "no source link and no prompt text on the card")
        self.assertEqual(r["src"]["eval"], 4, r["src"])                   # remotion: two of the four groups, 2 + 2 entries
        self.assertEqual(r["search"]["eval"], ["sample-3"], r["search"])
        self.assertRegex(r["count"]["eval"], r"^8 (of|из) 8$", r["count"])
        hashed, text = r["picked"]["eval"]
        self.assertEqual(hashed, "#/s/a")
        self.assertRegex(text, r"^\(.+\) $", "a click puts a tag, not the prompt text: %r" % text)
        self.assertNotIn("Sample prompt", text)
        self.assertFalse(r["errors"].get("errors"), r["errors"])
        self.assertEqual(self.sent(), [], "nothing is sent by itself")

    def test_button_in_the_chat_input_opens_the_gallery_over_the_chat(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            ("opened", {"until": "document.querySelectorAll('.mg-panel .mg-card').length >= 8", "ms": 10000}),
            (None, {"sleep": 800}),
            # the panel sits right above the input: it does not cover it, there is no backdrop, the input is what is under the pointer
            ("layout", {"eval": GEOMETRY}),
            (None, self.shot("overlay.png", width=1300, height=900)),
            # a click on a card puts it into the input and the gallery stays open; a second click, then typing
            # a mouse pick: the press must not take the focus (defaultPrevented), the click has detail 1 and returns it to the input
            ("md", {"eval": "(() => { const e = new MouseEvent('mousedown', { bubbles: true, cancelable: true }); document.querySelectorAll('.mg-panel .mg-card')[2].dispatchEvent(e); return e.defaultPrevented; })()"}),
            (None, {"eval": "document.querySelectorAll('.mg-panel .mg-card')[2].dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })); 1"}),
            (None, {"until": "document.querySelector('form.composer textarea').value.split('(').length === 2", "ms": 8000}),
            ("focus", {"eval": "document.activeElement && document.activeElement.tagName"}),
            (None, {"eval": "document.querySelectorAll('.mg-panel .mg-card')[4].dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })); 1"}),
            (None, {"until": "document.querySelector('form.composer textarea').value.split('(').length === 3", "ms": 8000}),
            ("after", {"eval": "[!!document.querySelector('.mg-panel'), document.querySelector('form.composer textarea').value, [...document.querySelectorAll('.mg-panel .mg-added')].filter(b => !b.hidden).length, " + GEOMETRY + "]"}),
            (None, self.shot("composer-overlay.png", width=1300, height=900)),
            # typing with the keyboard right after the picks, nothing clicked in the input: the focus is already there
            (None, {"typed": " my words"}),
            ("typed", {"eval": "[!!document.querySelector('.mg-panel'), document.querySelector('form.composer textarea').value.endsWith('my words'), document.activeElement.tagName]"}),
            # Escape pressed in the input closes the gallery too
            (None, {"key": "Escape"}),
            ("escin", {"until": "!document.querySelector('.mg-panel')", "ms": 3000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-panel .mg-close')", "ms": 3000}),
            # the cross closes it; the button opens it again and closes it; Escape inside it closes it
            (None, {"eval": "document.querySelector('.mg-panel .mg-close').click(); 1"}),
            ("x", {"until": "!document.querySelector('.mg-panel')", "ms": 3000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-panel')", "ms": 3000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            ("toggle", {"until": "!document.querySelector('.mg-panel')", "ms": 3000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-panel .mg-search')", "ms": 3000}),
            (None, {"eval": "document.querySelector('.mg-panel .mg-search').focus(); 1"}),
            (None, {"key": "Escape"}),
            ("esc", {"until": "!document.querySelector('.mg-panel')", "ms": 3000}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        self.assertTrue(r["opened"]["until"], r["opened"])
        free, covered = r["layout"]["eval"]["gap"], r["layout"]["eval"]["covered"]
        self.assertGreaterEqual(free, 0, "the panel ends above the input: %s" % r["layout"])
        self.assertFalse(covered, "the input is what is under its own centre: %s" % r["layout"])
        self.assertEqual(r["layout"]["eval"]["backdrop"], 0, "no backdrop")
        stays, text, added, geo = r["after"]["eval"]
        self.assertTrue(stays, "the gallery stays open after a pick")
        self.assertIn("(sample-3)", text)
        self.assertIn("(sample-5)", text)
        self.assertNotIn("Sample prompt", text, "tags only; the prompts travel under the message when it is sent")
        self.assertEqual(added, 2, "both cards carry a check mark")
        self.assertGreaterEqual(geo["gap"], 0, "the panel moved with the input and the panel moved up with it: %s" % geo)
        self.assertFalse(geo["covered"], geo)
        self.assertTrue(r["md"]["eval"], "a press on a card does not take the focus")
        self.assertEqual(r["focus"]["eval"], "TEXTAREA", "after a mouse pick the focus is in the input")
        self.assertEqual(r["typed"]["eval"], [True, True, "TEXTAREA"], "typing works while it is open")
        self.assertTrue(r["escin"]["until"], "Escape pressed in the input closes it")
        self.assertTrue(r["x"]["until"], "the cross closes it")
        self.assertTrue(r["toggle"]["until"], "the button closes it as well")
        self.assertTrue(r["esc"]["until"], "Escape inside it closes it")
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")
        self.assertEqual(self.sent(), [])


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class ButtonOff(Sandbox):
    """composer_button: false - the view works, the chat input has no gallery button."""

    def ext_config(self):
        return {"gallery_dir": STUB, "composer_button": False}

    def test_no_button_in_the_chat_input_when_the_setting_is_off(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer textarea')", "ms": 10000}),
            (None, {"sleep": 2500}),
            ("button", {"eval": "document.querySelectorAll('form.composer .mg-open').length"}),
            (None, {"eval": "location.hash = '#/x/motion-gallery'; 1"}),
            ("cards", {"until": "document.querySelectorAll('.mg-card').length >= 8", "ms": 10000}),
        ])
        self.assertEqual(r["button"]["eval"], 0, "the owner switched the button off")
        self.assertTrue(r["cards"]["until"], "the view itself still works")


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Place(Sandbox):
    """The button sits in the hub's own place composer.tools. A hub without that place (the shared core) gets no button and,
    above all, no error on the Plugins tab; a hub with it gets the button."""

    def test_the_button_follows_the_place_and_nothing_is_reported(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer textarea')", "ms": 10000}),
            (None, {"eval": "import('/static/js/ext.js').then(m => { window.__pl = JSON.stringify({ problems: [...m.problems], place: !!m.SLOTS['composer.tools'] }); window.__place = !!m.SLOTS['composer.tools']; }); 1"}),
            ("info", {"until": "window.__pl !== undefined", "ms": 5000}),
            (None, {"sleep": 2500}),
            # the input takes the button on the next snapshot of the page: with the place, wait for it; without, nothing to wait for
            (None, {"until": "!window.__place || !!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            ("button", {"eval": "document.querySelectorAll('form.composer .mg-open').length"}),
            ("seen", {"eval": "window.__pl"}),
            ("thrown", {"eval": "JSON.stringify(window.__mg)"}),
        ])
        info = json.loads(r["seen"]["eval"])
        self.assertEqual(info["problems"], [], "nothing on the Plugins tab")
        self.assertEqual(json.loads(r["thrown"]["eval"]), [], "nothing thrown on the page")
        self.assertEqual(r["button"]["eval"], 1 if info["place"] else 0,
                         "the button exists exactly when the hub has the place " + str(info["place"]))


# panel above the input? gap = input top - panel bottom (px, >= 0 means above); covered = the element at the input centre is not the input
GEOMETRY = """(() => {
  const p = document.querySelector('.mg-panel'), f = document.querySelector('form.composer'), t = f.querySelector('textarea');
  const pr = p.getBoundingClientRect(), fr = f.getBoundingClientRect(), tr = t.getBoundingClientRect();
  const at = document.elementFromPoint(tr.left + tr.width / 2, tr.top + tr.height / 2);
  return { gap: Math.round(fr.top - pr.bottom), covered: !(at === t || f.contains(at)), backdrop: document.querySelectorAll('.mg-over').length,
           close: !!p.querySelector('.mg-close svg, .mg-close .icon'), vh: innerHeight, top: Math.round(pr.top) };
})()"""


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Ghost(Sandbox):
    """An entry whose preview file is not there (the shared gallery lists examples before their previews are uploaded)."""
    def ext_config(self):
        import shutil
        import tempfile
        root = tempfile.mkdtemp(prefix="mg-ghost-")
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(STUB, root, dirs_exist_ok=True)
        path = os.path.join(root, "gallery.json")
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        rows.append({"slug": "ghost", "author": "Nobody", "category": "Product", "duration": 3, "prompt": "A prompt whose preview is not uploaded",
                     "preview": "previews/ghost-not-uploaded.mp4", "poster": "posters/sample-1.jpg"})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        # like the shared gallery: files by an address (media_base), the list names a preview the address does not have yet
        import functools
        import http.server
        import threading
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a, **k):
                pass
        handler = functools.partial(Quiet, directory=root)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return {"media_base": f"http://127.0.0.1:{srv.server_address[1]}"}

    def test_a_card_without_its_preview_file_stays_a_calm_poster(self):
        card = "[...document.querySelectorAll('.mg-card')].find(c => c.dataset.slug === 'ghost')"
        r = self.run_steps([
            (None, {"go": self.url + "#/s/a", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer textarea')", "ms": 10000}),
            (None, {"eval": "location.hash = '#/x/motion-gallery'; 1"}),
            ("cards", {"until": f"!!({card})", "ms": 10000}),
            (None, {"sleep": 1500}),   # the view loads the list again when it is shown: hover only when the cards have settled
            (None, {"eval": f"({card}).scrollIntoView(); ({card}).dispatchEvent(new MouseEvent('mouseenter')); 1"}),
            ("marked", {"until": f"({card}).dataset.nopreview === '1'", "ms": 8000}),
            ("dbg", {"eval": f"[({card}).dataset.nopreview || '', document.querySelectorAll('video').length, ({card}).className, document.querySelectorAll('.mg-card').length]"}),
            (None, {"sleep": 800}),
            ("state", {"eval": f"[document.querySelectorAll('video').length, document.querySelectorAll('.mg-card.playing').length, ({card}).querySelector('.mg-poster').complete]"}),
            (None, {"eval": f"({card}).dispatchEvent(new MouseEvent('mouseleave')); document.querySelectorAll('.mg-card')[1].dispatchEvent(new MouseEvent('mouseenter')); 1"}),
            ("others", {"until": "document.querySelectorAll('.mg-card video').length === 1", "ms": 4000}),
            (None, {"eval": f"({card}).click(); 1"}),
            ("picked", {"until": "document.querySelector('form.composer textarea').value.length > 2", "ms": 8000}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        self.assertTrue(r["cards"]["until"], r["cards"])
        self.assertTrue(r["marked"]["until"], f"the failed preview marks the card, it is not asked again: {r['dbg']}")
        self.assertEqual(r["state"]["eval"][:2], [0, 0], "no video is left on the page and nothing plays")
        self.assertTrue(r["others"]["until"], "other cards keep their previews")
        self.assertTrue(r["picked"]["until"], "the card still puts its tag")
        self.assertEqual(r["jserr"]["eval"], [], "a missing preview file is not an error of the page")
        self.assertEqual(self.sent(), [])


REAL_BASE = os.environ.get("MG_REAL_BASE", "")


def curl(*args):
    import shutil
    exe = shutil.which("curl")
    if not exe:
        return None
    r = subprocess.run([exe, "-sSL", "--max-time", "20", *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def missing_preview(base):
    """The id of an entry whose preview file is not in the cloud yet (404), or "" when every preview is there.
    curl, because Python on some machines does not trust the certificate of the cloud; the address is only in the environment."""
    from concurrent.futures import ThreadPoolExecutor
    raw = curl(base.rstrip("/") + "/gallery.json")
    items = json.loads(raw) if raw else []
    items = items.get("items", []) if isinstance(items, dict) else items
    items = [it for it in items if (it.get("preview") or "") and not it["preview"].startswith("http")]

    def gone(it):
        code = curl("-r", "0-0", "-o", os.devnull, "-w", "%{http_code}", base.rstrip("/") + "/" + it["preview"].lstrip("/"))
        return bool(code) and code.decode().strip().startswith("404")

    with ThreadPoolExecutor(16) as pool:
        flags = list(pool.map(gone, items))
    return next((it.get("slug") or it.get("id") or "" for it, f in zip(items, flags) if f), "")


@unittest.skipUnless(READY and CHROME_READY and REAL_BASE, "needs MG_REAL_BASE: the address of the real shared gallery (a secret, never in the repo)")
class Real(Sandbox):
    """The shared gallery as it really is: id/seconds/title/skill fields, 373 entries, some preview files not uploaded yet."""
    def ext_config(self):
        return {"media_base": REAL_BASE}

    def test_real_gallery_json_cards_posters_filters_and_missing_previews(self):
        # an entry whose preview is not in the cloud yet, if there is one today (the Ghost test covers the missing file always);
        # otherwise the first card is hovered and its video must play
        gone = missing_preview(REAL_BASE)
        print(f"real gallery: missing preview = {gone or 'none, every preview is uploaded'}", file=sys.stderr)
        pick = f"[...document.querySelectorAll('.mg-card')].find(c => c.dataset.slug === {json.dumps(gone)}) || document.querySelectorAll('.mg-card')[0]"
        # the driver gives one call 60 s: the slow network part and the checks are separate calls on the same page
        r = self.run_steps([
            (None, {"go": self.url + "#/s/a", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer textarea')", "ms": 10000}),
            (None, {"eval": "location.hash = '#/x/motion-gallery'; 1"}),
            ("cards", {"until": "document.querySelectorAll('.mg-card').length >= 300", "ms": 30000}),
        ])
        r.update(self.run_steps([
            (None, {"sleep": 4000}),
            ("posters", {"eval": "[...document.querySelectorAll('.mg-poster')].filter(i => i.src && i.complete && i.naturalWidth > 0).length"}),
            ("total", {"eval": "document.querySelectorAll('.mg-card').length"}),
            ("count", {"eval": "document.querySelector('.mg-count').textContent"}),
            ("chips", {"eval": "[...document.querySelectorAll('.mg-chips .mg-chip')].map(b => b.textContent)"}),
            (None, self.shot("real-gallery.png", width=1300, height=900)),
            (None, {"eval": f"(() => {{ const c = {pick}; c.scrollIntoView(); c.dispatchEvent(new MouseEvent('mouseenter')); return 1; }})()"}),
            (None, {"sleep": 3500}),
            ("video", {"eval": f"(() => {{ const c = {pick}; return [document.querySelectorAll('video').length, c.dataset.nopreview || '', document.querySelectorAll('.mg-card.playing').length]; }})()"}),
            (None, {"eval": f"{pick}.dispatchEvent(new MouseEvent('mouseleave')); 1"}),
            (None, {"eval": "document.querySelectorAll('.mg-card')[0].click(); 1"}),
            (None, {"until": "document.querySelector('form.composer textarea').value.length > 0", "ms": 20000}),
            ("picked", {"eval": "document.querySelector('form.composer textarea').value.length"}),
            ("jserr", {"eval": "window.__mg"}),
        ]))
        self.assertTrue(r["cards"]["until"], r["cards"])
        self.assertEqual(r["total"]["eval"], 373)
        self.assertGreaterEqual(r["posters"]["eval"], 6, "posters of the cards near the screen load from the base")
        self.assertRegex(r["count"]["eval"], r"^373 (of|из) 373$")
        self.assertGreaterEqual(len(r["chips"]["eval"]), 8, r["chips"])   # categories, 4 sources, tags
        n, nopreview, playing = r["video"]["eval"]
        if gone:
            self.assertEqual(nopreview, "1", "the failed preview marks the card")
            self.assertEqual((n, playing), (0, 0), "a preview that is not uploaded yet leaves a calm poster card, no video left")
        else:
            self.assertEqual((n, nopreview), (1, ""), "every preview is in the cloud: the hovered card plays")
        self.assertGreater(r["picked"]["eval"], 2)
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")
        self.assertEqual(self.sent(), [])


def probe(sel):
    """The two layers of an icon (navicon.css) and its scale: opacity of the outline (::before) and of the filled circle (::after)."""
    return ("(() => { const n = document.querySelector(%s); if (!n) return null; const b = getComputedStyle(n, '::before'), a = getComputedStyle(n, '::after'); "
            "const m = new DOMMatrix(getComputedStyle(n).transform); return [b.opacity, a.opacity, +m.a.toFixed(2), a.maskImage.includes('icon-filled.svg') || a.webkitMaskImage.includes('icon-filled.svg'), a.backgroundImage.includes('gradient')]; })()") % json.dumps(sel)


BTN = "form.composer .mg-open .mg-oi"
NAV = '#nav-extra .srow.nav .ext-icon[style*="motion-gallery/icon.svg"]'


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Icon(Sandbox):
    """The icon of the view (the menu) and the gallery button in the input: outline at rest, filled with a gradient on hover."""
    def test_icon_turns_filled_with_a_gradient_on_hover(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            (None, {"eval": "document.body.style.zoom = 3; 1"}),   # the icon is 22 px: a magnified page for the picture
            (None, {"sleep": 400}),
            ("btn_rest", {"eval": probe(BTN)}),
            (None, self.shot("icon-button-rest.png", width=1300, height=520)),
            # the driver has no hover step: a held mouse (pressed on the button, moved over it, never released) keeps :hover
            (None, {"drag": "form.composer .mg-open", "to": "form.composer .mg-open", "keep": True}),
            (None, {"sleep": 600}),
            ("btn_hover", {"eval": probe(BTN)}),
            (None, self.shot("icon-button-hover.png", width=1300, height=520)),
        ])
        self.assertEqual(r["btn_rest"]["eval"][:2], ["1", "0"], "at rest the outline shows, the filled layer is hidden")
        self.assertEqual(r["btn_rest"]["eval"][2], 1)
        self.assertEqual(r["btn_rest"]["eval"][3:], [True, True], "the filled layer is the filled icon with a gradient")
        self.assertEqual(r["btn_hover"]["eval"][:2], ["0", "1"], "on hover the outline goes, the filled gradient layer comes")
        self.assertGreater(r["btn_hover"]["eval"][2], 1.05, "and the icon grows a little")

    def test_menu_icon_turns_filled_with_a_gradient_on_hover(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            # the menu is built after the first snapshot and its button is bound with it: click only when our item is there
            (None, {"until": "!!document.querySelector('#navmenu[data-bound]') && !!document.querySelector('%s')" % NAV, "ms": 10000}),
            (None, {"eval": "document.querySelector('#navmenu').click(); document.body.style.zoom = 3; 1"}),
            (None, {"until": "!document.querySelector('#nav-extra').hidden", "ms": 6000}),
            (None, {"sleep": 400}),
            ("nav_rest", {"eval": probe(NAV)}),
            (None, self.shot("icon-menu-rest.png", width=1300, height=700)),
            (None, {"drag": '.srow.nav:has(.ext-icon[style*="motion-gallery/icon.svg"])', "to": '.srow.nav:has(.ext-icon[style*="motion-gallery/icon.svg"])', "keep": True}),
            (None, {"sleep": 600}),
            ("nav_hover", {"eval": probe(NAV)}),
            (None, self.shot("icon-menu-hover.png", width=1300, height=700)),
        ])
        self.assertEqual(r["nav_rest"]["eval"][:2], ["1", "0"])
        self.assertEqual(r["nav_hover"]["eval"][:2], ["0", "1"])
        self.assertGreater(r["nav_hover"]["eval"][2], 1.05)

    def test_menu_rebuild_under_a_held_mouse_does_not_restart_the_rings(self):
        """The hub puts new nodes into the menu on every snapshot: the icon under the mouse must go on with the same hover look and
        the same ring phase (0.4.4: its filled layer faded in again and the rings were born in the center again, a jerk of the loop)."""
        ROW = '.srow.nav:has(.ext-icon[style*="motion-gallery/icon.svg"])'
        watch = ("(() => { window.__w = []; const sel = %s; const tick = () => { const n = document.querySelector(sel); if (n) { "
                 "const a = document.getAnimations().find(x => x.effect && x.effect.target === n && (x.animationName || '') === 'mgi-ring1'); "
                 "window.__w.push([n.__id || (n.__id = Math.random().toString(36).slice(2)), a ? Math.round(a.currentTime) : null, getComputedStyle(n, '::after').opacity, "
                 "+new DOMMatrix(getComputedStyle(n).transform).a.toFixed(2), n.hasAttribute('data-mgi-resume')]); } requestAnimationFrame(tick); }; tick(); return 1; })()") % json.dumps(NAV)
        swap = "(() => { const r = document.querySelector(%s); r.replaceWith(r.cloneNode(true)); return 1; })()" % json.dumps(ROW)
        steps = [
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('#navmenu[data-bound]') && !!document.querySelector('%s')" % NAV, "ms": 10000}),
            (None, {"eval": "document.querySelector('#navmenu').click(); 1"}),
            (None, {"until": "!document.querySelector('#nav-extra').hidden", "ms": 6000}),
            (None, {"drag": ROW, "to": ROW, "keep": True}),
            (None, {"sleep": 1300}),
            (None, {"eval": watch}),
            (None, {"sleep": 500}),
        ]
        for _ in range(3):
            steps += [(None, {"eval": swap}), (None, {"sleep": 700})]
        steps += [("log", {"eval": "JSON.stringify(window.__w)"}), ("errors", {"eval": "window.__mg"})]
        r = self.run_steps(steps)
        log = json.loads(r["log"]["eval"])
        ids = []
        for e in log:
            if not ids or ids[-1] != e[0]:
                ids.append(e[0])
        self.assertEqual(len(ids), 4, "the node was replaced three times")
        for i in range(1, len(log)):
            prev, cur = log[i - 1], log[i]
            self.assertEqual(cur[2], "1", f"the filled layer never drops out of the hover look: {prev} -> {cur}")
            self.assertEqual(cur[3], 1.12, f"nor does the scale: {prev} -> {cur}")
            if cur[0] != prev[0]:   # the new node: the rings go on from where the old ones were (a frame later, not from zero)
                self.assertIsNotNone(cur[1], cur)
                self.assertGreater(cur[1], prev[1], f"the rings of the new icon go on, not restart: {prev} -> {cur}")
                self.assertLess(cur[1] - prev[1], 120, f"and only a frame or two later: {prev} -> {cur}")
        self.assertFalse(log[-1][4], "the forced look is released once the real hover is there")


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Lightbox(Sandbox):
    """The magnifier in the corner of a card: the example full screen (video with sound and controls, caption, arrows, Escape, cross)."""
    def test_magnifier_opens_the_lightbox_over_the_gallery_over_a_chat(self):
        card = "'.mg-panel .mg-card'"
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT}),
            (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "document.querySelectorAll('.mg-panel .mg-card').length >= 8", "ms": 10000}),
            (None, {"sleep": 800}),
            ("rest", {"eval": "getComputedStyle(document.querySelector('.mg-panel .mg-card .mg-zoom')).opacity"}),
            # a held mouse over the card keeps :hover: the magnifier shows in the top right corner
            (None, {"drag": ".mg-panel .mg-card", "to": ".mg-panel .mg-card", "keep": True}),
            (None, {"sleep": 500}),
            ("hover", {"eval": "(() => { const z = document.querySelector('.mg-panel .mg-card .mg-zoom'), m = z.closest('.mg-media').getBoundingClientRect(), r = z.getBoundingClientRect();"
                               " return [getComputedStyle(z).opacity, Math.round(m.right - r.right), Math.round(r.top - m.top), document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === z || z.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2))]; })()"}),
            (None, self.shot("card-magnifier.png")),
            (None, {"eval": "document.querySelector('.mg-panel .mg-card .mg-zoom').click(); 1"}),
            ("open", {"until": "!!document.querySelector('.mg-lb video')", "ms": 4000}),
            (None, {"sleep": 1200}),
            ("state", {"eval": "(() => { const v = document.querySelector('.mg-lb video'); return [v.controls, v.muted, !!v.src, document.querySelector('form.composer textarea').value.length, !!document.querySelector('.mg-panel'),"
                               " document.querySelector('.mg-lb-count').textContent, document.querySelector('.mg-lb').getAttribute('role'), document.querySelector('.mg-lb-prev').disabled, document.querySelector('.mg-lb-next').disabled]; })()"}),
            (None, self.shot("lightbox.png", width=1300, height=900)),
            (None, {"key": "ArrowRight"}),
            ("right", {"eval": "[document.querySelector('.mg-lb-count').textContent, document.querySelectorAll('.mg-lb video').length, document.querySelector('.mg-lb-prev').disabled]"}),
            (None, {"key": "ArrowLeft"}),
            ("left", {"eval": "document.querySelector('.mg-lb-count').textContent"}),
            (None, {"key": "Escape"}),
            ("esc", {"until": "!document.querySelector('.mg-lb')", "ms": 3000}),
            ("panel", {"eval": "[!!document.querySelector('.mg-panel'), document.querySelectorAll('video').length]"}),
            # the card itself still puts the example into the chat
            (None, {"eval": "document.querySelectorAll('.mg-panel .mg-card')[1].dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })); 1"}),
            (None, {"until": "document.querySelector('form.composer textarea').value.length > 0", "ms": 8000}),
            # the cross closes it; a filter narrows the list the arrows walk through
            (None, {"eval": "const s = document.querySelector('.mg-panel .mg-search'); s.value = 'prompt 3:'; s.dispatchEvent(new Event('input')); 1"}),
            (None, {"eval": "[...document.querySelectorAll('.mg-panel .mg-card')].find(c => !c.hidden).querySelector('.mg-zoom').click(); 1"}),
            ("filtered", {"until": "!!document.querySelector('.mg-lb video')", "ms": 4000}),
            ("fcount", {"eval": "[document.querySelector('.mg-lb-count').textContent, document.querySelector('.mg-lb-next').disabled]"}),
            (None, {"eval": "document.querySelector('.mg-lb-x').click(); 1"}),
            ("x", {"until": "!document.querySelector('.mg-lb')", "ms": 3000}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        self.assertEqual(r["rest"]["eval"], "0", "the magnifier shows only on hover")
        op, left, top, on_top = r["hover"]["eval"]
        self.assertEqual((op, left, top), ("1", 8, 8), "the magnifier is in the top right corner of the card")
        self.assertTrue(on_top, "and the playing preview does not cover it")
        self.assertTrue(r["open"]["until"], r["open"])
        controls, muted, has_src, chips, panel, count, role, prev_off, next_off = r["state"]["eval"]
        self.assertTrue(controls and has_src and not muted, "the video has controls, a source and sound: %s" % r["state"])
        self.assertEqual((chips, panel), (0, True), "the magnifier does not put anything into the chat")
        self.assertRegex(count, r"^1 (of|из) 8$")
        self.assertEqual((role, prev_off, next_off), ("dialog", True, False))
        self.assertEqual(r["right"]["eval"][1:], [1, False], "one video at a time, the back arrow is alive: %s" % r["right"])
        self.assertRegex(r["right"]["eval"][0], r"^2 (of|из) 8$")
        self.assertRegex(r["left"]["eval"], r"^1 (of|из) 8$")
        self.assertTrue(r["esc"]["until"], "Escape closes the lightbox")
        self.assertEqual(r["panel"]["eval"], [True, 0], "and only it: the gallery stays, no video is left playing")
        self.assertTrue(r["filtered"]["until"])
        self.assertEqual(r["fcount"]["eval"][1], True, "one card left by the filter: nowhere to step: %s" % r["fcount"])
        self.assertRegex(r["fcount"]["eval"][0], r"^1 (of|из) 1$")
        self.assertTrue(r["x"]["until"], "the cross closes it")
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")
        self.assertEqual(self.sent(), [])


    def test_the_running_man_shows_while_the_list_a_poster_and_a_video_load(self):
        # a watcher installed before the page scripts: where the runner appeared (it lives only while something loads)
        watch = ("window.__run = {}; new MutationObserver(() => { for (const [k, sel] of [['note', '.mg-note .mg-run'], ['card', '.mg-media .mg-run'], ['lb', '.mg-lb .mg-run']]) "
                 "{ const n = document.querySelector(sel); if (n && !window.__run[k]) window.__run[k] = [n.src.split('/').slice(-2).join('/'), n.style.width, getComputedStyle(n).filter]; } })"
                 ".observe(document, { subtree: true, childList: true });")
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b", "init": COLLECT + watch}),
            (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "document.querySelectorAll('.mg-panel .mg-card').length >= 8", "ms": 10000}),
            (None, {"sleep": 1500}),
            ("left", {"eval": "[document.querySelectorAll('.mg-run').length, document.querySelector('.mg-note').hidden]"}),
            (None, {"eval": "document.querySelector('.mg-panel .mg-card .mg-zoom').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-lb video')", "ms": 4000}),
            (None, {"sleep": 1500}),
            ("lbleft", {"eval": "document.querySelectorAll('.mg-lb .mg-run').length"}),
            ("seen", {"eval": "window.__run"}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        seen = r["seen"]["eval"]
        self.assertEqual(r["left"]["eval"][0], 0, "no runner is left on the page when everything has loaded: %s" % r["left"])
        self.assertEqual(r["lbleft"]["eval"], 0, "the runner leaves the lightbox when the video has data")
        self.assertIn("card", seen, "a runner showed on a card while its poster loaded: %s" % seen)
        self.assertEqual(seen["card"][0], "loader/runner-anim.png", seen)
        self.assertEqual(seen["card"][1], "20px", "as small as the palette icon of Hub Design")
        self.assertEqual(seen["lb"][1], "20px")
        self.assertEqual(seen["lb"][0], "loader/runner-anim.png", "and over the video in the lightbox: %s" % seen)
        self.assertIn("invert", seen["lb"][2], "on the dark backdrop the black icon is inverted")
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Removal(Sandbox):
    """Delete lives under the caption in the lightbox, with a few seconds of undo; the picked mark and the magnifier share the corner."""
    def ext_config(self):
        import shutil
        import tempfile
        self.copy = tempfile.mkdtemp(prefix="mg-copy-")   # a copy: the real stub is never deleted from
        shutil.copytree(STUB, self.copy, dirs_exist_ok=True)
        self.addCleanup(shutil.rmtree, self.copy, True)
        return {"gallery_dir": self.copy}

    def slugs(self):
        with open(os.path.join(self.copy, "gallery.json"), encoding="utf-8") as f:
            raw = json.load(f)
        rows = raw.get("items") if isinstance(raw, dict) else raw
        return [r.get("slug") or r.get("id") for r in rows]

    OPEN = [
        (None, {"go": "URL#/s/b", "init": COLLECT}),
        (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
        (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
        (None, {"until": "document.querySelectorAll('.mg-panel .mg-card').length >= 8", "ms": 10000}),
        (None, {"sleep": 600}),
    ]

    def open_steps(self):
        return [(l, {**s, "go": s["go"].replace("URL", self.url)} if "go" in s else s) for l, s in self.OPEN]

    def test_delete_button_under_the_caption_hides_the_card_and_waits_for_the_undo(self):
        before = len(self.slugs())
        vis = "[...document.querySelectorAll('.mg-panel .mg-card')].filter(c => !c.hidden).length"
        r = self.run_steps(self.open_steps() + [
            ("n0", {"eval": vis}),
            (None, {"eval": "document.querySelector('.mg-panel .mg-card .mg-zoom').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-lb video')", "ms": 4000}),
            ("acts", {"eval": "[...document.querySelectorAll('.mg-lb-actions .mg-lb-act')].filter(b => !b.hidden).map(b => b.className)"}),
            ("nocross", {"eval": "[!!document.querySelector('.mg-card .mg-del'), !!document.querySelector('.mg-lb-btn.mg-lb-del')]"}),
            (None, self.shot("lightbox-actions.png", width=1300, height=900)),
            (None, {"eval": "document.querySelector('.mg-lb-del').click(); 1"}),
            ("plate", {"until": "!!document.querySelector('.mg-undo')", "ms": 3000}),
            ("n1", {"eval": vis}),
            ("lb", {"eval": "document.querySelector('.mg-lb-count').textContent"}),
            (None, self.shot("undo-plate.png", width=1300, height=900)),
            (None, {"eval": "document.querySelector('.mg-undo-btn').click(); 1"}),
            ("n2", {"eval": "[" + vis + ", !!document.querySelector('.mg-undo')]"}),
            (None, {"sleep": 7000}),
            ("n3", {"eval": vis}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        acts = r["acts"]["eval"]
        self.assertEqual(len(acts), 2, "the link to the source and delete, under the caption: %s" % acts)
        self.assertIn("mg-lb-del", acts[-1])
        self.assertEqual(r["nocross"]["eval"], [False, False], "no cross on the card, no round button at the top")
        self.assertTrue(r["plate"]["until"], "the undo plate shows")
        self.assertEqual(r["n1"]["eval"], r["n0"]["eval"] - 1, "the card left the grid at once")
        self.assertRegex(r["lb"]["eval"], r"^1 (of|из) %d$" % (r["n0"]["eval"] - 1), "the lightbox went on to the next example")
        self.assertEqual(r["n2"]["eval"], [r["n0"]["eval"], False], "undo brings the card back and takes the plate away")
        self.assertEqual(r["n3"]["eval"], r["n0"]["eval"], "and nothing was deleted when the time passed")
        self.assertEqual(len(self.slugs()), before)
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")

    def test_without_the_undo_the_example_is_taken_off_the_disk(self):
        slugs = self.slugs()
        r = self.run_steps(self.open_steps() + [
            ("slug", {"eval": "document.querySelector('.mg-panel .mg-card').dataset.slug"}),
            (None, {"eval": "document.querySelector('.mg-panel .mg-card .mg-zoom').click(); 1"}),
            (None, {"until": "!!document.querySelector('.mg-lb video')", "ms": 4000}),
            (None, {"eval": "document.querySelector('.mg-lb-del').click(); 1"}),
            (None, {"key": "Escape"}),
            (None, {"sleep": 8000}),
            ("after", {"eval": "[!!document.querySelector('.mg-undo'), document.querySelectorAll('.mg-panel .mg-card').length]"}),
            ("jserr", {"eval": "window.__mg"}),
        ])
        gone = r["slug"]["eval"]
        self.assertIn(gone, slugs)
        self.assertEqual(self.slugs(), [s for s in slugs if s != gone], "gallery.json lost exactly that example")
        self.assertEqual(r["after"]["eval"], [False, len(slugs) - 1], "the plate is gone and the grid is one card shorter: %s" % r["after"])
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")

    def test_the_picked_mark_and_the_magnifier_do_not_overlap(self):
        r = self.run_steps(self.open_steps() + [
            (None, {"eval": "document.querySelectorAll('.mg-panel .mg-card')[0].dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })); 1"}),
            (None, {"until": "[...document.querySelectorAll('.mg-panel .mg-added')].some(b => !b.hidden)", "ms": 8000}),
            (None, {"drag": ".mg-panel .mg-card", "to": ".mg-panel .mg-card", "keep": True}),
            (None, {"sleep": 500}),
            ("rects", {"eval": "(() => { const c = document.querySelector('.mg-panel .mg-card'), m = c.querySelector('.mg-media').getBoundingClientRect(), a = c.querySelector('.mg-added').getBoundingClientRect(), z = c.querySelector('.mg-zoom').getBoundingClientRect();"
                               " return [Math.round(m.right - a.right), Math.round(a.top - m.top), Math.round(a.left - z.right), Math.round(z.top - m.top), getComputedStyle(c.querySelector('.mg-zoom')).opacity]; })()"}),
            (None, self.shot("card-picked.png", width=1300, height=900)),
            ("jserr", {"eval": "window.__mg"}),
        ])
        right, top, gap, ztop, op = r["rects"]["eval"]
        self.assertEqual((right, top, ztop), (8, 8, 8), "the check mark is in the top right corner, the magnifier at the same height")
        self.assertGreaterEqual(gap, 4, "the magnifier sits left of the check mark with a gap: %s" % r["rects"])
        self.assertEqual(op, "1")
        self.assertEqual(r["jserr"]["eval"], [], "the page threw nothing")


if __name__ == "__main__":
    # Page inherits PageInChrome: only our own tests, not the whole hub e2e suite
    own = [f"{c.__name__}.{n}" for c in (Page, Ghost, Real, Icon, Lightbox, Removal) for n in vars(c) if n.startswith("test_")]
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    unittest.main(argv=[sys.argv[0], *flags, *(names or own)])
