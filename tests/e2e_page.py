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


def cards_visible(sel="document"):
    return f"[...{sel}.querySelectorAll('.mg-card')].filter(c => !c.hidden).length"


@unittest.skipUnless(READY and CHROME_READY, "needs HUB_CODE, MG_STUB, node and a headless Chrome")
class Page(BASE):
    def setUp(self):
        from unittest import mock
        super().setUp()   # the page reads hub.json per request, so it can be written after
        cfg = os.path.join(self.state, "hub.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"extensions": {"motion-gallery": {"path": PLUGIN, "web": "main.js", "gallery_dir": STUB}}}, f)
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
            ("link", {"eval": "(() => { const a = document.querySelector('.mg-card .mg-link'); return a && [a.href, a.title]; })()"}),
            (None, {"click": "remotion"}),
            ("src", {"eval": cards_visible()}),
            (None, {"click": "remotion"}),
            ("search", {"eval": "(() => { const s = document.querySelector('.mg-search'); s.value = 'prompt 3:'; s.dispatchEvent(new Event('input')); return [...document.querySelectorAll('.mg-card')].filter(c => !c.hidden).map(c => c.dataset.slug); })()"}),
            ("count", {"eval": "(() => { const s = document.querySelector('.mg-search'); s.value = ''; s.dispatchEvent(new Event('input')); return document.querySelector('.mg-count').textContent; })()"}),
            # pick: goes to the chat opened last (a); the poster is a chip, the prompt is text, nothing is sent
            (None, {"eval": "document.querySelectorAll('.mg-card')[0].click(); 1"}),
            (None, {"until": "location.hash === '#/s/a' && document.querySelector('form.composer textarea').value.length > 0", "ms": 10000}),
            (None, {"until": "document.querySelectorAll('form.composer .pchip').length === 1", "ms": 8000}),
            ("picked", {"eval": "[location.hash, document.querySelector('form.composer textarea').value, document.querySelectorAll('form.composer .pchip').length, document.querySelector('form.composer .pchip').textContent]"}),
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
        self.assertTrue(r["link"]["eval"][0].startswith("https://example.com/"), r["link"])
        self.assertEqual(r["src"]["eval"], 4, r["src"])                   # remotion: two of the four groups, 2 + 2 entries
        self.assertEqual(r["search"]["eval"], ["sample-3"], r["search"])
        self.assertRegex(r["count"]["eval"], r"^8 (of|из) 8$", r["count"])
        hashed, text, chips, name = r["picked"]["eval"]
        self.assertEqual(hashed, "#/s/a")
        self.assertIn("Sample prompt 1", text)
        self.assertEqual(chips, 1)
        self.assertIn("Image", name or "")   # the page names the chip itself: "[Image #1] · 13 KB"
        self.assertFalse(r["errors"].get("errors"), r["errors"])
        self.assertEqual(self.sent(), [], "nothing is sent by itself")

    def test_button_in_the_chat_input_opens_the_gallery_over_the_chat(self):
        r = self.run_steps([
            (None, {"go": self.url + "#/s/b"}),
            (None, {"until": "!!document.querySelector('form.composer .mg-open')", "ms": 10000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            ("opened", {"until": "document.querySelectorAll('.mg-over .mg-card').length >= 8", "ms": 10000}),
            (None, self.shot("overlay.png", width=1300, height=900)),
            (None, {"key": "Escape"}),
            ("esc", {"until": "!document.querySelector('.mg-over')", "ms": 3000}),
            (None, {"eval": "document.querySelector('form.composer .mg-open').click(); 1"}),
            (None, {"until": "document.querySelectorAll('.mg-over .mg-card').length >= 8", "ms": 10000}),
            (None, {"eval": "document.querySelectorAll('.mg-over .mg-card')[2].click(); 1"}),
            (None, {"until": "!document.querySelector('.mg-over') && document.querySelector('form.composer textarea').value.length > 0", "ms": 10000}),
            (None, {"until": "document.querySelectorAll('form.composer .pchip').length === 1", "ms": 8000}),
            ("picked", {"eval": "[location.hash, document.querySelector('form.composer textarea').value, document.querySelectorAll('form.composer .pchip').length]"}),
            (None, self.shot("composer-overlay.png", width=1300, height=900)),
            ("errors", {"errors": 1500}),
        ])
        self.assertTrue(r["opened"]["until"], r["opened"])
        self.assertTrue(r["esc"]["until"], "Escape closes it")
        hashed, text, chips = r["picked"]["eval"]
        self.assertEqual(hashed, "#/s/b")
        self.assertIn("Sample prompt 3", text)
        self.assertEqual(chips, 1)
        self.assertFalse(r["errors"].get("errors"), r["errors"])
        self.assertEqual(self.sent(), [])


if __name__ == "__main__":
    # Page inherits PageInChrome: only our own tests, not the whole hub e2e suite
    own = [f"Page.{n}" for n in vars(Page) if n.startswith("test_")]
    unittest.main(argv=[sys.argv[0], *sys.argv[1:], *own])
