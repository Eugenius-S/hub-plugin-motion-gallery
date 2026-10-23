"""Hub Motion Gallery: what the settings tab "Motion Gallery: sources" does with the links (the page only calls it through /__canvas/fetch).

One object joins the memory of the links (links.py), the downloader (fetcher.py) and the question of the first start (firstrun.py):
  startup()   - at the start of the plugin: the links by default are put once; the first time (and only then) the owner is asked and NOTHING is
                downloaded until the answer "Download". A hub whose hub.json already points the plugin at a gallery (gallery_dir / media_base) is
                not asked: it has its examples already.
  status()    - what the page draws: the links with the reader of each, the question, the progress of the download
  act(body)   - add / remove a link, plan (the estimate), start (compress or as is), stop, firstrun (the answer, or "again")
A download that nobody watches (the answer "Download", a run that went on after the page closed) tells the owner once when it is over."""
import threading

import firstrun
import links as linkmem
import sources

# the sources the owner named: sites with prompts and videos, and repositories of motion work
DEFAULTS = [
    "https://skillry.dev/ai-videos",
    "https://prompt-motion.com",
    "https://claude-motion.com/gallery",
    "https://www.remotion.dev/prompts",
    "https://github.com/heygen-com/hyperframes",
    "https://github.com/per-simmons/launch-video-clone",
    "https://github.com/Liamrjohnston/remotion-motion-graphics-skill",
    "https://github.com/AbubakrChan/product-launch-motion",
]
NOTE_ID = "motion-gallery-fetched"
NOTE = {
    "en": ("Motion Gallery: {n} examples downloaded", "Motion Gallery downloaded {n} examples.{extra}"),
    "ru": ("Motion Gallery: скачано примеров - {n}", "Motion Gallery скачал примеров: {n}.{extra}"),
}
EXTRA = {"en": " {m} failed to download.", "ru": " Не удалось скачать: {m}."}


def _lang():
    try:
        from core import i18n
        return "ru" if str(i18n.current()).startswith("ru") else "en"
    except Exception:
        return "en"


class Ctl:
    """links - links.Links; fetch - fetcher.Fetcher; notify(type, data) - a fact for the hub (None - none);
    configured() - True when hub.json already points the plugin at a gallery (no question then)."""

    def __init__(self, links, fetch, notify=None, defaults=DEFAULTS, configured=None):
        self.links, self.fetch, self.notify, self.defaults = links, fetch, notify, defaults
        self.configured = configured or (lambda: False)
        self.watch = True   # a download nobody sits on is watched: the owner is told when it is over; tests switch it off
        self.lock = threading.Lock()

    # --- the start ---

    def startup(self):
        """-> "seeded" (the first time: the links were put), "" otherwise. Nothing is downloaded here."""
        first = not self.links.seeded
        put = self.links.seed([linkmem.canon(u) for u in self.defaults]) if first else []
        if self.links.first == "" and first and put:
            self.links.set_first("config" if self.configured() else "pending")
        return "seeded" if first and put else ""

    # --- the question of the first start ---

    def facts(self):
        """What the question says: the sources, how many of them the downloader reads, the size and the time."""
        urls = [linkmem.canon(u) for u in self.defaults]
        return {**firstrun.FACTS, "sources": len(urls), "ready": sum(1 for u in urls if sources.for_url(u)), "links": urls, "agents": list(firstrun.AGENTS)}

    def question(self):
        """The question while it waits for the answer, otherwise None."""
        return self.facts() if self.links.first == "pending" else None

    def to_post(self):
        """The question that is to go to Telegram (asked and not posted yet) -> the facts, else None. mark_posted() after it went."""
        return self.facts() if self.links.first == "pending" and not self.links.ask_posted else None

    def mark_posted(self):
        self.links.set_ask_posted(True)

    def answer(self, choice, via="page"):
        """The owner answered: yes - the links by default are downloaded now as they are; no / settings - nothing is downloaded ("settings" is for the
        one who goes to change it in the tab). Answered already - nothing happens. Answered on the page, the Telegram post is erased
        (telegram.unpost); a press in Telegram settles its post itself. -> the answer: "yes" | "no" | "settings" | "" (it was not asked)."""
        if choice not in firstrun.CHOICES or self.links.first != "pending":
            return self.links.first if self.links.first in firstrun.CHOICES else ""
        self.links.set_first(choice)
        if choice == "yes":
            urls = [x["url"] for x in self.links.items() if x["default"]]
            if urls and self.fetch.start(urls, compress=False) and self.watch:
                threading.Thread(target=self._watch, daemon=True).start()
        if via == "page" and self.links.ask_posted and self.notify:
            self.notify("telegram.unpost", {"ref": firstrun.REF})
        return choice

    def by_hand(self):
        """The owner started a download in the settings tab while the question waited: it is answered (he is in the settings already)."""
        if self.links.first == "pending":
            self.links.set_first("settings")
            if self.links.ask_posted and self.notify:
                self.notify("telegram.unpost", {"ref": firstrun.REF})

    def again(self):
        """The settings tab asks the question once more (and Telegram gets it again)."""
        self.links.set_first("pending")

    def _watch(self):
        self.fetch.join(timeout=24 * 3600)
        self.finished()

    def finished(self):
        """The background download is over: one fact to the owner."""
        st = self.fetch.status()
        if not self.notify or st["state"] not in ("done", "error", "stopped"):
            return
        lang = _lang()
        title, text = NOTE[lang]
        failed = max(st["done"] - st["added"], 0)
        extra = EXTRA[lang].format(m=failed) if failed else ""
        self.notify("owner.notify", {"id": NOTE_ID, "title": title.format(n=st["added"]), "text": text.format(n=st["added"], extra=extra), "urgency": "later", "asked": True})

    # --- what the page shows ---

    def status(self):
        rows = []
        for it in self.links.items():
            site = sources.for_url(it["url"])
            rows.append({**it, "site": site.name if site else ""})
        return {"links": rows, "first": self.links.first, "firstrun": self.question(), "fetch": self.fetch.status(), "ffmpeg": bool(self.fetch.ffmpeg())}

    # --- what the page asks for ---

    def act(self, body):
        """-> (http status, answer). The answer carries "error" when it is a refusal."""
        action = body.get("action")
        url = linkmem.canon(body.get("url")) if isinstance(body.get("url"), str) else ""
        if action == "add":
            if not url.startswith(("http://", "https://")) or len(url) > linkmem.LINK_MAX:
                return 400, {"error": "bad_link"}
            if len(self.links.urls()) >= linkmem.LINKS_MAX:
                return 400, {"error": "too_many"}
            self.links.add(url)
            return 200, {"link": url, "site": (sources.for_url(url) or sources.Site()).name}
        if action == "remove":   # only the link: what it brought stays in the gallery
            self.links.remove(url)
            return 200, {"link": url}
        if action in ("plan", "start"):
            urls = [u for u in body.get("urls", []) if isinstance(u, str)] if isinstance(body.get("urls"), list) else self.links.urls()
            urls = [linkmem.canon(u) for u in urls if linkmem.canon(u).startswith(("http://", "https://"))][:linkmem.LINKS_MAX]
            if not urls:
                return 400, {"error": "no_links"}
            if action == "plan":
                return 200, self.fetch.plan(urls)
            self.by_hand()
            if not self.fetch.start(urls, compress=bool(body.get("compress"))):
                return 409, {"error": "busy"}
            if self.watch:
                threading.Thread(target=self._watch, daemon=True).start()
            return 200, {"started": True, "compress": bool(body.get("compress")) and bool(self.fetch.ffmpeg())}
        if action == "stop":
            self.fetch.stop()
            return 200, {"stopping": True}
        if action == "firstrun":
            if body.get("choice") == "again":
                self.again()
                return 200, {"first": self.links.first}
            if body.get("choice") not in firstrun.CHOICES:
                return 400, {"error": "choice"}
            return 200, {"first": self.answer(body["choice"])}
        return 400, {"error": "action"}
