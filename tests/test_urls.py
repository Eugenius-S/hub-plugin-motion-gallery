"""Only http and https are read: file:, data:, ftp: and local paths are refused, in the downloader and in the poster proxy."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HUB_WEB_PORT", "18787")
os.environ["HUB_STATE_DIR"] = tempfile.mkdtemp(prefix="mg-state-")   # never the live hub
os.environ["HUB_CONFIG"] = os.path.join(os.environ["HUB_STATE_DIR"], "no-hub.json")
import fetcher  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
import sources  # noqa: E402

SECRET = b"-----BEGIN PRIVATE KEY----- not a real key"


class Lure(BaseHTTPRequestHandler):
    """A local site: /ok is a file, /to-file and /to-ftp redirect somewhere that is not http."""
    target = ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        elif self.path == "/to-file":
            self.send_response(302)
            self.send_header("Location", "file://" + Lure.target)
            self.end_headers()
        elif self.path == "/to-ftp":
            self.send_response(302)
            self.send_header("Location", "ftp://127.0.0.1/x")
            self.end_headers()
        else:
            self.send_error(404)

    do_HEAD = do_GET


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Lure)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.site = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bait = os.path.join(self.tmp.name, "id_rsa")   # stands for ~/.ssh/id_rsa
        Path(self.bait).write_bytes(SECRET)
        Lure.target = self.bait
        self.out = os.path.join(self.tmp.name, "out", "v.mp4")

    def tearDown(self):
        self.tmp.cleanup()

    def bad(self):
        return ["file://" + self.bait, "FILE://" + self.bait, "file:///" + self.bait.lstrip("/"), self.bait, "~/.ssh/id_rsa", "data:text/plain,hi",
                "ftp://127.0.0.1/x", "gopher://127.0.0.1/x", "javascript:alert(1)", "//127.0.0.1/x", "", "http:///x"]


class Loader(Base):
    def test_a_local_file_is_not_a_page(self):
        for url in self.bad():
            with self.assertRaises(net.NetError, msg=url):
                net.get_text(url)

    def test_a_local_file_is_not_downloaded(self):
        for url in self.bad():
            with self.assertRaises(net.NetError, msg=url):
                net.save(url, self.out, 10_000)
            self.assertFalse(os.path.exists(self.out), url)
        self.assertEqual(net.head_size("file://" + self.bait), 0)

    def test_a_redirect_to_something_that_is_not_http_is_refused(self):
        for path in ("/to-file", "/to-ftp"):
            with self.assertRaises(net.NetError, msg=path):
                net.get_text(self.site + path)
            with self.assertRaises(net.NetError, msg=path):
                net.save(self.site + path, self.out, 10_000)
            self.assertFalse(os.path.exists(self.out), path)

    def test_a_plain_http_file_still_comes(self):
        self.assertEqual(net.save(self.site + "/ok", self.out, 10_000), 72)
        self.assertIn("PNG", net.get_text(self.site + "/ok"))

    def test_curl_is_told_to_speak_http_only(self):
        seen = []
        orig = subprocess.run
        subprocess.run = lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, b"", b""))[1]
        try:
            net._curl(["http://x.test/"], 5)
        finally:
            subprocess.run = orig
        cmd = seen[0]
        self.assertEqual(cmd[cmd.index("--proto") + 1], "=http,https")
        self.assertEqual(cmd[cmd.index("--proto-redir") + 1], "=http,https")


class Proxy(Base):
    def test_the_poster_proxy_does_not_read_local_files(self):
        for url in self.bad():
            self.assertIsNone(server.fetch_url(url, 10_000), url)
        self.assertIsNone(server.fetch_url(self.site + "/to-file", 10_000))
        self.assertIsNone(server.fetch_with_curl("file://" + self.bait, 10_000))

    def test_a_plain_http_poster_still_comes(self):
        data, mime = server.fetch_url(self.site + "/ok", 10_000)
        self.assertEqual((data[:4], mime), (b"\x89PNG", "image/png"))

    def test_a_remote_poster_that_is_not_http_is_not_fetched_at_all(self):
        self.assertIsNone(server.fetch_remote("file://" + self.bait))


class Downloader(Base):
    def test_a_page_that_points_the_video_at_a_local_file_saves_nothing(self):
        got = {"saved": [], "heads": []}
        entry = {"slug": "x", "title": "T", "author": "", "tags": [], "prompt": "p", "seconds": 1,
                 "video_url": "file://" + self.bait, "poster_url": "file://" + self.bait}

        class Site:
            name = "s"

            def read(self, url, page):
                return dict(entry)

        f = fetcher.Fetcher(self.tmp.name, get=lambda u: "page", head=lambda u: got["heads"].append(u) or 5,
                            save=lambda u, p, lim: (got["saved"].append(u), os.makedirs(os.path.dirname(p), exist_ok=True), Path(p).write_bytes(b"x"))[0] or 5,
                            sleep=lambda s: None)
        with self.assertRaises(net.NetError):
            f._one(Site(), "https://a.test", "https://a.test/p", False)
        self.assertEqual(got["saved"], [])
        entry["video_url"] = self.site + "/ok"
        f._one(Site(), "https://a.test", "https://a.test/p", False)
        self.assertEqual(got["saved"], [self.site + "/ok"])   # the poster that is not http is dropped, the video stays

    def test_the_size_probe_does_not_touch_a_local_file(self):
        got = []

        class Site:
            name = "s"

            def list(self, url, get):
                return ["https://a.test/p1"]

            def slug(self, u):
                return "p1"

            def read(self, url, page):
                return {"video_url": "file://" + self_bait}

        self_bait = self.bait
        f = fetcher.Fetcher(self.tmp.name, get=lambda u: "page", head=lambda u: got.append(u) or 5, sleep=lambda s: None)
        f.listing = lambda url: (Site(), ["https://a.test/p1"])
        f.plan(["https://a.test"])
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
