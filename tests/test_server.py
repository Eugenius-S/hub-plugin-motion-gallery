import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["HUB_WEB_PORT"] = "18787"
os.environ["HUB_STATE_DIR"] = tempfile.mkdtemp(prefix="mg-state-")   # never the live hub
import server  # noqa: E402

PAGE = "http://localhost:18787"
JPEG = b"\xff\xd8\xff\xe0" + b"j" * 200
MP4 = bytes(range(256)) * 8   # 2048 bytes, easy to slice


def make_gallery(folder, rows):
    folder = Path(folder)
    (folder / "previews").mkdir(exist_ok=True)
    (folder / "posters").mkdir(exist_ok=True)
    (folder / "gallery.json").write_text(json.dumps(rows), encoding="utf-8")
    (folder / "previews" / "a.mp4").write_bytes(MP4)
    (folder / "posters" / "a.jpg").write_bytes(JPEG)


class Normalise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        make_gallery(self.root, [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_by_slug_and_fields(self):
        items = server.normalise(self.root, [{"slug": "a", "category": " Product ", "author": "Anna", "duration": "6.54",
                                              "tags": "loop, 3d;x", "prompt": " P ", "post": "https://x.test/p"}])
        self.assertEqual(len(items), 1)
        i = items[0]
        self.assertEqual((i["preview"], i["poster"]), ("/f/previews/a.mp4", "/f/posters/a.jpg"))
        self.assertEqual((i["category"], i["duration"], i["prompt"], i["post"]), ("Product", 6.5, "P", "https://x.test/p"))
        self.assertEqual(i["tags"], ["loop", "3d", "x"])

    def test_wrapped_list_and_bad_rows(self):
        rows = {"items": [{"slug": "a"}, "junk", {"slug": ""}, {"slug": "a"}, {"slug": "nofiles"}, {"prompt": "no slug", "poster": "posters/a.jpg"}]}
        self.assertEqual([i["slug"] for i in server.normalise(self.root, rows)], ["a"])   # dupes, no slug, no pictures: dropped
        self.assertEqual(server.normalise(self.root, "nope"), [])
        self.assertEqual(server.normalise(self.root, {"items": 5}), [])

    def test_urls_pass_and_paths_cannot_leave_the_folder(self):
        outside = Path(self.root).parent / "secret.jpg"
        outside.write_bytes(JPEG)
        try:
            items = server.normalise(self.root, [
                {"slug": "r", "poster": "https://cdn.test/r.jpg", "preview": "http://cdn.test/r.mp4"},
                {"slug": "esc", "poster": "../secret.jpg", "preview": "..\\secret.jpg"},
                {"slug": "abs", "poster": str(outside)},
                {"slug": "ok", "poster": "posters/a.jpg", "post": "javascript:alert(1)", "page": "ftp://x"},
            ])
        finally:
            outside.unlink()
        self.assertEqual([i["slug"] for i in items], ["r", "ok"])
        self.assertEqual(items[0]["poster"], "https://cdn.test/r.jpg")
        self.assertEqual((items[1]["post"], items[1]["page"]), ("", ""))   # only http(s) links

    def test_the_real_file_format_id_seconds_title_skill(self):
        """The shared gallery.json has id (not slug), seconds (not duration), title, kind, skill, prompt_note; prompts reach 15k."""
        long_prompt = "word " * 3000
        rows = [
            {"id": "x-1", "sources": ["skillry"], "title": " T ", "author": "A", "category": "", "tags": ["GLSL"], "kind": "Prompt",
             "prompt": long_prompt, "prompt_note": "Attach the brand image.", "skill": None, "post": "https://x.test/p",
             "pages": {"skillry": "https://skillry.test/x-1"}, "seconds": 27.6, "video": "videos/x-1.mp4", "preview": "previews/x-1.mp4",
             "poster": "posters/x-1.jpg"},
            {"id": "s-1", "kind": "Skill", "prompt": "", "skill": {"desc": "D", "install": "npx skills add a/b", "repo": "https://github.com/a/b"},
             "seconds": 5, "poster": "posters/s-1.jpg"},
        ]
        a, s = server.normalise(self.root, rows, "https://cloud.test/b")
        self.assertEqual((a["slug"], a["title"], a["duration"], a["note"]), ("x-1", "T", 27.6, "Attach the brand image."))
        self.assertEqual(len(a["prompt"]), len(long_prompt.strip()), "the prompt is not cut at 4000")
        self.assertEqual(a["poster"], "https://cloud.test/b/posters/x-1.jpg")
        self.assertIsNone(a["skill"])
        self.assertEqual(s["skill"], {"desc": "D", "install": "npx skills add a/b", "repo": "https://github.com/a/b"})
        self.assertEqual(s["preview"], "")   # no preview file named: a calm poster-only card

    def test_slug_is_made_safe(self):
        self.assertEqual(server.normalise(self.root, [{"slug": "a b/../c", "poster": "posters/a.jpg"}])[0]["slug"], "a-b-..-c")


class Base(unittest.TestCase):
    """A web base for the files that are not in the folder (the shared cloud folder of a team)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        make_gallery(self.root, [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_paths_go_to_the_base_unless_the_file_is_in_the_folder(self):
        rows = [{"slug": "a", "poster": "posters/a.jpg", "preview": "previews/a b.mp4"},
                {"slug": "far", "poster": "posters/far.jpg", "preview": "/previews/far.mp4", "video": "videos/far.mp4"}]
        i, f = server.normalise(self.root, rows, "https://cloud.test/dav/x")
        self.assertEqual((i["poster"], i["preview"]), ("/f/posters/a.jpg", "https://cloud.test/dav/x/previews/a%20b.mp4"))
        self.assertEqual((f["poster"], f["preview"]), ("https://cloud.test/dav/x/posters/far.jpg", "https://cloud.test/dav/x/previews/far.mp4"))
        self.assertEqual([x["slug"] for x in server.normalise(self.root, rows)], ["a"])   # no base: a missing file is no picture

    def test_the_preview_falls_back_to_the_video_and_the_base_cannot_be_escaped(self):
        rows = [{"slug": "v", "video": "videos/v.mp4", "poster": "../x.jpg"}]
        (v,) = server.normalise(None, rows, "https://cloud.test/b")
        self.assertEqual((v["preview"], v["poster"]), ("https://cloud.test/b/videos/v.mp4", ""))

    def test_sources_and_links(self):
        rows = [{"slug": "a", "poster": "posters/a.jpg", "sources": ["skillry", "remotion"],
                 "pages": {"skillry": "https://s.test/p/1", "bad": "javascript:x"}, "post": "https://s.test/p/1"},
                {"slug": "b", "poster": "posters/a.jpg", "source": "claude-motion, prompt-motion", "page": "https://c.test/b"},
                {"slug": "c", "poster": "posters/a.jpg", "pages": {"remotion": "https://r.test/c"}}]
        a, b, c = server.normalise(self.root, rows)
        self.assertEqual(a["sources"], ["skillry", "remotion"])
        self.assertEqual(a["links"], [{"source": "skillry", "url": "https://s.test/p/1"}])   # post is the same address: once
        self.assertEqual(b["sources"], ["claude-motion", "prompt-motion"])
        self.assertEqual(b["links"], [{"source": "", "url": "https://c.test/b"}])
        self.assertEqual(c["sources"], ["remotion"])                                         # taken from the pages when not named

    def test_media_base_setting_only_http_and_no_trailing_slash(self):
        keep = os.environ.get("MOTION_GALLERY_BASE")
        try:
            os.environ["MOTION_GALLERY_BASE"] = "https://cloud.test/dav/x/"
            self.assertEqual(server.media_base(), "https://cloud.test/dav/x")
            os.environ["MOTION_GALLERY_BASE"] = "file:///etc"
            self.assertEqual(server.media_base(), "")
        finally:
            os.environ.pop("MOTION_GALLERY_BASE", None)
            if keep is not None:
                os.environ["MOTION_GALLERY_BASE"] = keep

    def test_a_base_without_a_folder_reads_gallery_json_from_the_base(self):
        keep = {k: os.environ.pop(k, None) for k in ("MOTION_GALLERY_DIR", "MOTION_GALLERY_BASE", "HUB_CONFIG")}
        seen = []
        orig = server.fetch_url
        server.fetch_url = lambda url, limit: (seen.append(url), (json.dumps({"items": [{"slug": "w", "poster": "posters/w.jpg"}]}).encode(), "application/json"))[1]
        server._cache.update(sig=None, data=None)
        server._web.update(url=None, time=0, raw=None)
        os.environ["MOTION_GALLERY_BASE"] = "https://cloud.test/dav/x"
        try:
            d = server.load()
            self.assertEqual((d["configured"], d["ready"], [i["poster"] for i in d["items"]]), (True, True, ["https://cloud.test/dav/x/posters/w.jpg"]))
            server.load()
            self.assertEqual(seen, ["https://cloud.test/dav/x/gallery.json"])   # kept for a while
            server.fetch_url = lambda url, limit: None
            server._web["time"] = 0
            self.assertTrue(server.load()["ready"], "the last good copy is shown when the cloud does not answer")
        finally:
            server.fetch_url = orig
            os.environ.pop("MOTION_GALLERY_BASE", None)
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v
            server._cache.update(sig=None, data=None)
            server._web.update(url=None, time=0, raw=None, failed=0)

    def test_a_dead_base_is_not_asked_again_at_once(self):
        calls = []
        orig = server.fetch_url
        server.fetch_url = lambda url, limit: calls.append(url)   # None: the cloud does not answer
        server._web.update(url=None, time=0, raw=None, failed=0)
        try:
            self.assertIsNone(server.web_gallery("https://dead.test/x"))
            self.assertIsNone(server.web_gallery("https://dead.test/x"))
            self.assertEqual(len(calls), 1, "the second request must not wait for the dead link again")
            server._web["failed"] = time.time() - server.FAIL_TTL - 1
            server.web_gallery("https://dead.test/x")
            self.assertEqual(len(calls), 2)
        finally:
            server.fetch_url = orig
            server._web.update(url=None, time=0, raw=None, failed=0)

    def test_a_picture_without_an_image_mime_is_recognised_by_its_bytes(self):
        self.assertEqual(server.sniff_image(b"\xff\xd8\xff\xe0abc"), "image/jpeg")
        self.assertEqual(server.sniff_image(b"\x89PNG\r\n\x1a\nrest"), "image/png")
        self.assertEqual(server.sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(server.sniff_image(b"<html>nope</html>"), "")
        orig = server.fetch_url
        server.fetch_url = lambda url, limit: (b"\xff\xd8\xff\xe0jpegdata", "application/octet-stream")
        server._remote.clear()
        try:
            self.assertEqual(server.fetch_remote("https://c.test/p.jpg")[1], "image/jpeg")
            server._remote.clear()
            server.fetch_url = lambda url, limit: (b"<html>login</html>", "text/html")
            self.assertIsNone(server.fetch_remote("https://c.test/p2.jpg"))
        finally:
            server.fetch_url = orig
            server._remote.clear()


@unittest.skipUnless(shutil.which("curl"), "needs curl")
class CurlFallback(unittest.TestCase):
    """Python may distrust a certificate that curl trusts (an old Windows store) and the hub proxy may drop it: curl is the last way."""
    def setUp(self):
        from http.server import BaseHTTPRequestHandler

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = b"x" * 100 if self.path.split("?")[0] == "/ok" else b""
                self.send_response(200 if body else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self._env = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
        self._opener = server.urllib.request.build_opener

        class Dead:
            def open(self, *a, **k):
                raise OSError("python cannot reach it")
        server.urllib.request.build_opener = lambda *a: Dead()

    def tearDown(self):
        server.urllib.request.build_opener = self._opener
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self.srv.shutdown()
        self.srv.server_close()

    def test_curl_answers_when_python_cannot(self):
        self.assertEqual(server.fetch_url(self.url + "/ok", 1000), (b"x" * 100, ""))

    def test_a_missing_file_and_a_too_big_one_are_none(self):
        self.assertIsNone(server.fetch_url(self.url + "/missing", 1000))
        self.assertIsNone(server.fetch_url(self.url + "/ok", 50))

    def logged(self, fn):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            out = fn()
        return out, buf.getvalue()

    def test_the_reason_goes_to_the_log_without_the_path(self):
        out, text = self.logged(lambda: server.fetch_url(self.url + "/ok?token=SECRET", 1000))
        self.assertEqual(out, (b"x" * 100, ""))
        self.assertIn("python could not read 127.0.0.1:", text)
        self.assertIn("OSError: python cannot reach it", text)
        self.assertNotIn("SECRET", text)
        out, text = self.logged(lambda: server.fetch_with_curl(self.url + "/missing?token=SECRET", 1000))
        self.assertIsNone(out)
        self.assertIn("curl failed", text)
        self.assertIn("404", text)
        self.assertNotIn("SECRET", text)


class DirectFirst(unittest.TestCase):
    """The hub proxy drops connections to the gallery host: the first try is direct, never through the proxy."""
    def test_direct_first_then_curl(self):
        calls = []
        orig_open, orig_curl, orig_build = server.urllib.request.OpenerDirector.open, server.fetch_with_curl, server.urllib.request.build_opener

        def build(*handlers):
            calls.append([type(h).__name__ for h in handlers])
            return orig_build(*handlers)

        def boom(self, *a, **k):
            raise OSError("certificate has expired")
        server.urllib.request.build_opener = build
        server.urllib.request.OpenerDirector.open = boom
        server.fetch_with_curl = lambda url, limit: calls.append("curl") or (b"ok", "")
        try:
            import contextlib, io
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(server.fetch_url("https://example.invalid/gallery.json", 100), (b"ok", ""))
        finally:
            server.urllib.request.build_opener = orig_build
            server.urllib.request.OpenerDirector.open = orig_open
            server.fetch_with_curl = orig_curl
        self.assertEqual(calls, [["ProxyHandler"], "curl"])
        self.assertIn("certificate has expired", err.getvalue())
        self.assertIn("trying curl", err.getvalue())

    def test_an_answer_of_the_server_does_not_call_curl(self):
        import contextlib, io, urllib.error
        orig_open, orig_curl = server.urllib.request.OpenerDirector.open, server.fetch_with_curl

        def gone(self, *a, **k):
            raise urllib.error.HTTPError("https://x/y", 404, "Not Found", {}, None)
        server.urllib.request.OpenerDirector.open = gone
        server.fetch_with_curl = lambda *a: self.fail("curl must not be called after an HTTP answer")
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(server.fetch_url("https://x/y", 100))
        finally:
            server.urllib.request.OpenerDirector.open = orig_open
            server.fetch_with_curl = orig_curl
        self.assertIn("HTTP 404", err.getvalue())


class Config(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("MOTION_GALLERY_DIR", "MOTION_GALLERY_BASE", "HUB_CONFIG")}
        os.environ.pop("MOTION_GALLERY_DIR", None)
        os.environ.pop("MOTION_GALLERY_BASE", None)
        self.tmp = tempfile.TemporaryDirectory()
        server._cache.update(sig=None, data=None)

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self.tmp.cleanup()

    def conf(self, extensions):
        path = os.path.join(self.tmp.name, "hub.json")
        Path(path).write_text(json.dumps({"extensions": extensions}), encoding="utf-8")
        os.environ["HUB_CONFIG"] = path

    def test_not_set_is_empty_with_the_flag_down(self):
        self.conf({"motion-gallery": {}})
        self.assertEqual(server.load(), {"configured": False, "ready": False, "items": []})

    def test_set_by_account_key_and_read(self):
        gal = os.path.join(self.tmp.name, "g")
        os.mkdir(gal)
        make_gallery(gal, [{"slug": "a"}])
        self.conf({"someone:motion-gallery": {"gallery_dir": gal}})
        d = server.load()
        self.assertTrue(d["configured"] and d["ready"])
        self.assertEqual([i["slug"] for i in d["items"]], ["a"])

    def test_folder_without_json_and_broken_json(self):
        gal = os.path.join(self.tmp.name, "g")
        os.mkdir(gal)
        self.conf({"motion-gallery": {"gallery_dir": gal}})
        self.assertEqual(server.load(), {"configured": True, "ready": False, "items": []})
        Path(gal, "gallery.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(server.load(), {"configured": True, "ready": False, "items": []})

    def test_file_is_reread_when_it_changes(self):
        gal = os.path.join(self.tmp.name, "g")
        os.mkdir(gal)
        make_gallery(gal, [{"slug": "a"}])
        self.conf({"motion-gallery": {"gallery_dir": gal}})
        self.assertEqual(len(server.load()["items"]), 1)
        make_gallery(gal, [{"slug": "a", "prompt": "one more edit that changes the size"}])
        self.assertEqual(server.load()["items"][0]["prompt"], "one more edit that changes the size")

    def test_bom_is_fine(self):
        gal = os.path.join(self.tmp.name, "g")
        os.mkdir(gal)
        make_gallery(gal, [])
        Path(gal, "gallery.json").write_bytes(b"\xef\xbb\xbf" + json.dumps([{"slug": "a"}]).encode())
        self.conf({"motion-gallery": {"gallery_dir": gal}})
        self.assertEqual(len(server.load()["items"]), 1)


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_gallery(cls.tmp.name, [{"slug": "a", "prompt": "p"}, {"slug": "remote", "poster": "https://cdn.test/r.jpg"}])
        cls._dir = os.environ.get("MOTION_GALLERY_DIR")
        os.environ["MOTION_GALLERY_DIR"] = cls.tmp.name
        server._cache.update(sig=None, data=None)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_address[1]
        server.PORT = cls.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        if cls._dir is None:
            os.environ.pop("MOTION_GALLERY_DIR", None)
        else:
            os.environ["MOTION_GALLERY_DIR"] = cls._dir
        cls.tmp.cleanup()

    def get(self, path, headers=None, host=None, method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"localhost:{self.port}", **(headers or {})}
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        out = (r.status, dict(r.getheaders()), body)
        c.close()
        return out

    def test_gallery_json_only_for_the_page_origin(self):
        st, h, body = self.get("/gallery.json", {"Origin": PAGE})
        self.assertEqual(st, 200)
        self.assertEqual(h["Access-Control-Allow-Origin"], PAGE)
        data = json.loads(body)
        self.assertEqual([i["slug"] for i in data["items"]], ["a", "remote"])
        self.assertEqual(self.get("/gallery.json")[0], 403)
        self.assertEqual(self.get("/gallery.json", {"Origin": "http://evil.test"})[0], 403)
        self.assertEqual(self.get("/gallery.json", {"Origin": "http://localhost:9999"})[0], 403)

    def test_wrong_host_is_refused(self):
        self.assertEqual(self.get("/ping", {"Origin": PAGE}, host="evil.test")[0], 403)
        self.assertEqual(self.get("/ping", {"Origin": PAGE}, host=f"localhost:{self.port + 1}")[0], 403)
        self.assertEqual(self.get("/ping", {"Origin": PAGE}, host=f"127.0.0.1:{self.port}")[0], 200)

    def test_preflight(self):
        st, h, _ = self.get("/gallery.json", {"Origin": PAGE}, method="OPTIONS")
        self.assertEqual((st, h["Access-Control-Allow-Origin"]), (204, PAGE))
        self.assertEqual(self.get("/gallery.json", {"Origin": "http://evil.test"}, method="OPTIONS")[0], 403)

    def test_file_full_and_ranges(self):
        st, h, body = self.get("/f/previews/a.mp4")
        self.assertEqual((st, h["Content-Type"], body), (200, "video/mp4", MP4))
        self.assertEqual(h["Accept-Ranges"], "bytes")
        st, h, body = self.get("/f/previews/a.mp4", {"Range": "bytes=10-19"})
        self.assertEqual((st, body, h["Content-Range"]), (206, MP4[10:20], "bytes 10-19/2048"))
        st, h, body = self.get("/f/previews/a.mp4", {"Range": "bytes=2000-"})
        self.assertEqual((st, body), (206, MP4[2000:]))
        st, h, body = self.get("/f/previews/a.mp4", {"Range": "bytes=-8"})
        self.assertEqual((st, body), (206, MP4[-8:]))
        st, h, _ = self.get("/f/previews/a.mp4", {"Range": "bytes=5000-"})
        self.assertEqual((st, h["Content-Range"]), (416, "bytes */2048"))
        st, h, body = self.get("/f/previews/a.mp4", method="HEAD")
        self.assertEqual((st, h["Content-Length"], body), (200, "2048", b""))

    def test_nothing_outside_the_folder_or_of_another_type(self):
        Path(self.tmp.name, "gallery.json").exists()
        Path(self.tmp.name, "note.txt").write_text("x")
        for bad in ("/f/../x", "/f/..%2Fx", "/f/%2e%2e/%2e%2e/windows/win.ini", "/f/gallery.json", "/f/note.txt", "/f/nope.mp4", "/f/previews", "/f/"):
            self.assertEqual(self.get(bad)[0], 404, bad)

    def test_poster_by_slug(self):
        st, h, body = self.get("/poster/a")
        self.assertEqual((st, h["Content-Type"], body), (200, "image/jpeg", JPEG))
        self.assertEqual(self.get("/poster/nope")[0], 404)

    def test_remote_poster_is_fetched_by_the_process(self):
        orig = server.fetch_remote
        server.fetch_remote = lambda url: (JPEG, "image/jpeg") if url == "https://cdn.test/r.jpg" else None
        try:
            self.assertEqual(self.get("/poster/remote", {"Origin": PAGE})[2], JPEG)
            server.fetch_remote = lambda url: None
            self.assertEqual(self.get("/poster/remote")[0], 502)
        finally:
            server.fetch_remote = orig

    def test_unknown_path(self):
        self.assertEqual(self.get("/etc/passwd")[0], 404)


if __name__ == "__main__":
    unittest.main()
