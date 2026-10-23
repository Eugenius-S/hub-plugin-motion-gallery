// Hub Motion Gallery: pure helpers (no DOM) - the entry list, filter, captions, what goes into the chat.
export const PORT_OFFSET = 12;   // the plugin process listens on hub page port + 12 (server.py)
export const processPort = (pagePort) => Number(pagePort || 8787) + PORT_OFFSET;

const norm = (s) => String(s || "").toLowerCase();

// "0:05" for 5 s, "1:20" for 80 s; unknown - ""
export function fmtDuration(sec) {
  const n = Math.round(Number(sec));
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}

// categories with counts, the biggest first (equal - by name)
export function categories(items) {
  const m = new Map();
  for (const i of items) if (i.category) m.set(i.category, (m.get(i.category) || 0) + 1);
  return [...m].map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
}

// sources (where the example comes from) with counts, the biggest first
export function sourceList(items) {
  const m = new Map();
  for (const i of items) for (const s of i.sources || []) m.set(s, (m.get(s) || 0) + 1);
  return [...m].map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
}

// links to the originals: [{source, url}] (an older entry has only post or page)
const isUrl = (u) => /^https?:\/\//i.test(u || "");
export function linksOf(item) {
  const l = (item?.links || []).filter((x) => x && isUrl(x.url));
  return l.length ? l : [item?.post, item?.page].filter(isUrl).map((url) => ({ source: "", url }));
}

// tags with counts, the most used first, at most `limit`
export function tagList(items, limit = 24) {
  const m = new Map();
  for (const i of items) for (const t of i.tags || []) m.set(t, (m.get(t) || 0) + 1);
  return [...m].map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n || a.name.localeCompare(b.name)).slice(0, limit);
}

// the entry matches the query (every word, in the prompt, slug, author, category, tags or sources), the category, the source and ALL chosen tags
export function matches(item, { q = "", category = "", tags = [], source = "" } = {}) {
  if (category && item.category !== category) return false;
  if (source && !(item.sources || []).includes(source)) return false;
  if (tags.length && !tags.every((t) => (item.tags || []).includes(t))) return false;
  const words = norm(q).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = norm([item.prompt, item.slug, item.author, item.category, (item.tags || []).join(" "), (item.sources || []).join(" ")].join("\n"));
  return words.every((w) => hay.includes(w));
}

export const filterItems = (items, f) => items.filter((i) => matches(i, f));

// "Category · Author" and the duration separately (it sits on the picture)
export const metaLine = (item) => [item.category, item.author].filter(Boolean).join(" · ");

// the first lines of a prompt for the card
export function excerpt(prompt, max = 140) {
  const s = String(prompt || "").replace(/\s+/g, " ").trim();
  return s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s;
}

// what goes into the chat input as text: the full prompt, nothing else
export const chatText = (item) => String(item?.prompt || "").trim();

// the session of an address "#/s/<name>"; anything else - ""
export function sessionOf(hash) {
  const m = String(hash || "").match(/^#\/s\/([^/?]+)/);
  if (!m) return "";
  try { return decodeURIComponent(m[1]); } catch { return ""; }
}

// session names for the "insert into" choice: the last opened first, then the rest in the snapshot order; no duplicates
export function targets(sessions, last) {
  const names = [...new Set((sessions || []).map((s) => s?.name).filter(Boolean))];
  return last && names.includes(last) ? [last, ...names.filter((n) => n !== last)] : names;
}

// a file name for the poster that goes with the message: <slug>.<ext by the mime>
const EXT = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif" };
export const posterName = (item, mime) => `${String(item.slug || "example").replace(/[^\w.-]/g, "-")}.${EXT[mime] || "jpg"}`;

// the address of a process answer: relative paths ("/f/…") belong to the process, URLs stay as they are
export const mediaUrl = (base, src) => (!src ? "" : /^https?:\/\//i.test(src) ? src : base + src);
