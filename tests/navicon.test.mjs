import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const rd = (f) => readFileSync(new URL("../" + f, import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("the gallery button in the input is an empty mask span, so navicon.css can animate it like the menu icon", () => {
  const main = rd("main.js");
  assert.match(main, /<span class="mg-oi" aria-hidden="true"><\/span>/);
  assert.match(main, /hub\.addStyle\("navicon\.css"\)/);
});

test("navicon.css: the outline/filled layers and the gradient sweep cover the menu icon and the gallery button; reduced motion is static", () => {
  const css = rd("navicon.css");
  assert.match(css, /\.mg-open \.mg-oi/);
  assert.match(css, /\.srow\.nav \.ext-icon\[style\*="motion-gallery\/icon\.svg"\]/);
  assert.match(css, /:is\(\.srow\.nav, \.mg-open\):is\(:hover, :focus-visible, \.on\)/);   // hover, focus and the open gallery
  assert.match(css, /icon-filled\.svg/);
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
