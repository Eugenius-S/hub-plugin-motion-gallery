"""Hub Motion Gallery: the memory of the links the downloader takes (a small file in the plugin state folder, not in the browser: the links
survive a restart and are the same on every page).

links.json: {"links": [{"url", "default"}], "seeded": bool, "first": str, "ask_posted": bool}
  seeded - the links by default are put once (a removed one does not come back);
  first - the question of the first start: "pending" (asked, nothing is downloaded until the answer), "yes" | "no" | "settings" (the answer),
  "config" (the owner's hub.json already points the plugin at a gallery: no question), "legacy" (the file is older than the question);
  "" - not asked yet; ask_posted - the question went to Telegram."""
import json
import os
import threading

NAME = "links.json"
FIRST = ("", "pending", "yes", "no", "settings", "config", "legacy")
LINK_MAX = 500
LINKS_MAX = 40

_lock = threading.Lock()


def canon(url):
    """The link as it is kept: no spaces, no slash at the end."""
    return str(url or "").strip().rstrip("/")


class Links:
    """One file; every change is written at once (atomically)."""

    def __init__(self, path):
        self.path = path
        self.data = self._read()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = None
        fresh = not isinstance(d, dict)
        d = {} if fresh else d
        links = [x for x in d.get("links", []) if isinstance(x, dict) and isinstance(x.get("url"), str)] if isinstance(d.get("links"), list) else []
        seeded = bool(d.get("seeded")) and not fresh
        first = d.get("first") if d.get("first") in FIRST else ""
        if seeded and not first:   # written before the question existed: it had downloaded already
            first = "legacy"
        return {"links": links, "seeded": seeded, "first": first, "ask_posted": bool(d.get("ask_posted"))}

    def _write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def urls(self):
        with _lock:
            return [x["url"] for x in self.data["links"]]

    def items(self):
        with _lock:
            return [{"url": x["url"], "default": bool(x.get("default"))} for x in self.data["links"]]

    def has(self, url):
        return url in self.urls()

    def add(self, url, default=False):
        """-> True if the link is new."""
        with _lock:
            if any(x["url"] == url for x in self.data["links"]):
                return False
            self.data["links"].append({"url": url, **({"default": True} if default else {})})
            self._write()
            return True

    def remove(self, url):
        with _lock:
            self.data["links"] = [x for x in self.data["links"] if x["url"] != url]
            self._write()

    def seed(self, defaults):
        """The links by default, once. -> the links that were put."""
        with _lock:
            if self.data["seeded"]:
                return []
            put = []
            for url in defaults:
                if not any(x["url"] == url for x in self.data["links"]):
                    self.data["links"].append({"url": url, "default": True})
                    put.append(url)
            self.data["seeded"] = True
            self._write()
            return put

    @property
    def seeded(self):
        return self.data["seeded"]

    @property
    def first(self):
        return self.data["first"]

    @property
    def ask_posted(self):
        return self.data["ask_posted"]

    def set_first(self, value):
        with _lock:
            self.data["first"] = value if value in FIRST else ""
            if value in ("", "pending"):
                self.data["ask_posted"] = False
            self._write()

    def set_ask_posted(self, value):
        with _lock:
            self.data["ask_posted"] = bool(value)
            self._write()
