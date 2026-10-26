"""Only http and https are read: file:, data:, ftp: and local paths are refused, in the downloader and in the poster proxy."""
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

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
        patcher = mock.patch.object(net, "ALLOW_PRIVATE", True)   # the test site is on 127.0.0.1
        patcher.start()
        self.addCleanup(patcher.stop)
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
        subprocess.run = lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, b"200 ", b""))[1]
        try:
            net._curl("http://127.0.0.1/", [], 5, os.path.join(self.tmp.name, "o"))
        finally:
            subprocess.run = orig
        cmd = seen[0]
        self.assertEqual(cmd[cmd.index("--proto") + 1], "=http,https")
        self.assertNotIn("-L", cmd)   # redirects are followed here, hop by hop, never by curl


class Private(unittest.TestCase):
    """The downloader never reads this machine or a private network (ALLOW_PRIVATE is off here, as in the real process)."""
    ADDRESSES = ["127.0.0.1", "127.8.9.10", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                 "0.0.0.0", "[::1]", "[fc00::1]", "[fd12:3456::1]", "[fe80::1]", "[::ffff:127.0.0.1]", "[::ffff:10.0.0.1]", "localhost", "LOCALHOST.",
                 "app.localhost"]

    def setUp(self):
        self.assertFalse(net.ALLOW_PRIVATE)

    def test_every_private_form_is_an_address_of_this_machine_or_network(self):
        for a in ("127.0.0.1", "10.0.0.1", "172.20.1.1", "192.168.0.9", "169.254.1.1", "::1", "fc00::1", "fe80::1", "::ffff:192.168.1.1"):
            self.assertTrue(net.is_private(a), a)
        for a in ("8.8.8.8", "93.184.216.34", "172.32.0.1", "2606:4700::1111", "example.com"):
            self.assertFalse(net.is_private(a), a)

    def test_a_link_to_a_private_address_is_refused_everywhere(self):
        for a in self.ADDRESSES:
            url = f"http://{a}:9/x"
            with self.assertRaises(net.NetError, msg=url):
                net.get_text(url)
            with self.assertRaises(net.NetError, msg=url):
                net.save(url, os.path.join(tempfile.gettempdir(), "mg-never.bin"), 1000)
            self.assertEqual(net.head_size(url), 0, url)

    def test_a_name_that_resolves_to_a_private_address_is_refused(self):
        def lie(name, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
        with mock.patch.object(socket, "getaddrinfo", lie):
            with self.assertRaises(net.NetError):
                net.vet("looks-public.example", 80)
            with self.assertRaises(net.NetError):
                net.get_text("http://looks-public.example/")

    def test_one_private_answer_among_public_ones_is_enough_to_refuse(self):
        def mixed(name, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        with mock.patch.object(socket, "getaddrinfo", mixed):
            with self.assertRaises(net.NetError):
                net.vet("two-faced.example", 80)

    def test_a_public_address_is_let_through_and_connected_to_exactly_that_address(self):
        def good(name, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        with mock.patch.object(socket, "getaddrinfo", good):
            self.assertEqual(net.vet("example.com", 80)[0][4], ("93.184.216.34", 80))

    def test_a_name_that_does_not_resolve_is_a_clear_refusal(self):
        def none(name, port, **kw):
            raise socket.gaierror("no")
        with mock.patch.object(socket, "getaddrinfo", none):
            with self.assertRaises(net.NetError) as c:
                net.vet("nowhere.example", 80)
            self.assertIn("resolve", c.exception.what)

    def test_a_redirect_to_a_private_address_is_not_followed(self):
        """Hop 1 is let through (the test narrows the list to 10/8, so the local test site counts as public); it answers with a
        redirect to 10.0.0.7: that second address is vetted like the first and refused, no connection is made to it."""
        class Jump(Lure):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://10.0.0.7:9/secret")
                self.end_headers()
        jumper = ThreadingHTTPServer(("127.0.0.1", 0), Jump)
        threading.Thread(target=jumper.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{jumper.server_address[1]}/"
            with mock.patch.object(net, "PRIVATE", [ipaddress.ip_network("10.0.0.0/8")]):
                for call in (lambda: net.get_text(url), lambda: net.save(url, os.path.join(tempfile.gettempdir(), "mg-never.bin"), 1000)):
                    with self.assertRaises(net.NetError) as c:
                        call()
                    self.assertIn("private", c.exception.what)
        finally:
            jumper.shutdown()
            jumper.server_close()

    def test_curl_hops_are_vetted_and_a_redirect_to_a_private_address_is_refused(self):
        runs = []

        def fake(cmd, **kw):
            runs.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"302 http://10.0.0.7/secret", b"")

        def public(name, port, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        out = os.path.join(tempfile.gettempdir(), "mg-curl-out")
        with mock.patch.object(socket, "getaddrinfo", public), mock.patch.object(subprocess, "run", fake):
            with self.assertRaises(net.NetError):
                net._curl("http://example.com/start", [], 5, out)
        self.assertEqual(len(runs), 1)   # the second hop never reached curl
        cmd = runs[0]
        self.assertEqual(cmd[cmd.index("--resolve") + 1], "example.com:80:93.184.216.34")   # curl is held to the vetted address
        self.assertNotIn("-L", cmd)

    def test_curl_of_a_private_address_never_starts(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("curl started")):
            with self.assertRaises(net.NetError):
                net._curl("http://192.168.1.1/", [], 5, os.path.join(tempfile.gettempdir(), "mg-curl-out"))


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
