import { test } from "node:test";
import assert from "node:assert/strict";
import { appendText, insertInto, openComposer, pasteFile, waitComposer } from "../insert.js";

// no DOM in node: just enough of it
class FakeTA {
  constructor(value = "") { this.value = value; this.events = []; this.focused = false; this.pasted = []; this.sel = null; }
  dispatchEvent(ev) {
    this.events.push(ev.type);
    if (ev.type === "paste") this.pasted.push(...ev.clipboardData.files);
    return true;
  }
  focus() { this.focused = true; }
  setSelectionRange(a, b) { this.sel = [a, b]; }
}
const form = (ta) => ({ querySelector: (s) => (s === "textarea" ? ta : null) });

function fakeClipboard({ keepFiles = true } = {}) {
  globalThis.DataTransfer = class { constructor() { this.files = []; this.items = { add: (f) => this.files.push(f) }; } };
  globalThis.ClipboardEvent = class { constructor(type, init) { this.type = type; this.clipboardData = keepFiles ? init.clipboardData : null; } };
}

test("appendText: after what is typed, on a new line; the page is told by input", () => {
  const ta = new FakeTA("hello");
  appendText(ta, "prompt");
  assert.equal(ta.value, "hello\nprompt");
  assert.deepEqual(ta.events, ["input"]);
  assert.deepEqual(ta.sel, [12, 12]);
  const t2 = new FakeTA("hello\n");
  appendText(t2, "p");
  assert.equal(t2.value, "hello\np");
  const t3 = new FakeTA("");
  appendText(t3, "p");
  assert.equal(t3.value, "p");
  const t4 = new FakeTA("keep");
  appendText(t4, "");
  assert.equal(t4.value, "keep");
  assert.deepEqual(t4.events, []);
});

test("insertInto: the picture as a paste, then the text; nothing is submitted", () => {
  fakeClipboard();
  const ta = new FakeTA("");
  const file = { name: "a.jpg" };
  assert.deepEqual(insertInto(form(ta), { text: "the prompt", file }), { file: true, text: true });
  assert.deepEqual(ta.events, ["paste", "input"]);
  assert.deepEqual(ta.pasted, [file]);
  assert.equal(ta.value, "the prompt");
  assert.ok(ta.focused);
});

test("insertInto: no picture - only the text, and it says so", () => {
  fakeClipboard();
  const ta = new FakeTA("");
  assert.deepEqual(insertInto(form(ta), { text: "t", file: null }), { file: false, text: true });
  assert.deepEqual(ta.events, ["input"]);
});

test("insertInto: a browser that drops clipboardData - the text still goes in", () => {
  fakeClipboard({ keepFiles: false });
  const ta = new FakeTA("");
  assert.deepEqual(insertInto(form(ta), { text: "t", file: { name: "a.jpg" } }), { file: false, text: true });
  assert.equal(ta.value, "t");
  assert.equal(pasteFile(ta, {}), false);
});

test("insertInto: no input in the form", () => {
  assert.deepEqual(insertInto({ querySelector: () => null }, { text: "t" }), { file: false, text: false });
  assert.deepEqual(insertInto(null, { text: "t" }), { file: false, text: false });
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
