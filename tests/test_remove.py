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
import remove  # noqa: E402
import server  # noqa: E402

PAGE = "http://localhost:18787"
KEYS = ("MOTION_GALLERY_DIR", "MOTION_GALLERY_BASE", "MOTION_GALLERY_DELETE", "MOTION_GALLERY_DAV_LOGIN", "MOTION_GALLERY_DAV_FOLDER")


def rows():
    return [
        {"slug": "a", "video": "videos/a.mp4", "preview": "previews/a.mp4", "poster": "posters/a.jpg", "prompt": "pa"},
        {"slug": "b", "video": "videos/b.mp4", "preview": "previews/b.mp4", "poster": "posters/b.jpg"},
        {"slug": "c", "preview": "previews/a.mp4", "poster": "https://cdn.test/c.jpg"},
    ]


class TakeOut(unittest.TestCase):
    def test_the_entry_leaves_and_the_rest_stays(self):
        new, files = remove.take_out(rows(), "b", server.slug_of)
        self.assertEqual([r["slug"] for r in new], ["a", "c"])
        self.assertEqual(sorted(files), ["posters/b.jpg", "previews/b.mp4", "videos/b.mp4"])

    def test_a_wrapped_list_keeps_its_other_keys(self):
        new, _ = remove.take_out({"title": "T", "items": rows()}, "a", server.slug_of)
        self.assertEqual(new["title"], "T")
        self.assertEqual([r["slug"] for r in new["items"]], ["b", "c"])

    def test_a_file_that_another_entry_uses_stays(self):
        _, files = remove.take_out(rows(), "a", server.slug_of)
        self.assertNotIn("previews/a.mp4", files)   # c shows the same preview
        self.assertEqual(sorted(files), ["posters/a.jpg", "videos/a.mp4"])

    def test_links_are_not_ours_and_empty_values_fall_back_to_the_layout(self):
        _, files = remove.take_out([{"slug": "x", "poster": "https://cdn.test/x.jpg", "preview": "../../etc/passwd"}], "x", server.slug_of)
        self.assertFalse(any(f.startswith("http") or ".." in f for f in files))
        self.assertNotIn("posters/x.jpg", files)   # the link is where the poster lives: not guessed
        self.assertIn("posters/x.jpg", remove.paths_of({"slug": "x"}, "x"))

    def test_unknown_slug_and_bad_shapes(self):
        self.assertIsNone(remove.take_out(rows(), "zzz", server.slug_of))
        self.assertIsNone(remove.take_out({"items": 5}, "a", server.slug_of))
        self.assertIsNone(remove.take_out("x", "a", server.slug_of))


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in KEYS}
        server._cache.update(sig=None, data=None)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        server._cache.update(sig=None, data=None)


class Folder(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        for sub in ("videos", "previews", "posters"):
            (d / sub).mkdir()
        for rel in ("videos/a.mp4", "previews/a.mp4", "posters/a.jpg", "videos/b.mp4", "previews/b.mp4", "posters/b.jpg"):
            (d / rel).write_bytes(b"x")
        (d / "gallery.json").write_text(json.dumps(rows()), encoding="utf-8")
        os.environ["MOTION_GALLERY_DIR"] = self.tmp.name
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.srv.daemon_threads = True
        server.PORT = self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()
        super().tearDown()

    def call(self, method, path, body=None, origin=PAGE):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"localhost:{self.port}"}
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, r.read())
        c.close()
        return out

    def on_disk(self):
        return [r["slug"] for r in json.loads((Path(self.tmp.name) / "gallery.json").read_text(encoding="utf-8"))]

    def test_delete_takes_the_entry_and_its_own_files(self):
        self.assertTrue(json.loads(self.call("GET", "/gallery.json")[1])["can_delete"])
        st, body = self.call("POST", "/delete", {"slug": "b"})
        self.assertEqual(st, 200, body)
        self.assertEqual(self.on_disk(), ["a", "c"])
        d = Path(self.tmp.name)
        self.assertFalse((d / "videos/b.mp4").exists() or (d / "previews/b.mp4").exists() or (d / "posters/b.jpg").exists())
        self.assertTrue((d / "videos/a.mp4").exists())
        self.assertEqual([i["slug"] for i in json.loads(self.call("GET", "/gallery.json")[1])["items"]], ["a", "c"])

    def test_a_file_shared_with_another_entry_stays(self):
        self.assertEqual(self.call("POST", "/delete", {"slug": "a"})[0], 200)
        d = Path(self.tmp.name)
        self.assertTrue((d / "previews/a.mp4").exists())   # c still shows it
        self.assertFalse((d / "videos/a.mp4").exists())

    def test_unknown_slug_is_404_and_nothing_changes(self):
        self.assertEqual(self.call("POST", "/delete", {"slug": "nope"})[0], 404)
        self.assertEqual(self.on_disk(), ["a", "b", "c"])

    def test_only_the_hub_page_may_ask(self):
        self.assertEqual(self.call("POST", "/delete", {"slug": "b"}, origin=None)[0], 403)
        self.assertEqual(self.call("POST", "/delete", {"slug": "b"}, origin="http://evil.test")[0], 403)
        self.assertEqual(self.on_disk(), ["a", "b", "c"])

    def test_bad_bodies(self):
        for body in (b"", b"not json", b'{"slug": 5}', b'{"slug": ""}', b"[]", b'{"slug": "' + b"x" * 5000 + b'"}'):
            self.assertEqual(self.call("POST", "/delete", body)[0], 400, body[:20])
        self.assertEqual(self.call("POST", "/other", {"slug": "a"})[0], 404)
        self.assertEqual(self.on_disk(), ["a", "b", "c"])

    def test_the_switch_turns_deleting_off(self):
        os.environ["MOTION_GALLERY_DELETE"] = "off"
        self.assertFalse(json.loads(self.call("GET", "/gallery.json")[1])["can_delete"])
        self.assertEqual(self.call("POST", "/delete", {"slug": "b"})[0], 403)
        self.assertEqual(self.on_disk(), ["a", "b", "c"])

    def test_a_read_only_gallery_json_is_not_offered(self):
        orig = os.access
        os.access = lambda p, m, *a, **k: False if str(p).endswith("gallery.json") and m == os.W_OK else orig(p, m, *a, **k)
        try:
            self.assertFalse(json.loads(self.call("GET", "/gallery.json")[1])["can_delete"])
        finally:
            os.access = orig

    def test_preflight_allows_post(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("OPTIONS", "/delete", headers={"Host": f"localhost:{self.port}", "Origin": PAGE})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 204)
        self.assertIn("POST", r.getheader("Access-Control-Allow-Methods"))
        self.assertIn("Content-Type", r.getheader("Access-Control-Allow-Headers"))
        c.close()


class FakeDav:
    """A storage in memory: files by relative path, a version of gallery.json; `race` changes it once between get and put."""

    def __init__(self, files, race=False):
        self.files, self.race, self.version, self.calls = dict(files), race, 1, []

    def get(self, rel):
        self.calls.append(("get", rel))
        return self.files[rel], f'"v{self.version}"'

    def put(self, rel, data, etag=""):
        self.calls.append(("put", rel))
        if self.race:
            self.race, self.version = False, self.version + 1
            self.files[rel] = json.dumps([*json.loads(self.files[rel]), {"slug": "late", "poster": "posters/late.jpg"}]).encode()
        if etag != f'"v{self.version}"':
            raise dav.DavError(412, "changed meanwhile")
        self.version += 1
        self.files[rel] = data

    def delete(self, rel):
        self.calls.append(("delete", rel))
        self.files.pop(rel, None)


class Storage(Base):
    def setUp(self):
        super().setUp()
        os.environ["MOTION_GALLERY_BASE"] = "https://media.test/share"
        self.files = {"gallery.json": json.dumps(rows()).encode(), "videos/b.mp4": b"x", "previews/b.mp4": b"x", "posters/b.jpg": b"x"}
        self.orig = server.make_dav

    def tearDown(self):
        server.make_dav = self.orig
        super().tearDown()

    def use(self, fake):
        server.make_dav = lambda: fake

    def slugs(self, fake):
        return [r["slug"] for r in json.loads(fake.files["gallery.json"])]

    def test_entry_and_files_go_from_the_storage(self):
        fake = FakeDav(self.files)
        self.use(fake)
        self.assertTrue(server.can_delete())
        out = server.remove_entry("b")
        self.assertEqual((out["ok"], out["files"], out["left"]), (True, 3, 0))
        self.assertEqual(self.slugs(fake), ["a", "c"])
        self.assertEqual(sorted(fake.files), ["gallery.json"])

    def test_the_file_changed_meanwhile_is_read_again_and_the_new_entry_survives(self):
        fake = FakeDav(self.files, race=True)
        self.use(fake)
        server.remove_entry("b")
        self.assertEqual(self.slugs(fake), ["a", "c", "late"])
        self.assertEqual([c[0] for c in fake.calls].count("put"), 2)

    def test_it_gives_up_after_three_changes(self):
        fake = FakeDav(self.files)

        def always_changed(rel, data, etag=""):
            raise dav.DavError(412, "changed meanwhile")

        fake.put = always_changed
        self.use(fake)
        with self.assertRaises(server.Refused) as e:
            server.remove_entry("b")
        self.assertEqual(e.exception.code, 409)
        self.assertIn("videos/b.mp4", fake.files)   # nothing was deleted before the list was written

    def test_unknown_slug_deletes_nothing(self):
        fake = FakeDav(self.files)
        self.use(fake)
        with self.assertRaises(server.Refused) as e:
            server.remove_entry("nope")
        self.assertEqual(e.exception.code, 404)
        self.assertEqual(len(fake.files), 4)

    def test_without_a_login_it_is_not_offered_and_refused(self):
        os.environ["MOTION_GALLERY_DAV_LOGIN"] = str(ROOT / "no-such-login.json")
        self.assertFalse(server.can_delete())
        with self.assertRaises(server.Refused) as e:
            server.remove_entry("b")
        self.assertEqual(e.exception.code, 403)

    def test_a_folder_that_is_set_wins_over_the_base(self):
        os.environ["MOTION_GALLERY_DIR"] = str(ROOT / "no-such-folder")   # set, but not a folder: nothing to delete from
        self.use(FakeDav(self.files))
        self.assertFalse(server.can_delete())


class Login(unittest.TestCase):
    def test_the_login_file_is_read_and_checked(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "l.json")
            self.assertIsNone(dav.read_login(p))
            Path(p).write_text(json.dumps({"server": "https://s.test/", "user": "u", "password": "p", "root": "/r/"}), encoding="utf-8")
            self.assertEqual(dav.read_login(p), {"server": "https://s.test", "user": "u", "password": "p", "root": "r"})
            Path(p).write_text(json.dumps({"server": "https://s.test", "user": "u"}), encoding="utf-8")
            self.assertIsNone(dav.read_login(p))

    def test_urls_are_quoted_and_the_password_goes_on_stdin_only(self):
        seen = []

        def runner(args, auth):
            seen.append((args, auth))
            if args[args.index("-X") + 1] == "PROPFIND":
                Path(args[args.index("-D") + 1]).write_text("HTTP/1.1 207 Multi-Status\r\n", encoding="utf-8")
                Path(args[args.index("-o") + 1]).write_bytes(b'<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat></d:response></d:multistatus>')
                return 0, ""
            Path(args[args.index("-D") + 1]).write_text('HTTP/1.1 204 No Content\r\nETag: "e"\r\n', encoding="utf-8")
            Path(args[args.index("-o") + 1]).write_bytes(b"")
            return 0, ""

        d = dav.Dav({"server": "https://s.test", "user": "me", "password": "sec ret", "root": "r"}, "Motion Gallery", runner)
        self.assertEqual(d.url("videos/a b.mp4"), "https://s.test/remote.php/dav/files/me/r/Motion%20Gallery/videos/a%20b.mp4")
        d.delete("videos/a b.mp4")
        args, auth = seen[0]
        self.assertIn("sec ret", auth)
        self.assertFalse(any("sec ret" in a for a in args))


class Webdav:
    """A storage behind the real Dav: files and collections by url path; every request is kept."""

    def __init__(self, entries):
        self.entries, self.requests = dict(entries), []

    def runner(self, args, auth):
        method = args[args.index("-X") + 1]
        url = args[-1]
        path = url.split("/remote.php/dav/files/me/", 1)[1].rstrip("/")
        self.requests.append((method, path))
        kind = self.entries.get(path)
        status, body = 204, b""
        if method == "PROPFIND":
            if kind is None:
                status = 404
            else:
                tag = "<d:collection/>" if kind == "dir" else ""
                body = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:resourcetype>%s'
                        '</d:resourcetype></d:prop></d:propstat></d:response></d:multistatus>' % tag).encode()
                status = 207
        elif method == "DELETE":
            if kind is None:
                status = 404
            else:
                for k in [k for k in self.entries if k == path or k.startswith(path + "/")]:
                    del self.entries[k]
        Path(args[args.index("-D") + 1]).write_text("HTTP/1.1 %d X\r\n" % status, encoding="utf-8")
        Path(args[args.index("-o") + 1]).write_bytes(body)
        return 0, ""

    def dav(self, runner=None):
        return dav.Dav({"server": "https://s.test", "user": "me", "password": "p", "root": ""}, "mg", runner or self.runner)

    def deletes(self):
        return [r for r in self.requests if r[0] == "DELETE"]


class SafeDelete(unittest.TestCase):
    """Only the exact file the plugin put there goes: never a folder, never the root, never an unsure target."""

    def setUp(self):
        self.w = Webdav({"mg": "dir", "mg/videos": "dir", "mg/videos/a.mp4": "file", "mg/gallery.json": "file", "mg/videos/keep.txt": "file"})

    def test_a_media_file_is_checked_as_a_file_and_then_deleted(self):
        self.w.dav().delete("videos/a.mp4")
        self.assertEqual(self.w.requests, [("PROPFIND", "mg/videos/a.mp4"), ("DELETE", "mg/videos/a.mp4")])
        self.assertNotIn("mg/videos", [k for k in self.w.entries if k.endswith("a.mp4")])
        self.assertIn("mg/videos", self.w.entries)

    def test_a_folder_is_refused_without_a_delete_request(self):
        self.w.entries["mg/videos/clips.mp4"] = "dir"   # a collection with a file-like name
        for rel in ("videos", "videos/clips.mp4", "", "/", ".", "videos/", "../x.mp4", "videos/../a.mp4", "videos//a.mp4"):
            with self.assertRaises(dav.DavError, msg=rel):
                self.w.dav().delete(rel)
        self.assertEqual(self.w.deletes(), [])
        self.assertIn("mg/videos/a.mp4", self.w.entries)

    def test_only_media_files_are_ours(self):
        for rel in ("gallery.json", "videos/keep.txt", "videos/noext"):
            with self.assertRaises(dav.DavError, msg=rel):
                self.w.dav().delete(rel)
        self.assertEqual(self.w.requests, [])

    def test_a_missing_file_is_not_an_error_and_not_deleted(self):
        self.w.dav().delete("videos/gone.mp4")
        self.assertEqual(self.w.deletes(), [])

    def test_an_answer_that_does_not_say_what_it_is_means_no_delete(self):
        orig = self.w.runner

        def runner(args, auth):
            code = orig(args, auth)
            if args[args.index("-X") + 1] == "PROPFIND":
                Path(args[args.index("-D") + 1]).write_text("HTTP/1.1 207 X\r\n", encoding="utf-8")
                Path(args[args.index("-o") + 1]).write_bytes(b"<nonsense")
            return code

        with self.assertRaises(dav.DavError):
            self.w.dav(runner).delete("videos/a.mp4")
        self.assertEqual(self.w.deletes(), [])

    def test_no_login_file_is_guessed_when_none_is_set(self):
        self.assertIsNone(dav.read_login(""))

    def test_an_entry_that_names_a_folder_does_not_take_the_folder_with_it(self):
        _, files = remove.take_out([{"slug": "x", "video": "videos", "poster": "posters/x.jpg/", "preview": "gallery.json"}], "x", server.slug_of)
        self.assertNotIn("videos", files)
        self.assertNotIn("gallery.json", files)
        for f in files:
            self.assertTrue(f.lower().endswith((".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp")), f)


if __name__ == "__main__":
    unittest.main()
