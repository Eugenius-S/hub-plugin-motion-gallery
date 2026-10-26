import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { baseLang, makeT, pick, setLangSource } from "../i18n.js";

const dir = new URL("..", import.meta.url);
const src = (f) => readFileSync(new URL(f, dir), "utf8");

// the STR table of main.js, read as text (main.js itself needs a browser)
function table() {
  const m = src("main.js").match(/const STR = (\{[\s\S]*?\n\});/);
  assert.ok(m, "STR not found in main.js");
  return new Function(`return (${m[1]})`)();
}

test("en and ru have the same keys, nothing empty", () => {
  const { en, ru } = table();
  assert.deepEqual(Object.keys(ru).sort(), Object.keys(en).sort());
  for (const t of [en, ru]) for (const [k, v] of Object.entries(t)) assert.ok(v && String(v).trim(), k);
});

test("every key used in the code exists", () => {
  const { en } = table();
  const used = new Set();
  for (const f of ["main.js", "gallery.js", "attach.js"]) for (const m of src(f).matchAll(/\btr\("(\w+)"/g)) used.add(m[1]);
  for (const k of used) assert.ok(k in en, `tr("${k}") has no string`);
});

test("Cyrillic only in STR.ru (and manifest strings)", () => {
  const stripped = src("main.js").replace(/\n  ru: \{[\s\S]*?\n  \},\n\};/, "");
  for (const f of ["gallery.js", "lib.js", "insert.js", "attach.js", "i18n.js"]) assert.ok(!/[А-Яа-яЁё]/.test(src(f)), f);
  assert.ok(!/[А-Яа-яЁё]/.test(stripped), "main.js outside STR.ru");
});

test("the language is read at use time, any other language falls back to English", () => {
  const STR = { en: { a: "A {n}" }, ru: { a: "Я {n}" } };
  let lang = "en";
  setLangSource(() => lang);
  const tr = makeT(STR);
  assert.equal(tr("a", { n: 1 }), "A 1");
  lang = "ru-RU";
  assert.equal(tr("a", { n: 2 }), "Я 2");
  lang = "de";
  assert.equal(tr("a", { n: 3 }), "A 3");
  lang = "__proto__";
  assert.equal(tr("a", { n: 4 }), "A 4");
  assert.equal(tr("nope"), "nope");
  assert.equal(tr("a", { x: 1 }), "A {n}");
  assert.equal(baseLang("RU-ru"), "ru");
  assert.equal(pick(STR, "constructor"), "en");
});
