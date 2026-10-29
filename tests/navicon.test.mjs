import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const rd = (f) => readFileSync(new URL("../" + f, import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("the gallery button in the input is a one-color mask icon: no animation sheet of ours", () => {
  const main = rd("main.js");
  assert.match(main, /<span class="mg-oi" aria-hidden="true"><\/span>/);
  assert.doesNotMatch(main, /navicon/);
  assert.ok(!existsSync(new URL("../navicon.css", import.meta.url)));
  assert.ok(!existsSync(new URL("../icon-filled.svg", import.meta.url)));
});

test("the icon is drawn by a currentColor mask and nothing else: no layers, rings, gradients or scale on hover", () => {
  const css = rd("style.css");
  const i = css.indexOf(".mg-open .mg-oi {");
  assert.ok(i > 0);
  const rule = css.slice(i, css.indexOf("}", i));
  assert.match(rule, /background: currentColor/);
  assert.match(rule, /mask: url\("icon\.svg"\)/);
  assert.doesNotMatch(css, /mgi-|@property|radial-gradient|\.mg-oi:?:(before|after)/);
  assert.match(rd("icon.svg"), /viewBox="0 0 24 24"/);
});

test("the menu icon is not ours: no navicon.js, no keepRings (0.7.1)", () => {
  const main = rd("main.js");
  assert.doesNotMatch(main, /keepRings|navicon\.js/);
  assert.ok(!existsSync(new URL("../navicon.js", import.meta.url)));
});
