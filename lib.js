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
  const hay = norm([item.title, item.prompt, item.slug, item.author, item.category, (item.tags || []).join(" "), (item.sources || []).join(" ")].join("\n"));
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
// (a skill entry has no prompt: its description, the install commands and the repo)
export function chatText(item) {
  const p = String(item?.prompt || "").trim();
  if (p || !item?.skill) return p;
  return [item.skill.desc, item.skill.install, item.skill.repo].filter(Boolean).join("\n\n");
}

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

// ---- tags: a click on a card puts "(Name)" at the cursor of the chat input; the prompt, the video and the preview of every
// tag still in the text are added under the message when it is sent (see main.js) and never stay in the input.
export const REFS_MARK = "Refs from Motion Gallery";
// said before the prompt of every example: it was written for another task, so the model takes from it what this task needs
export const REF_NOTE = "Note: this reference was made for another task. Take the part we need and carry it over; do not copy it whole.";

// the tag of an example in the input: "(Title)"; a second example with the same title becomes "(Title 2)", "(Title 3)"…
// `taken` is Map tag -> slug of the tags this input already holds; the same example always gets its own tag back
export function tagFor(item, taken) {
  const name = String(item?.title || item?.slug || "example").replace(/\s+/g, " ").trim();
  for (let n = 1; ; n++) {
    const tag = `(${n > 1 ? `${name} ${n}` : name})`;
    if (!taken.has(tag) || taken.get(tag) === item.slug) return tag;
  }
}

// `text` into `value` over the selection [start, end]: a space is added where it would stick to a word; -> {value, pos}
export function insertAt(value, start, end, text) {
  const s = Math.max(0, Math.min(Number.isInteger(start) ? start : value.length, value.length));
  const e = Math.max(s, Math.min(Number.isInteger(end) ? end : s, value.length));
  const before = s > 0 && !/\s/.test(value[s - 1]) ? " " : "";
  const after = e < value.length && /\s/.test(value[e]) ? "" : " ";
  const put = before + text + after;
  return { value: value.slice(0, s) + put + value.slice(e), pos: s + put.length };
}

// the entries (for withRefs) of the tags that are still in the text, each example once, in the order of the text
export function usedRefs(value, tags) {
  const seen = new Set(), out = [];
  const found = [...tags].map(([tag, ref]) => ({ tag, ref, at: value.indexOf(tag) })).filter((x) => x.at >= 0).sort((a, b) => a.at - b.at);
  for (const { tag, ref } of found) if (!seen.has(tag)) { seen.add(tag); out.push({ tag, ...ref }); }
  return out;
}

// the text under the message: for every tag - its prompt and the links to the video and the preview
export function refsBlock(entries) {
  return REFS_MARK + " (the tags in the message above stand for these examples):\n\n" + entries.map((r) =>
    [r.tag, r.prompt && REF_NOTE, r.prompt && "Prompt: " + r.prompt, r.video && "Video: " + r.video, r.preview && "Preview: " + r.preview, r.source && "Source: " + r.source].filter(Boolean).join("\n")).join("\n\n");
}

// the message with its refs (an old block is replaced, so doing it twice is the same as once)
export function stripRefs(value) {
  const at = value.indexOf("\n\n" + REFS_MARK);
  return at < 0 ? value : value.slice(0, at);
}
export function withRefs(value, entries) {
  const base = stripRefs(value);
  return entries.length ? base.replace(/\s+$/, "") + "\n\n" + refsBlock(entries) : base;
}

// the address of a process answer: relative paths ("/f/…") belong to the process, URLs stay as they are
export const mediaUrl = (base, src) => (!src ? "" : /^https?:\/\//i.test(src) ? src : base + src);

// the lightbox: the index after a step, stopping at the ends (like a photo viewer); a missing index - the first
export function stepIndex(i, delta, n) {
  if (!(n > 0)) return -1;
  const at = Number.isInteger(i) && i >= 0 && i < n ? i : 0;
  return Math.min(n - 1, Math.max(0, at + delta));
}

// what the lightbox plays: the full video, else the preview; "" - the entry has no video at all
export const lightVideo = (item) => item?.video || item?.preview || "";

// ---- agents Motion Gallery works with: without them the examples have nobody to turn into a script or a video. One list (the same names as
// firstrun.AGENTS in firstrun.py); installed from the specialists catalog by a message to the hub (`specialists install <name>`).
export const NEEDED = ["screenwriter", "moviemaker"];
export const ASK_TTL = 30 * 60 * 1000;   // "asked the hub" lasts this long, then "Install" again
export const installText = (name) => `specialists install ${name}`;
export const hubName = (sessions) => ((sessions || []).find((s) => s.kind === "hub") || {}).name || "hub";
// who is missing from the hub: [{name, state}] with state "ask" (can be asked) or "wait" (asked, waiting - until the session appears in the snapshot)
export function lacking(sessions, asked = {}, now = Date.now(), needed = NEEDED) {
  const have = new Set((sessions || []).filter((s) => s.kind !== "hub").map((s) => s.name));
  return needed.filter((n) => !have.has(n)).map((name) => ({ name, state: asked[name] && now - asked[name] < ASK_TTL ? "wait" : "ask" }));
}
