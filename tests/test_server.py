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

    def test_slug_is_made_safe(self):
        self.assertEqual(server.normalise(self.root, [{"slug": "a b/../c", "poster": "posters/a.jpg"}])[0]["slug"], "a-b-..-c")


class Config(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("MOTION_GALLERY_DIR", "HUB_CONFIG")}
        os.environ.pop("MOTION_GALLERY_DIR", None)
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
