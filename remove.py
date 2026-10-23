"""Hub Motion Gallery: taking one example out of gallery.json (pure functions, no files or network here).

take_out(raw, slug, slug_of) -> (new_raw, files) or None when the slug is not in the list:
  new_raw - gallery.json without that entry (the other entries and the other keys stay as they were);
  files   - the media paths (relative to the gallery) that only this entry used: video, preview, poster.
An entry whose media is a link (http/https) or that has no value gets the files the folder layout gives it
(videos/<slug>.*, previews/<slug>.*, posters/<slug>.*); a path that is also used by another entry stays.
"""
import re

KINDS = (("video", "videos", (".mp4", ".webm", ".mov")),
         ("preview", "previews", (".mp4", ".webm", ".mov")),
         ("poster", "posters", (".jpg", ".jpeg", ".png", ".webp")))


def clean(value):
    """A path inside the gallery, or "": links, empty values and anything that climbs out of the folder are not files."""
    v = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not v or re.match(r"^[a-z][a-z0-9+.-]*:", v, re.I) or any(p in ("..", "") for p in v.split("/")):
        return ""
    return v


def paths_of(row, slug):
    """The media paths of one entry: what it names itself, else the paths of the folder layout."""
    out = []
    for key, folder, exts in KINDS:
        raw = row.get(key)
        if isinstance(raw, str) and re.match(r"^https?://", raw.strip(), re.I):
            continue   # lives elsewhere: not ours to delete
        one = clean(raw)
        out += [one] if one else [f"{folder}/{slug}{e}" for e in exts]
    return list(dict.fromkeys(out))


def take_out(raw, slug, slug_of):
    rows = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return None
    at = next((i for i, r in enumerate(rows) if isinstance(r, dict) and slug_of(r) == slug), -1)
    if at < 0:
        return None
    rest = rows[:at] + rows[at + 1:]
    used = set()
    for r in rest:
        if isinstance(r, dict):
            used.update(clean(r.get(k)) for k, _, _ in KINDS)
    files = [p for p in paths_of(rows[at], slug) if p not in used]
    return ({**raw, "items": rest} if isinstance(raw, dict) else rest), files
