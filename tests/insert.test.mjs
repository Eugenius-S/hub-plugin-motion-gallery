import { test } from "node:test";
import assert from "node:assert/strict";
import { attachRefs, detachRefs, insertTag, interceptSend, openComposer, tagsOf, waitComposer } from "../insert.js";

// no DOM in node: just enough of it
class FakeTA {
  constructor(value = "") { this.value = value; this.events = []; this.focused = false; this.sel = null; this.selectionStart = value.length; this.selectionEnd = value.length; this.tagName = "TEXTAREA"; }
  dispatchEvent(ev) { this.events.push(ev.type); return true; }
  focus() { this.focused = true; }
  setSelectionRange(a, b) { this.sel = [a, b]; this.selectionStart = a; this.selectionEnd = b; }
}
const form = (ta) => ({ querySelector: (s) => (s === "textarea" ? ta : null) });

test("insertTag: at the cursor, the page is told by input, the cursor goes after the tag", () => {
  const ta = new FakeTA("make like  now");
  ta.setSelectionRange(10, 10);
  assert.equal(insertTag(form(ta), "(A)"), true);
  assert.equal(ta.value, "make like (A) now");
  assert.deepEqual(ta.events, ["input"]);
  assert.deepEqual(ta.sel, [13, 13]);
  assert.ok(ta.focused);
  assert.equal(insertTag({ querySelector: () => null }, "(A)"), false);
  assert.equal(insertTag(null, "(A)"), false);
});

test("two tags: both prompts go with the message, a tag deleted from the text does not", () => {
  const ta = new FakeTA("");
  const tags = tagsOf(ta, true);
  tags.set("(One)", { slug: "1", prompt: "prompt one", video: "http://x/1.mp4" });
  tags.set("(Two)", { slug: "2", prompt: "prompt two", preview: "http://x/2-p.mp4" });
  tags.set("(Gone)", { slug: "3", prompt: "prompt gone" });
  insertTag(form(ta), "(One)");
  insertTag(form(ta), "(Two)");
  assert.equal(ta.value, "(One) (Two) ");
  assert.equal(attachRefs(ta, true), true);
  for (const must of ["(One) (Two)", "prompt one", "http://x/1.mp4", "prompt two", "http://x/2-p.mp4"]) assert.ok(ta.value.includes(must), must);
  assert.ok(!ta.value.includes("prompt gone"));
  assert.equal(attachRefs(ta, true), true);                 // twice: still one block
  assert.equal(ta.value.split("Refs from Motion Gallery").length, 2);
  detachRefs(ta);
  assert.equal(ta.value, "(One) (Two)");                    // not sent: the input is as the owner left it
  assert.equal(attachRefs(new FakeTA("no tags here")), false);
});

test("interceptSend: Enter and submit add the refs before the page reads the input, Shift+Enter does not, an unsent text gets them back", async () => {
  const handlers = {};
  const doc = { addEventListener: (t, f) => { handlers[t] = f; }, removeEventListener() {} };
  const off = interceptSend(doc, () => true);
  const ta = new FakeTA("(One) hi");
  tagsOf(ta, true).set("(One)", { slug: "1", prompt: "prompt one" });
  handlers.keydown({ key: "Enter", shiftKey: true, target: ta });
  assert.equal(ta.value, "(One) hi");
  handlers.keydown({ key: "Enter", shiftKey: false, target: ta });
  assert.ok(ta.value.includes("prompt one"));
  await new Promise((r) => setTimeout(r, 20));              // the page did not clear the input: not sent
  assert.equal(ta.value, "(One) hi");
  handlers.submit({ target: { querySelector: () => ta } });
  assert.ok(ta.value.includes("prompt one"));
  ta.value = "";                                            // the page cleared it: sent, the block went with it
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(ta.value, "");
  assert.equal(typeof off, "function");
});

test("openComposer: the last visible composer with a textarea", () => {
  const f = (vis, ta = true) => ({ querySelector: () => (ta ? {} : null), getClientRects: () => (vis ? [1] : []) });
  const hidden = f(false), a = f(true), b = f(true), bare = f(true, false);
  const doc = { querySelectorAll: () => [a, hidden, b, bare] };
  assert.equal(openComposer(doc), b);
  assert.equal(openComposer({ querySelectorAll: () => [hidden] }), null);
});

test("waitComposer: finds the form when it appears, gives up when the chat changed or on time", async () => {
  const f = { querySelector: () => ({}), getClientRects: () => [1] };
  let shown = false;
  const doc = { querySelectorAll: () => (shown ? [f] : []) };
  setTimeout(() => { shown = true; }, 150);
  assert.equal(await waitComposer(() => true, 2000, doc), f);
  assert.equal(await waitComposer(() => false, 2000, doc), null);   // the owner went elsewhere
  shown = false;
  const t0 = Date.now();
  assert.equal(await waitComposer(() => true, 200, doc), null);     // never appeared
  assert.ok(Date.now() - t0 < 1500);
});

test("without the owner's consent nothing is added: attachRefs and interceptSend leave the message as it is", async () => {
  const ta = new FakeTA("(One) hi");
  tagsOf(ta, true).set("(One)", { slug: "1", prompt: "prompt one" });
  assert.equal(attachRefs(ta), false);
  assert.equal(attachRefs(ta, false), false);
  assert.equal(ta.value, "(One) hi");
  const handlers = {};
  const doc = { addEventListener: (t, f) => { handlers[t] = f; }, removeEventListener() {} };
  interceptSend(doc);                                       // no consent given: off
  handlers.keydown({ key: "Enter", shiftKey: false, target: ta });
  handlers.submit({ target: { querySelector: () => ta } });
  assert.equal(ta.value, "(One) hi");
  let on = false;
  const doc2 = { addEventListener: (t, f) => { handlers[t] = f; }, removeEventListener() {} };
  interceptSend(doc2, () => on);                            // the consent is read at the moment of sending
  handlers.keydown({ key: "Enter", shiftKey: false, target: ta });
  assert.equal(ta.value, "(One) hi");
  on = true;
  handlers.keydown({ key: "Enter", shiftKey: false, target: ta });
  assert.ok(ta.value.includes("prompt one"));
});
