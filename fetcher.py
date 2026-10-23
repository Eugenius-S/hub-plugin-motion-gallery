"""Hub Motion Gallery: the downloader. Links in -> videos, posters and prompts in <state>/motion-gallery/library (the folder the
gallery reads when no gallery_dir is set): videos/<slug>.mp4, posters/<slug>.jpg, gallery.json.

plan(urls) reads the lists and a few pages and says how many examples, how many bytes (Content-Length of the sampled videos, the
average of the rest) and whether ffmpeg is there; nothing is saved. start(urls, compress) downloads in a thread; compress runs
ffmpeg over every video after it came. A link of a site without a reader is skipped and named in the plan.
Everything that touches the net or ffmpeg is an argument, so tests give fakes."""
import json
import os
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

import net
import sources

PER_LINK = 30                  # examples one link brings at most (the gallery is a shelf, not a mirror)
AVG_BYTES = 900 * 1024         # a video and its poster, measured on 92 references (94 MB)
SMALL = 0.35                   # the share ffmpeg leaves of a video (1280 px, crf 28)
SECONDS_EACH = 2.0             # a page, a video and a poster
VIDEO_MAX = 80 * 1024 * 1024
POSTER_MAX = 8 * 1024 * 1024
SAMPLE = 3
GIVE_UP = 10                   # failures in a row stop the run
VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")
POSTER_EXT = (".jpg", ".jpeg", ".png", ".webp")


def library(root):
    return os.path.join(root, "library")


def ext_of(url, allowed, default):
    e = os.path.splitext(urlparse(url).path)[1].lower()
    return e if e in allowed else default


def write_json(path, data):
    """Atomic; on Windows a reader holding the file makes the replace fail for a moment."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.1)


class Fetcher:
    def __init__(self, root, get=None, head=None, save=None, which=None, run=None, sleep=None):
        self.root = root
        self.get = get or net.get_text
        self.head = head or net.head_size
        self.save = save or net.save
        self.which = which or shutil.which
        self.run = run or subprocess.run
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self.thread = None
        self.stopping = False
        self.state = {"state": "idle", "done": 0, "total": 0, "bytes": 0, "current": "", "errors": [], "added": 0}

    # ---- what a download would be
    def ffmpeg(self):
        return self.which("ffmpeg") or ""

    def known(self):
        """The slugs already in the library."""
        try:
            with open(os.path.join(library(self.root), "gallery.json"), encoding="utf-8-sig") as f:
                return {str(r.get("slug")) for r in json.load(f).get("items", []) if isinstance(r, dict)}
        except (OSError, ValueError, AttributeError):
            return set()

    def listing(self, url):
        """(site, the new item pages of the link) - site None: no reader; the pages are cut to PER_LINK."""
        site = sources.for_url(url)
        if not site:
            return None, []
        have = self.known()
        found = [u for u in site.list(url, self.get) if site.slug(u) not in have]
        return site, found[:PER_LINK]

    def plan(self, urls):
        """-> {links: [{url, site, n, error}], n, bytes, exact, seconds, ffmpeg, small, skipped: [url]}"""
        links, skipped, total, sized = [], [], 0, []
        for url in urls:
            try:
                site, items = self.listing(url)
            except net.NetError as e:
                links.append({"url": url, "site": "", "n": 0, "error": e.what})
                continue
            if site is None:
                skipped.append(url)
                continue
            links.append({"url": url, "site": site.name, "n": len(items), "error": ""})
            total += len(items)
            for page_url in items[:SAMPLE]:
                try:
                    entry = site.read(page_url, self.get(page_url))
                    size = self.head(entry["video_url"]) if entry else 0
                except net.NetError:
                    size = 0
                if size:
                    sized.append(size + 60 * 1024)
        avg = sum(sized) // len(sized) if sized else AVG_BYTES
        size = avg * total
        return {"links": links, "n": total, "bytes": size, "exact": bool(total) and total <= SAMPLE and len(sized) == total,
                "seconds": int(total * SECONDS_EACH), "ffmpeg": bool(self.ffmpeg()), "small": int(size * SMALL), "skipped": skipped}

    # ---- the download
    def status(self):
        with self.lock:
            return dict(self.state, errors=list(self.state["errors"]))

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, urls, compress=False):
        """-> True: started; False: a run is going."""
        if self.running():
            return False
        self.stopping = False
        with self.lock:
            self.state = {"state": "running", "done": 0, "total": 0, "bytes": 0, "current": "", "errors": [], "added": 0, "compress": bool(compress and self.ffmpeg())}
        self.thread = threading.Thread(target=self._run, args=(list(urls), bool(compress and self.ffmpeg())), daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stopping = True
        with self.lock:
            if self.state["state"] == "running":
                self.state["state"] = "stopping"

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _error(self, what):
        with self.lock:
            self.state["errors"] = (self.state["errors"] + [what])[-5:]

    def _run(self, urls, compress):
        try:
            work = []
            for url in urls:
                if self.stopping:
                    break
                try:
                    site, items = self.listing(url)
                except net.NetError as e:
                    self._error(f"{net.host(url)}: {e.what}")
                    continue
                if site:
                    work += [(site, url, u) for u in items]
                    self._set(total=len(work))
            failed = 0
            for site, link, page_url in work:
                if self.stopping or failed >= GIVE_UP:
                    break
                self._set(current=net.host(page_url))
                try:
                    size = self._one(site, link, page_url, compress)
                    failed = 0
                    with self.lock:
                        self.state["bytes"] += size
                        self.state["added"] += 1 if size else 0
                except net.NetError as e:
                    failed += 1
                    self._error(f"{net.host(page_url)}: {e.what}")
                    net.log(f"{net.host(page_url)}: {e.what}")
                except Exception as e:   # one broken page must not stop the rest
                    failed += 1
                    self._error(f"{net.host(page_url)}: {type(e).__name__}")
                    net.log(f"{net.host(page_url)}: {type(e).__name__}: {e}")
                with self.lock:
                    self.state["done"] += 1
                self.sleep(0.3)
            self._set(state="stopped" if self.stopping else ("error" if failed >= GIVE_UP else "done"), current="")
        except Exception as e:
            net.log(f"downloader: {type(e).__name__}: {e}")
            self._error(type(e).__name__)
            self._set(state="error", current="")

    def _one(self, site, link, page_url, compress):
        """One example -> bytes saved (0: the page has no video)."""
        entry = site.read(page_url, self.get(page_url))
        if not entry:
            return 0
        lib = library(self.root)
        slug = entry["slug"]
        rel = f"videos/{slug}{ext_of(entry['video_url'], VIDEO_EXT, '.mp4')}"
        size = self.save(entry["video_url"], os.path.join(lib, *rel.split("/")), VIDEO_MAX)
        if compress:
            size = self._squeeze(os.path.join(lib, *rel.split("/")), size)
        poster = ""
        if entry["poster_url"]:
            prel = f"posters/{slug}{ext_of(entry['poster_url'], POSTER_EXT, '.jpg')}"
            try:
                size += self.save(entry["poster_url"], os.path.join(lib, *prel.split("/")), POSTER_MAX)
                poster = prel
            except net.NetError as e:   # a gallery without this poster still plays the video
                net.log(f"poster {net.host(entry['poster_url'])}: {e.what}")
        self._add({"slug": slug, "title": entry["title"], "author": entry["author"], "category": "", "tags": entry["tags"], "prompt": entry["prompt"],
                   "sources": [site.name], "pages": {site.name: page_url}, "video": rel, "poster": poster, "seconds": entry["seconds"], "from": link})
        return size

    def _squeeze(self, path, size):
        """ffmpeg over a video; the smaller of the two stays. -> the size now."""
        exe = self.ffmpeg()
        out = os.path.splitext(path)[0] + ".small.mp4"
        try:
            p = self.run([exe, "-y", "-v", "error", "-i", path, "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                          "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out], capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
            if p.returncode == 0 and os.path.isfile(out) and 0 < os.path.getsize(out) < size:
                small = os.path.getsize(out)
                final = os.path.splitext(path)[0] + ".mp4"
                os.replace(out, final)
                if final != path:
                    os.remove(path)
                return small
        except (OSError, subprocess.SubprocessError) as e:
            net.log(f"ffmpeg: {type(e).__name__}")
        try:
            os.remove(out)
        except OSError:
            pass
        return size

    def _add(self, entry):
        """The entry into gallery.json (a video the compression renamed to .mp4 is found by its slug)."""
        lib = library(self.root)
        for ext in VIDEO_EXT:
            if os.path.isfile(os.path.join(lib, "videos", entry["slug"] + ext)):
                entry["video"] = f"videos/{entry['slug']}{ext}"
                break
        path = os.path.join(lib, "gallery.json")
        with self.lock:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {"items": []}
            items = [r for r in data.get("items", []) if isinstance(r, dict) and r.get("slug") != entry["slug"]]
            items.append(entry)
            write_json(path, {"items": items})
