"""Hub Motion Gallery: the plugin process serves a gallery folder (gallery.json, previews, posters) to the hub page.

The folder is set in hub.json (extensions.<account>:motion-gallery.gallery_dir, or MOTION_GALLERY_DIR for tests); nothing is
set - an empty gallery with a hint. Relative paths of gallery.json that are not in the folder are taken from a web base
(media_base, or MOTION_GALLERY_BASE): <base>/<path>; with a base and no folder gallery.json is read from <base>/gallery.json. The process listens on localhost, hub page port + 12, and answers only the hub page
(Origin) for data; videos and pictures are plain GETs (a <video> and an <img> send no Origin).
  /gallery.json   the normalised list (see load())
  /f/<path>       a file of the gallery folder, with Range for video; never outside the folder
  /poster/<slug>  the poster as bytes: a file, or a remote URL fetched here (the page can not read a foreign image)
"""
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
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


def setting(key, env):
    """A setting of the plugin: the environment (tests) first, then hub.json extensions.<account>:motion-gallery.<key>; "" - not set."""
    val = (os.environ.get(env) or "").strip()
    if val:
        return val
    for k, v in (config().get("extensions") or {}).items():
        if isinstance(v, dict) and str(k).rsplit(":", 1)[-1] == NAME and str(v.get(key) or "").strip():
            return str(v[key]).strip()
    return ""


def gallery_dir():
    """The folder of the gallery, or None: not set / not a folder."""
    path = setting("gallery_dir", "MOTION_GALLERY_DIR")
    if not path:
        return None
    real = os.path.realpath(os.path.expanduser(path))
    return real if os.path.isdir(real) else None


def media_base():
    """The web base for relative paths (no slash at the end), or "": not set / not an http(s) address."""
    val = setting("media_base", "MOTION_GALLERY_BASE").rstrip("/")
    return val if is_url(val) else ""


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


PROMPT_MAX = 40000   # prompts go into the chat whole: the longest real one is about 15k


def text(v, limit=4000):
    return v.strip()[:limit] if isinstance(v, str) else ""


def tags_of(v):
    if isinstance(v, str):
        v = re.split(r"[,;]", v)
    return [x.strip() for x in v if isinstance(x, str) and x.strip()][:30] if isinstance(v, list) else []


def skill_of(v):
    """An entry that is a skill, not a prompt: {desc, install, repo} (all text) or None."""
    if not isinstance(v, dict):
        return None
    s = {k: text(v.get(k), 1000) for k in ("desc", "install", "repo")}
    return s if any(s.values()) else None


def duration_of(v):
    try:
        n = float(v)
        return round(n, 1) if n > 0 else 0
    except (TypeError, ValueError):
        return 0


def media(root, base, slug, value, folder, exts):
    """Address of a preview or poster: a URL as is; a file of the folder as /f/<path>; else <base>/<path>.
    No value - <folder>/<slug>.<ext> in the folder if it exists."""
    value = text(value, 1000)
    if is_url(value):
        return value
    rel = value.replace("\\", "/").lstrip("/")
    if value and root and inside(root, value):
        return "/f/" + quote(rel, safe="/")
    if value and base and rel and not any(p == ".." for p in rel.split("/")):
        return base + "/" + quote(rel, safe="/")
    if not value and root:
        for ext in exts:
            rel = f"{folder}/{slug}{ext}"
            if inside(root, rel):
                return "/f/" + quote(rel, safe="/")
    return ""


def links_of(r):
    """Links to the originals: pages {source: url} (or a plain list of urls), then post and page. -> [{source, url}]"""
    out = []
    pages = r.get("pages")
    if isinstance(pages, dict):
        out += [{"source": text(k, 80), "url": text(u, 1000)} for k, u in pages.items() if is_url(u)]
    elif isinstance(pages, list):
        out += [{"source": "", "url": text(u, 1000)} for u in pages if is_url(u)]
    for key in ("post", "page"):
        if is_url(r.get(key)) and not any(l["url"] == text(r[key], 1000) for l in out):
            out.append({"source": "", "url": text(r[key], 1000)})
    return out[:8]


def normalise(root, raw, base=""):
    """gallery.json (a list or {items: [...]}) -> the entries the page draws. Entries without a slug or without any picture are dropped."""
    rows = raw.get("items") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        slug = re.sub(r"[^\w.-]", "-", text(r.get("slug") or r.get("id"), 120)).strip("-")
        if not slug or slug in seen:
            continue
        video = media(root, base, slug, r.get("video"), "videos", (".mp4", ".webm", ".mov"))
        preview = media(root, base, slug, r.get("preview"), "previews", (".mp4", ".webm", ".mov")) or video
        poster = media(root, base, slug, r.get("poster"), "posters", (".jpg", ".jpeg", ".png", ".webp"))
        if not preview and not poster:
            continue
        seen.add(slug)
        links = links_of(r)
        sources = tags_of(r.get("sources") or r.get("source")) or [l["source"] for l in links if l["source"]]
        out.append({"slug": slug, "author": text(r.get("author"), 200), "category": text(r.get("category"), 120), "duration": duration_of(r.get("duration") or r.get("seconds")),
                    "title": text(r.get("title"), 200), "note": text(r.get("prompt_note"), 600), "skill": skill_of(r.get("skill")), "tags": tags_of(r.get("tags")), "prompt": text(r.get("prompt"), PROMPT_MAX), "sources": list(dict.fromkeys(sources)), "links": links,
                    "post": text(r.get("post"), 1000) if is_url(r.get("post")) else "", "page": text(r.get("page"), 1000) if is_url(r.get("page")) else "",
                    "preview": preview, "video": video or preview, "poster": poster})
    return out


_cache = {"sig": None, "data": None}
_web = {"url": None, "time": 0, "raw": None, "failed": 0}
WEB_TTL = 60
FAIL_TTL = 30   # after a failed read the base is not asked again for this long (a dead link must not stall every request)


def web_gallery(base):
    """gallery.json from <base>/gallery.json (no folder set): the parsed JSON or None. Kept for WEB_TTL seconds."""
    now = time.time()
    same = _web["url"] == base
    if same and _web["raw"] is not None and now - _web["time"] < WEB_TTL:
        return _web["raw"]
    if same and now - _web["failed"] < FAIL_TTL:
        return _web["raw"]
    got = fetch_url(base + "/" + FILE, 20 * 1024 * 1024)
    try:
        raw = json.loads(got[0].decode("utf-8-sig")) if got else None
    except ValueError as e:
        log(f"{url_host(base)}: {FILE} is not JSON ({e})")
        raw = None
    if raw is None:
        if not same:
            _web.update(url=base, time=0, raw=None)
        _web["failed"] = time.time()
        return _web["raw"]   # an old copy is better than an empty page
    _web.update(url=base, time=now, raw=raw, failed=0)
    return raw


def load():
    """{configured, ready, items}: configured - a folder or a base is set in the settings, ready - gallery.json is readable."""
    root, base = gallery_dir(), media_base()
    if not root:
        folder = setting("gallery_dir", "MOTION_GALLERY_DIR")
        raw = web_gallery(base) if base and not folder else None
        if raw is None:
            return {"configured": bool(folder or base), "ready": False, "items": []}
        sig = ("web", base, _web["time"])
        if _cache["sig"] != sig:
            _cache.update(sig=sig, data={"configured": True, "ready": True, "items": normalise(None, raw, base)})
        return _cache["data"]
    path = os.path.join(root, FILE)
    try:
        st = os.stat(path)
    except OSError:
        return {"configured": True, "ready": False, "items": []}
    sig = (root, base, st.st_mtime_ns, st.st_size)
    if _cache["sig"] != sig:
        try:
            with open(path, encoding="utf-8-sig") as f:
                items = normalise(root, json.load(f), base)
            _cache.update(sig=sig, data={"configured": True, "ready": True, "items": items})
        except (OSError, ValueError):
            _cache.update(sig=None, data=None)
            return {"configured": True, "ready": False, "items": []}
    return _cache["data"]


_remote = {}   # url -> (time, bytes, mime)
_remote_lock = threading.Lock()


def log(msg):
    print("motion-gallery: " + msg, file=sys.stderr, flush=True)


def fetch_with_curl(url, limit):
    """The last way: curl (it has its own certificate store and speaks to the hub proxy), (bytes, "") or None."""
    exe = shutil.which("curl")
    if not exe:
        log("curl is not installed, cannot read " + url_host(url))
        return None
    try:
        r = subprocess.run([exe, "-sSfL", "--max-time", "30", "--max-filesize", str(limit), url],
                           capture_output=True, timeout=40, stdin=subprocess.DEVNULL)
    except Exception as e:
        log(f"curl failed for {url_host(url)}: {e}")
        return None
    if r.returncode != 0:
        log(f"curl failed for {url_host(url)}: exit {r.returncode} {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
        return None
    if len(r.stdout) > limit:
        log(f"{url_host(url)}: the file is bigger than {limit} bytes")
        return None
    return r.stdout, ""


def url_host(url):
    """The address for the log without its path and query (a public link may carry a token)."""
    return urlparse(url).netloc or "?"


def fetch_url(url, limit):
    """(bytes, mime) of a remote file or None. Directly without a proxy first (the hub proxy drops these connections), then
    through curl (Python on some machines does not trust the certificate that curl trusts; curl also uses the proxy from the
    environment). The reason of every failure goes to the log of the process."""
    req = urllib.request.Request(url, headers={"User-Agent": "hub-motion-gallery"})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15) as r:
            data = r.read(limit + 1)
            mime = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        if len(data) > limit:
            log(f"{url_host(url)}: the file is bigger than {limit} bytes")
            return None
        return data, mime
    except urllib.error.HTTPError as e:   # the server answered: a missing file stays missing, curl would get the same
        log(f"{url_host(url)}: HTTP {e.code}")
        return None
    except Exception as e:
        log(f"python could not read {url_host(url)} ({type(e).__name__}: {e}); trying curl")
    return fetch_with_curl(url, limit)


def sniff_image(data):
    """The mime of a picture by its first bytes, "" if it is not one we know."""
    for magic, mime in ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF8", "image/gif")):
        if data.startswith(magic):
            return mime
    return "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""


def fetch_remote(url):
    """A remote poster: (bytes, mime) or None; kept for REMOTE_TTL."""
    now = time.time()
    with _remote_lock:
        hit = _remote.get(url)
        if hit and now - hit[0] < REMOTE_TTL:
            return hit[1], hit[2]
    got = fetch_url(url, REMOTE_MAX)
    if got and not got[1].startswith("image/"):
        got = (got[0], sniff_image(got[0]))   # a storage may answer application/octet-stream for a picture
    if not got or not got[1].startswith("image/"):
        return None
    with _remote_lock:
        _remote[url] = (now, got[0], got[1])
        while len(_remote) > 64:
            _remote.pop(next(iter(_remote)))
    return got


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
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(f"motion-gallery: port {PORT} (hub page port + 12) is busy: {e}", file=sys.stderr, flush=True)
        return 1
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
