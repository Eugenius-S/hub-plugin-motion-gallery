// Hub Motion Gallery: put a tag into the input of a session chat at the cursor, send nothing; and, when the owner sends,
// add what the tags stand for under the message.
// The page's input is a plain <textarea> (there are no chips in the middle of a text), so a tag is the text "(Name)": it is
// deleted like any text. The prompt, the video and the preview of every tag that is still in the text travel with the message:
// they are added a moment before the page reads the input and taken back at once if the input was not cleared (not sent).
import { REFS_MARK, insertAt, stripRefs, usedRefs, withRefs } from "./lib.js";

// `text` at the cursor (the selection is replaced); the page learns of it by the input event. -> false when the form has no input
export function insertTag(form, text) {
  const ta = form?.querySelector("textarea");
  if (!ta || !text) return false;
  const r = insertAt(ta.value, ta.selectionStart, ta.selectionEnd, text);
  ta.value = r.value;
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  ta.setSelectionRange?.(r.pos, r.pos);
  ta.focus();
  return true;
}

// tags that belong to an input: WeakMap textarea -> Map tag -> {prompt, video, preview, slug}
const registry = new WeakMap();
export function tagsOf(ta, create = false) {
  let m = registry.get(ta);
  if (!m && create) registry.set(ta, (m = new Map()));
  return m;
}

// the message is about to be read by the page: its refs go under the text - only when the owner agreed (`allowed`). true - something was added
export function attachRefs(ta, allowed = false) {
  if (!allowed) return false;
  const tags = tagsOf(ta);
  if (!tags?.size) return false;
  const entries = usedRefs(stripRefs(ta.value), tags);
  if (!entries.length) return false;
  ta.value = withRefs(ta.value, entries);
  return true;
}

// the message was not sent (the page kept the text): the refs come off the input again
export function detachRefs(ta) {
  const clean = stripRefs(ta.value);
  if (clean !== ta.value) ta.value = clean;
}

// for any composer of the page: capture handlers before the page's own (Enter, the send button, a form submit).
// `allowed()` is asked at the moment of sending: without it nothing is added. Idempotent: attachRefs twice gives one block. Returns the function that takes the handlers off.
export function interceptSend(doc = document, allowed = () => false) {
  const forTextarea = (t) => (t && t.tagName === "TEXTAREA" ? t : null);
  const prepare = (ta) => {
    if (!ta || !attachRefs(ta, allowed())) return;
    setTimeout(() => { if (ta.value.includes("\n\n")) detachRefs(ta); }, 0);   // sent: the page has emptied it already
  };
  const onKey = (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) prepare(forTextarea(e.target)); };
  const onSubmit = (e) => prepare(e.target?.querySelector?.("textarea"));
  const onClick = (e) => {
    const b = e.target?.closest?.("form button[type=submit], form .send");
    if (b) prepare(b.closest("form").querySelector("textarea"));
  };
  doc.addEventListener("keydown", onKey, true);
  doc.addEventListener("submit", onSubmit, true);
  doc.addEventListener("click", onClick, true);
  return () => { doc.removeEventListener("keydown", onKey, true); doc.removeEventListener("submit", onSubmit, true); doc.removeEventListener("click", onClick, true); };
}

// the input of the chat that is open now: the composer form with a textarea that is on the page; null while it is not there
export function openComposer(doc = document) {
  const forms = [...doc.querySelectorAll("form.composer")].filter((f) => f.querySelector("textarea") && f.getClientRects().length);
  return forms[forms.length - 1] || null;
}

// wait (up to `ms`) for the composer of the session chat that was just opened
export function waitComposer(ok, ms = 4000, doc = document) {
  return new Promise((done) => {
    const t0 = Date.now();
    (function tick() {
      const f = ok() ? openComposer(doc) : null;
      if (f) return done(f);
      if (!ok() || Date.now() - t0 > ms) return done(null);
      setTimeout(tick, 80);
    })();
  });
}
