import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const rd = (f) => readFileSync(new URL("../" + f, import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("the gallery button in the input is an empty mask span, so navicon.css can animate it", () => {
  const main = rd("main.js");
  assert.match(main, /<span class="mg-oi" aria-hidden="true"><\/span>/);
  assert.match(main, /hub\.addStyle\("navicon\.css"\)/);
});

test("navicon.css: the outline/filled layers and the gradient sweep cover the gallery button only, not the menu icon; reduced motion is static", () => {
  const css = rd("navicon.css");
  assert.match(css, /\.mg-open \.mg-oi/);
  assert.doesNotMatch(css, /\.srow|\.ext-icon|mgi-resume/);   // the menu icon hovers like every other item
  assert.match(css, /\.mg-open:is\(:hover, :focus-visible, \.on\)/);   // hover, focus and the open gallery
  assert.match(css, /icon-filled\.svg/);
  assert.match(css, /radial-gradient\(circle closest-side at 50% 50%/);   // soft-edged rings from the center
  for (const k of [1, 2, 3]) {   // three rings on water, each with its own registered radius, shifted in time
    assert.match(css, new RegExp(`@property --mgi-r${k} \{ syntax: "<percentage>"`));
    assert.match(css, new RegExp(`@keyframes mgi-ring${k} \{ from \{ --mgi-r${k}: 0%; \} to \{ --mgi-r${k}: 100%; \} \}`));
  }
  assert.match(css, /cubic-bezier\(\.2, \.6, \.3, 1\)/);   // ease-out: fast from the center, slow at the edge
  assert.match(css, /--mgi-pink: light-dark\(#e01a7f, #ff2e93\)/);   // saturated, not pastel
  assert.doesNotMatch(css, /linear-gradient|mgi-sweep/);
  const rm = css.slice(css.indexOf("prefers-reduced-motion"));
  assert.match(rm, /animation: none/);
  assert.match(rm, /transform: none/);
});

test("icon-filled.svg is the filled twin of icon.svg: same 24 px frame, the triangle cut out of the circle", () => {
  const f = rd("icon-filled.svg");
  assert.match(f, /viewBox="0 0 24 24"/);
  assert.match(f, /fill-rule="evenodd"/);
  assert.match(rd("icon.svg"), /viewBox="0 0 24 24"/);
});

test("the menu icon is not ours any more: no navicon.js, no keepRings (0.7.1)", () => {
  const main = rd("main.js");
  assert.doesNotMatch(main, /keepRings|navicon\.js/);
  assert.ok(!existsSync(new URL("../navicon.js", import.meta.url)));
});
