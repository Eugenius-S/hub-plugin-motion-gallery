"""Hub Motion Gallery: reading and downloading from the web for the downloader (fetcher.py).

Directly without a proxy first (the hub proxy drops these connections), then curl (it has its own certificate store and
speaks to the hub proxy). Nothing is written under the final name until the whole file came; a file bigger than the limit
is not taken. Only http and https addresses are read (safe_url): a file:, data:, ftp: or plain path is refused before any request, a
redirect to anything else is refused too, in Python and in curl. Addresses go to the log by host only.

The downloader reads public addresses only (0.5.1): localhost, 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, 100.64/10, ::1,
fc00::/7 and fe80::/10 (and the same inside ::ffff:a.b.c.d) are refused, so a page cannot send the plugin to the owner's own machine or
network. The check is made on the address the name resolves to, at the moment of connecting (the connection goes to the vetted
address itself, so a name that answers differently the second time gains nothing), for every redirect, in Python and in curl."""
import http.client
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

UA = "hub-motion-gallery"
TEXT_MAX = 6 * 1024 * 1024
CHUNK = 256 * 1024
HOPS = 6                       # redirects followed by hand in the curl way
ALLOW_PRIVATE = False          # tests only (a local site stands in for the web); nothing in the plugin sets it

PRIVATE = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
    "::/128", "::1/128", "fc00::/7", "fe80::/10")]


class NetError(Exception):
    """Could not read the address: code is an HTTP status (0 - no answer), what - for the log and the report."""

    def __init__(self, code, what):
        super().__init__(what)
        self.code, self.what = code, what


def host(url):
    return urlparse(url).netloc or "?"


def log(msg):
    print("motion-gallery: " + msg, file=sys.stderr, flush=True)


def safe_url(url):
    """The address itself when it is an http(s) address with a host; NetError otherwise (file:, data:, ftp:, a path, nothing)."""
    u = url.strip() if isinstance(url, str) else ""
    try:
        p = urlparse(u)
        ok = p.scheme.lower() in ("http", "https") and bool(p.hostname)
    except ValueError:
        ok = False
    if not ok or any(c in u for c in "\r\n\0"):
        raise NetError(0, "only http and https addresses are read")
    return u


def is_private(addr):
    """True for an address of this machine or of a private network (see the top); a name that is not an address - False."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in PRIVATE)


def _local_name(name):
    name = (name or "").rstrip(".").lower()
    return name == "localhost" or name.endswith(".localhost")


def vet(name, port):
    """The addresses [(family, type, proto, canon, sockaddr)] the name resolves to, all of them public; NetError otherwise."""
    if not ALLOW_PRIVATE and (_local_name(name) or is_private(name)):
        raise NetError(0, "private and local addresses are not read")
    try:
        found = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
    except OSError:
        raise NetError(0, "the name did not resolve")
    if not found:
        raise NetError(0, "the name did not resolve")
    if not ALLOW_PRIVATE and any(is_private(f[4][0]) for f in found):
        raise NetError(0, "private and local addresses are not read")
    return found


def _connect(name, port, timeout, source=None):
    """A socket to the vetted address of the name (the first that answers)."""
    err = None
    for family, kind, proto, _, addr in vet(name, port):
        sock = None
        try:
            sock = socket.socket(family, kind, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source:
                sock.bind(source)
            sock.connect(addr)
            return sock
        except OSError as e:
            err = e
            if sock:
                sock.close()
    raise err or NetError(0, "could not connect")


class _PublicHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _connect(self.host, self.port, self.timeout, self.source_address)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class _PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _connect(self.host, self.port, self.timeout, self.source_address)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTP, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPS, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(urljoin(req.full_url, newurl))   # a redirect to file:, ftp: ... is not followed
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build(public=False):
    """urllib with http and https only (build_opener alone adds file:, ftp: and data:), no proxy, redirects checked; public - every
    connection goes to a vetted public address (the downloader)."""
    o = urllib.request.OpenerDirector()
    web = (_HTTP(), _HTTPS()) if public else (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    for h in (urllib.request.ProxyHandler({}), *web, _Redirects(),
              urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def _open(url, method="GET", timeout=20):
    req = urllib.request.Request(safe_url(url), method=method, headers={"User-Agent": UA})
    return build(True).open(req, timeout=timeout)


def _curl(url, args, timeout, out):
    """curl, hop by hop: every address is vetted and handed to curl (--resolve), a redirect is followed here and not by curl, so a
    redirect to a private address is refused like the first address. The body (or the headers of -I) goes to the file out.
    -> the HTTP status of the last answer; NetError otherwise. (A proxy in the environment resolves the name itself: the name is
    still vetted here, the connection of that case is the proxy's.)"""
    exe = shutil.which("curl")
    if not exe:
        raise NetError(0, "curl is not installed")
    for _ in range(HOPS):
        url = safe_url(url)
        p = urlparse(url)
        port = p.port or (443 if p.scheme.lower() == "https" else 80)
        ip = vet(p.hostname, port)[0][4][0]
        pin = [] if ALLOW_PRIVATE else ["--resolve", f"{p.hostname}:{port}:{'[' + ip + ']' if ':' in ip else ip}"]
        try:
            r = subprocess.run([exe, "-sS", "--proto", "=http,https", "-o", out, "-w", "%{http_code} %{redirect_url}", *pin, *args, url],
                               capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise NetError(0, "timeout")
        if r.returncode != 0:
            raise NetError(0, f"curl exit {r.returncode}")
        word, _, nxt = r.stdout.decode("latin1").strip().partition(" ")
        code = int(word) if word.isdigit() else 0
        if 300 <= code < 400 and nxt.strip():
            url = nxt.strip()
            continue
        if code >= 400:
            raise NetError(code, f"HTTP {code}")
        return code
    raise NetError(0, "too many redirects")


def get_text(url, limit=TEXT_MAX):
    """The page as text."""
    url = safe_url(url)
    try:
        with _open(url) as r:
            data = r.read(limit + 1)
    except NetError:
        raise
    except urllib.error.HTTPError as e:
        raise NetError(e.code, f"HTTP {e.code}")
    except Exception as e:
        log(f"python could not read {host(url)} ({type(e).__name__}); trying curl")
        data = _curl_text(url, limit)
    if len(data) > limit:
        raise NetError(0, "page too big")
    return data.decode("utf-8", "replace")


def _curl_text(url, limit):
    fd, tmp = tempfile.mkstemp(prefix="mg-net-")
    os.close(fd)
    try:
        _curl(url, ["--max-time", "30", "--max-filesize", str(limit), "-A", UA], 40, tmp)
        with open(tmp, "rb") as f:
            return f.read(limit + 1)
    finally:
        _drop(tmp)


def head_size(url):
    """Content-Length of the file, or 0 when the server does not say (or the address is not http/https)."""
    try:
        url = safe_url(url)
    except NetError:
        return 0
    try:
        with _open(url, "HEAD") as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        pass
    fd, tmp = tempfile.mkstemp(prefix="mg-net-")
    os.close(fd)
    try:
        _curl(url, ["-I", "-A", UA, "--max-time", "20"], 30, tmp)
        with open(tmp, "rb") as f:
            sizes = [int(x) for x in _lengths(f.read(65536).decode("latin1", "replace"))]
    except (NetError, OSError):
        return 0
    finally:
        _drop(tmp)
    return sizes[-1] if sizes else 0


def _lengths(headers):
    import re
    return re.findall(r"(?i)content-length:\s*(\d+)", headers)


def save(url, path, limit):
    """The file at url -> path (through path.part). -> its size."""
    url = safe_url(url)
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
        try:
            _curl(url, ["--max-time", "120", "--max-filesize", str(limit), "-A", UA], 130, part)
        except NetError:
            _drop(part)
            raise
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
