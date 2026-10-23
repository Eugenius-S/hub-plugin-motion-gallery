"""Hub Motion Gallery: reading and downloading from the web for the downloader (fetcher.py).

Directly without a proxy first (the hub proxy drops these connections), then curl (it has its own certificate store and
speaks to the hub proxy). Nothing is written under the final name until the whole file came; a file bigger than the limit
is not taken. Addresses go to the log by host only."""
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

UA = "hub-motion-gallery"
TEXT_MAX = 6 * 1024 * 1024
CHUNK = 256 * 1024


class NetError(Exception):
    """Could not read the address: code is an HTTP status (0 - no answer), what - for the log and the report."""

    def __init__(self, code, what):
        super().__init__(what)
        self.code, self.what = code, what


def host(url):
    return urlparse(url).netloc or "?"


def log(msg):
    print("motion-gallery: " + msg, file=sys.stderr, flush=True)


def _open(url, method="GET", timeout=20):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def _curl(args, timeout):
    exe = shutil.which("curl")
    if not exe:
        raise NetError(0, "curl is not installed")
    try:
        return subprocess.run([exe, "-sSfL", *args], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise NetError(0, "timeout")


def get_text(url, limit=TEXT_MAX):
    """The page as text."""
    try:
        with _open(url) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise NetError(e.code, f"HTTP {e.code}")
    except Exception as e:
        log(f"python could not read {host(url)} ({type(e).__name__}); trying curl")
        p = _curl(["--max-time", "30", "--max-filesize", str(limit), "-A", UA, url], 40)
        if p.returncode != 0:
            raise NetError(0, f"curl exit {p.returncode}")
        data = p.stdout
    if len(data) > limit:
        raise NetError(0, "page too big")
    return data.decode("utf-8", "replace")


def head_size(url):
    """Content-Length of the file, or 0 when the server does not say."""
    try:
        with _open(url, "HEAD") as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        pass
    try:
        p = _curl(["-I", "-A", UA, "--max-time", "20", url], 30)
    except NetError:
        return 0
    sizes = [int(x) for x in _lengths(p.stdout.decode("latin1", "replace"))]
    return sizes[-1] if sizes else 0


def _lengths(headers):
    import re
    return re.findall(r"(?i)content-length:\s*(\d+)", headers)


def save(url, path, limit):
    """The file at url -> path (through path.part). -> its size."""
    part = path + ".part"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    size = 0
    try:
        with _open(url, timeout=30) as r, open(part, "wb") as f:
            while True:
                buf = r.read(CHUNK)
                if not buf:
                    break
                size += len(buf)
                if size > limit:
                    raise NetError(0, "file too big")
                f.write(buf)
    except NetError:
        _drop(part)
        raise
    except urllib.error.HTTPError as e:
        _drop(part)
        raise NetError(e.code, f"HTTP {e.code}")
    except Exception as e:
        log(f"python could not read {host(url)} ({type(e).__name__}); trying curl")
        _drop(part)
        p = _curl(["--max-time", "120", "--max-filesize", str(limit), "-A", UA, "-o", part, url], 130)
        if p.returncode != 0:
            _drop(part)
            raise NetError(0, f"curl exit {p.returncode}")
        size = os.path.getsize(part)
    if size == 0:
        _drop(part)
        raise NetError(0, "empty file")
    os.replace(part, path)
    return size


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass
