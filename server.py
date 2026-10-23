"""Hub Motion Gallery: the plugin process serves a gallery folder (gallery.json, previews, posters) to the hub page.

The folder is set in hub.json (extensions.<account>:motion-gallery.gallery_dir, or MOTION_GALLERY_DIR for tests); nothing is
set - an empty gallery with a hint. The process listens on localhost, hub page port + 12, and answers only the hub page
(Origin) for data; videos and pictures are plain GETs (a <video> and an <img> send no Origin).
  /gallery.json   the normalised list (see load())
  /f/<path>       a file of the gallery folder, with Range for video; never outside the folder
  /poster/<slug>  the poster as bytes: a file, or a remote URL fetched here (the page can not read a foreign image)
"""
import json
import mimetypes
import os
import re
import signal
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

WEB_PORT = int(os.environ.get("HUB_WEB_PORT") or 8787)
PORT = int(os.environ.get("MOTION_GALLERY_PORT") or WEB_PORT + 12)
NAME = "motion-gallery"
FILE = "gallery.json"
MEDIA = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}
REMOTE_MAX = 12 * 1024 * 1024    # a remote poster larger than this is not taken
REMOTE_TTL = 3600
CHUNK = 256 * 1024


def state_dir():
    return os.environ.get("HUB_STATE_DIR") or os.path.expanduser("~/.hub-core")


def config():
    """hub.json of this machine; unreadable: {}."""
    try:
        from core import catalog
        path = catalog.config_path(state_dir())
    except Exception:
        path = os.environ.get("HUB_CONFIG") or ""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def gallery_dir():
    """The folder of the gallery, or None: not set / not a folder."""
    path = (os.environ.get("MOTION_GALLERY_DIR") or "").strip()
    if not path:
        for key, val in (config().get("extensions") or {}).items():
            if isinstance(val, dict) and str(key).rsplit(":", 1)[-1] == NAME and str(val.get("gallery_dir") or "").strip():
                path = str(val["gallery_dir"]).strip()
                break
    if not path:
        return None
    real = os.path.realpath(os.path.expanduser(path))
    return real if os.path.isdir(real) else None


def page_origins():
    return [f"http://localhost:{WEB_PORT}", f"http://127.0.0.1:{WEB_PORT}"]


def is_url(s):
    return bool(re.match(r"^https?://", str(s or ""), re.I))


def inside(root, rel):
    """A file under root by a relative path (slashes either way); None if it leaves root or is not a file."""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or any(p == ".." for p in rel.split("/")):
        return None
    real = os.path.realpath(os.path.join(root, *rel.split("/")))
    if os.path.commonpath([root, real]) != root or not os.path.isfile(real):
        return None
    return real


def text(v, limit=4000):
    return v.strip()[:limit] if isinstance(v, str) else ""


def tags_of(v):
    if isinstance(v, str):
        v = re.split(r"[,;]", v)
    return [x.strip() for x in v if isinstance(x, str) and x.strip()][:30] if isinstance(v, list) else []


def duration_of(v):
    try:
        n = float(v)
        return round(n, 1) if n > 0 else 0
    except (TypeError, ValueError):
        return 0


def media(root, slug, field, value, folder, exts):
    """Address of a preview or poster: a URL as is, a file of the folder as /f/<path>; no field - previews/<slug>.<ext> if it exists."""
    value = text(value, 1000)
    if is_url(value):
        return value
    if value and inside(root, value):
        return "/f/" + quote(value.replace("\\", "/").lstrip("/"), safe="/")
    if not value:
        for ext in exts:
            rel = f"{folder}/{slug}{ext}"
            if inside(root, rel):
                return "/f/" + quote(rel, safe="/")
    return ""


def normalise(root, raw):
    """gallery.json (a list or {items: [...]}) -> the entries the page draws. Entries without a slug or without any picture are dropped."""
    rows = raw.get("items") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        slug = re.sub(r"[^\w.-]", "-", text(r.get("slug"), 120)).strip("-")
        if not slug or slug in seen:
            continue
        preview = media(root, slug, "preview", r.get("preview"), "previews", (".mp4", ".webm", ".mov"))
        poster = media(root, slug, "poster", r.get("poster"), "posters", (".jpg", ".jpeg", ".png", ".webp"))
        if not preview and not poster:
            continue
        seen.add(slug)
        out.append({"slug": slug, "author": text(r.get("author"), 200), "category": text(r.get("category"), 120), "duration": duration_of(r.get("duration")),
                    "tags": tags_of(r.get("tags")), "prompt": text(r.get("prompt")), "post": text(r.get("post"), 1000) if is_url(r.get("post")) else "",
                    "page": text(r.get("page"), 1000) if is_url(r.get("page")) else "", "preview": preview, "poster": poster})
    return out


_cache = {"sig": None, "data": None}


def load():
    """{configured, ready, items}: configured - a folder is set in the settings, ready - it has a readable gallery.json."""
    root = gallery_dir()
    if not root:
        configured = bool(os.environ.get("MOTION_GALLERY_DIR") or any(
            isinstance(v, dict) and str(k).rsplit(":", 1)[-1] == NAME and str(v.get("gallery_dir") or "").strip() for k, v in (config().get("extensions") or {}).items()))
        return {"configured": configured, "ready": False, "items": []}
    path = os.path.join(root, FILE)
    try:
        st = os.stat(path)
    except OSError:
        return {"configured": True, "ready": False, "items": []}
    sig = (root, st.st_mtime_ns, st.st_size)
    if _cache["sig"] != sig:
        try:
            with open(path, encoding="utf-8-sig") as f:
                items = normalise(root, json.load(f))
            _cache.update(sig=sig, data={"configured": True, "ready": True, "items": items})
        except (OSError, ValueError):
            _cache.update(sig=None, data=None)
            return {"configured": True, "ready": False, "items": []}
    return _cache["data"]


_remote = {}   # url -> (time, bytes, mime)
_remote_lock = threading.Lock()


def fetch_remote(url):
    """A remote poster: (bytes, mime) or None. Through the system proxy first, directly if that fails (the hub proxy can be flaky)."""
    now = time.time()
    with _remote_lock:
        hit = _remote.get(url)
        if hit and now - hit[0] < REMOTE_TTL:
            return hit[1], hit[2]
    req = urllib.request.Request(url, headers={"User-Agent": "hub-motion-gallery"})
    for opener in (urllib.request.build_opener(), urllib.request.build_opener(urllib.request.ProxyHandler({}))):
        try:
            with opener.open(req, timeout=15) as r:
                data = r.read(REMOTE_MAX + 1)
                mime = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            if len(data) > REMOTE_MAX or not mime.startswith("image/"):
                return None
            with _remote_lock:
                _remote[url] = (now, data, mime)
                while len(_remote) > 64:
                    _remote.pop(next(iter(_remote)))
            return data, mime
        except Exception:
            continue
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def head(self, code, mime, length, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def say(self, code, data, extra=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.head(code, "application/json; charset=utf-8", len(body), {"Cache-Control": "no-store", **(extra or {})})
        if self.command != "HEAD":
            self.wfile.write(body)

    def guard(self):
        """Only localhost on its own port (not a spoofed name)."""
        host = (self.headers.get("Host") or "").lower()
        return None if host in (f"localhost:{PORT}", f"127.0.0.1:{PORT}") else "host"

    def cors(self):
        origin = self.headers.get("Origin")
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if origin in page_origins() else {}

    def do_OPTIONS(self):
        if self.guard() or not self.cors():
            return self.say(403, {"error": "origin"})
        self.head(204, "text/plain", 0, {**self.cors(), "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "600"})

    def do_GET(self):
        bad = self.guard()
        if bad:
            return self.say(403, {"error": bad})
        url = urlparse(self.path)
        extra = self.cors()
        if url.path == "/ping":
            return self.say(200, {"ok": True}, extra)
        if url.path == "/gallery.json":
            return self.say(200, load(), extra) if extra else self.say(403, {"error": "origin"})
        if url.path.startswith("/poster/"):
            return self.poster(unquote(url.path[len("/poster/"):]), extra)
        if url.path.startswith("/f/"):
            return self.file(unquote(url.path[3:]), extra)
        return self.say(404, {"error": "no page"})

    do_HEAD = do_GET

    def poster(self, slug, extra):
        item = next((i for i in load()["items"] if i["slug"] == slug), None)
        src = (item or {}).get("poster") or ""
        if not src:
            return self.say(404, {"error": "no poster"}, extra)
        if is_url(src):
            got = fetch_remote(src)
            if not got:
                return self.say(502, {"error": "poster not reachable"}, extra)
            data, mime = got
            self.head(200, mime, len(data), {"Cache-Control": "max-age=3600", **extra})
            if self.command != "HEAD":
                self.wfile.write(data)
            return
        return self.file(unquote(src[3:]), extra)

    def file(self, rel, extra):
        root = gallery_dir()
        real = inside(root, rel) if root else None
        mime = MEDIA.get(os.path.splitext(real or "")[1].lower()) if real else None
        if not real or not mime:
            return self.say(404, {"error": "no file"}, extra)
        size = os.path.getsize(real)
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(size - int(m.group(2)), 0)
            if start > end or start >= size:
                return self.head(416, "text/plain", 0, {"Content-Range": f"bytes */{size}", **extra})
            code = 206
        hdr = {"Accept-Ranges": "bytes", "Cache-Control": "max-age=300", **extra}
        if code == 206:
            hdr["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.head(code, mime, end - start + 1, hdr)
        if self.command == "HEAD":
            return
        try:
            with open(real, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    buf = f.read(min(CHUNK, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass   # the page left (hover ended): not an error


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    print(f"motion-gallery: http://127.0.0.1:{PORT}", flush=True)

    def stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, stop)
        except (ValueError, OSError):
            pass
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
