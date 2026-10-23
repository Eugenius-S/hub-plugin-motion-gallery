"""Hub Motion Gallery: what the downloader can read. A source is a site whose pages describe a video with schema.org
(a VideoObject in ld+json: the video, the poster, the author, the length) and carry the prompt in the page.

  skillry.dev      /ai-videos[/<model>[/<item>]]   the prompt is in a <pre>
  prompt-motion.com  /<author>-<hex6>              the prompt is in the page data of the framework, tags are /tags/<tag> links
  claude-motion.com  /gallery[/<item>]             the prompt is in a <pre>

A link to another site (remotion.dev, a GitHub repository ...) has no reader yet: for_url() gives None and the settings say so.
The reader works on text it is given (get(url) -> str), so tests feed it saved pages."""
import html
import json
import re
from urllib.parse import urljoin, urlparse

MODEL_PAGES = 3   # skillry: how many model list pages one link may open


def _ld(page):
    """Every ld+json object of the page (a @graph is opened)."""
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for x in d.get("@graph", [d]) if isinstance(d, dict) else d if isinstance(d, list) else []:
            if isinstance(x, dict):
                out.append(x)
    return out


def _video(page):
    return next((d for d in _ld(page) if d.get("@type") == "VideoObject" and isinstance(d.get("contentUrl"), str)), None)


def _seconds(iso):
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", str(iso or ""))
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0) if m else 0


def _pre(page):
    m = re.search(r"<pre[^>]*>(.*?)</pre>", page, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def _rsc_prompt(page):
    """The prompt in the data a Next.js page carries (self.__next_f.push chunks): the first "prompt":"..." string."""
    try:
        text = "".join(json.loads(c) for c in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', page))
    except ValueError:
        return ""
    i = text.find('"prompt":"')
    if i < 0:
        return ""
    try:
        return json.JSONDecoder().raw_decode(text[i + len('"prompt":'):])[0].strip()
    except ValueError:
        return ""


def _hrefs(page, pattern):
    seen = []
    for h in re.findall(r'href="([^"#?]+)"', page):
        if re.fullmatch(pattern, h) and h not in seen:
            seen.append(h)
    return seen


def _slug(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")[:100]


class Site:
    name = ""
    item = ""       # regex of the path of an item page
    tags = False

    def is_item(self, url):
        return bool(re.fullmatch(self.item, urlparse(url).path.rstrip("/")))

    def list(self, url, get):
        """The item pages a link leads to (a link to one item is that item)."""
        if self.is_item(url):
            return [url]
        return [urljoin(url, h) for h in _hrefs(get(url), self.item)]

    def slug(self, url):
        return f"{self.name.split('.')[0]}-{_slug(urlparse(url).path.rstrip('/').rsplit('/', 1)[-1])}"

    def prompt(self, page):
        return _pre(page)

    def title(self, v, prompt):
        return html.unescape(str(v.get("name") or ""))[:200]

    def read(self, url, page):
        """One item page -> the entry the downloader stores, or None when the page has no video."""
        v = _video(page)
        if not v:
            return None
        who = v.get("author") or v.get("creator") or {}
        thumbs = v.get("thumbnailUrl")
        thumbs = [thumbs] if isinstance(thumbs, str) else [t for t in (thumbs or []) if isinstance(t, str)]
        poster = next((t for t in thumbs if not re.search(r"/og[.\w]*\.(jpg|png)", t)), thumbs[0] if thumbs else "")
        prompt = self.prompt(page)
        tags = [html.unescape(t) for t in re.findall(r'href="/tags/([^"]+)"', page)] if self.tags else []
        return {"slug": self.slug(url), "title": self.title(v, prompt), "author": html.unescape(str((who or {}).get("name") or ""))[:200],
                "prompt": prompt, "tags": list(dict.fromkeys(tags))[:12], "seconds": _seconds(v.get("duration")), "page": url, "source": self.name,
                "video_url": v["contentUrl"], "poster_url": poster}


class Skillry(Site):
    name = "skillry.dev"
    item = r"/ai-videos/[\w.-]+/[\w.-]+"

    def list(self, url, get):
        if self.is_item(url):
            return [url]
        page = get(url)
        found = _hrefs(page, self.item)
        if not found:   # the hub of the models: open the first model pages
            for h in _hrefs(page, r"/ai-videos/[\w.-]+")[:MODEL_PAGES]:
                found += [x for x in _hrefs(get(urljoin(url, h)), self.item) if x not in found]
        return [urljoin(url, h) for h in found]

    def title(self, v, prompt):   # the page title is "Opus 5.5 video by @name": the start of the prompt says more
        t = re.sub(r"\s+", " ", prompt)[:60].strip()
        return (t + "…" if len(prompt) > 60 else t) or super().title(v, prompt)


class PromptMotion(Site):
    name = "prompt-motion.com"
    item = r"/[\w.]+-[0-9a-f]{6}"
    tags = True

    def list(self, url, get):
        if self.is_item(url):
            return [url]
        return [urljoin(url, h) for h in _hrefs(get(url), self.item)]

    def prompt(self, page):
        return _rsc_prompt(page) or _pre(page)


class ClaudeMotion(Site):
    name = "claude-motion.com"
    item = r"/gallery/[\w.-]+"

    def list(self, url, get):
        if self.is_item(url):
            return [url]
        if urlparse(url).path.rstrip("/") in ("", "/"):
            url = urljoin(url, "/gallery")
        return [urljoin(url, h) for h in _hrefs(get(url), self.item)]


SITES = {s.name: s for s in (Skillry(), PromptMotion(), ClaudeMotion())}


def for_url(url):
    """The reader of a link, or None: no reader for this site yet."""
    h = urlparse(url).netloc.lower()
    h = h[4:] if h.startswith("www.") else h
    return SITES.get(h)
