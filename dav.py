"""Hub Motion Gallery: WebDAV client for deleting examples from a gallery that lives on a Nextcloud-style storage.

Reading goes by the public link (media_base); that link is read-only, so removing files needs the owner's own login:
a JSON file {"server", "user", "password", "root"} named by the setting dav_login (no login file is guessed).
Only curl is used (it has its own certificate store and speaks to the hub proxy); the password goes to curl through stdin
(-K -), never into its arguments, the log or an answer. Nothing here prints the password or the login file path's content.
"""
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import quote

DEFAULT_FOLDER = "motion-gallery"
MEDIA = (".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp")   # the only files the plugin ever puts there
TIMEOUT = 60
PROPFIND = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'


class DavError(Exception):
    """code: http status (0 - no answer), what: a short word for the log (never a secret)."""

    def __init__(self, code, what):
        super().__init__(f"{what} (HTTP {code})" if code else what)
        self.code, self.what = code, what


def read_login(path=""):
    """The login dict {server, user, password, root} or None: no path / no file / not readable / incomplete."""
    if not path:
        return None
    try:
        with open(os.path.expandvars(os.path.expanduser(path)), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ("server", "user", "password")):
        return {"server": d["server"].rstrip("/"), "user": d["user"], "password": d["password"], "root": str(d.get("root") or "").strip("/")}
    return None


def run_curl(args, password_line, timeout=TIMEOUT):
    """curl with the credentials on stdin; -> (returncode, stderr text)."""
    exe = shutil.which("curl")
    if not exe:
        return 127, "curl is not installed"
    r = subprocess.run([exe, "-sS", "-K", "-", "--max-time", str(timeout)] + args, input=password_line.encode("utf-8"),
                       capture_output=True, timeout=timeout + 10)
    return r.returncode, r.stderr.decode("utf-8", "replace").strip()[:200]


class Dav:
    """A folder of the storage: get / put (with If-Match) / delete by a path relative to it."""

    def __init__(self, login, folder=DEFAULT_FOLDER, runner=run_curl):
        self.login, self.runner = login, runner
        parts = [login["root"]] if login.get("root") else []
        parts.append(folder.strip("/"))
        self.base = "{}/remote.php/dav/files/{}/{}".format(login["server"], quote(login["user"]), "/".join(quote(p, safe="/") for p in parts))

    def url(self, rel):
        return self.base + "/" + "/".join(quote(p) for p in rel.replace("\\", "/").split("/") if p)

    def call(self, method, rel, data=None, headers=None):
        """-> (http status, response headers dict (lower case), body bytes)."""
        auth = 'user = "{}:{}"\n'.format(self.login["user"].replace('"', '\\"'), self.login["password"].replace("\\", "\\\\").replace('"', '\\"'))
        with tempfile.TemporaryDirectory() as tmp:
            hdr, out = os.path.join(tmp, "h"), os.path.join(tmp, "o")
            args = ["-X", method, "-D", hdr, "-o", out]
            for k, v in (headers or {}).items():
                args += ["-H", f"{k}: {v}"]
            if data is not None:
                src = os.path.join(tmp, "i")
                with open(src, "wb") as f:
                    f.write(data)
                args += ["-T", src] if method == "PUT" else ["--data-binary", "@" + src]
            args.append(self.url(rel))
            try:
                code, err = self.runner(args, auth)
            except (OSError, subprocess.SubprocessError) as e:
                raise DavError(0, f"curl failed: {type(e).__name__}")
            if code != 0:
                raise DavError(0, f"curl exit {code}: {err.replace(self.login['password'], '***')}")
            status, heads = 0, {}
            try:
                with open(hdr, encoding="utf-8", errors="replace") as f:
                    for line in f.read().splitlines():
                        if line.startswith("HTTP/"):
                            status, heads = int((line.split() + ["0", "0"])[1]), {}   # the last block wins (redirects)
                        elif ":" in line:
                            k, v = line.split(":", 1)
                            heads[k.strip().lower()] = v.strip()
                with open(out, "rb") as f:
                    body = f.read()
            except (OSError, ValueError):
                raise DavError(0, "no answer")
            return status, heads, body

    def get(self, rel):
        """-> (bytes, etag)."""
        st, h, body = self.call("GET", rel)
        if st != 200:
            raise DavError(st, "read failed")
        return body, h.get("etag", "")

    def put(self, rel, data, etag=""):
        st, _, _ = self.call("PUT", rel, data, {"If-Match": etag} if etag else None)
        if st == 412:
            raise DavError(412, "changed meanwhile")
        if st not in (200, 201, 204):
            raise DavError(st, "write failed")

    def is_file(self, rel):
        """True: a file; False: nothing there. A folder or an answer that does not say raises (the caller must not delete)."""
        st, _, body = self.call("PROPFIND", rel, PROPFIND, {"Depth": "0", "Content-Type": "application/xml"})
        if st == 404:
            return False
        if st != 207:
            raise DavError(st, "could not check the target")
        try:
            kind = ET.fromstring(body).find(".//{DAV:}resourcetype")
        except ET.ParseError:
            kind = None
        if kind is None:
            raise DavError(st, "could not check the target")
        if kind.find("{DAV:}collection") is not None:
            raise DavError(400, "the target is a folder")
        return True

    def delete(self, rel):
        """Deletes one file of ours by its exact path. Not a folder, not the root, not a file that is not media, and nothing when
        the target can not be told to be a plain file. A missing file is not an error (it is gone either way)."""
        parts = rel.replace("\\", "/").split("/") if isinstance(rel, str) else []
        if (not parts or rel.strip("/ .") == "" or rel.endswith("/") or any(p in ("", ".", "..") for p in parts)
                or not rel.lower().endswith(MEDIA)):
            raise DavError(400, "not a file of ours")
        if not self.is_file(rel):
            return
        st, _, _ = self.call("DELETE", rel)
        if st not in (200, 202, 204, 404):
            raise DavError(st, "delete failed")
