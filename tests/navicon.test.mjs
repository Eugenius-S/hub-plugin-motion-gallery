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

test("the page rebuilds the menu on every snapshot: navicon.js carries the ring phase and the hover look over to the new icon (0.4.5)", () => {
  const main = rd("main.js");
  assert.match(main, /import \{ keepRings \} from "\.\/navicon\.js"/);
  assert.match(main, /keepRings\(\);/);
  const js = rd("navicon.js");
  assert.match(js, /new MutationObserver/);                // sees the old icon go and the new one come
  assert.match(js, /addEventListener\("animationstart"/);   // the phase is read from, and set on, the rings
  assert.match(js, /\.startTime = carry\.start/);
  assert.match(js, /setAttribute\(RESUME/);
  const css = rd("navicon.css");
  // the resumed icon shows the hover look at once and without a transition (else the fill fades in again and bounces)
  assert.match(css, /\[data-mgi-resume\]::after \{ transition: none; \}/);
  assert.match(css, /\[data-mgi-resume\] \{ transform: scale\(1\.12\); \}/);
  assert.match(css, /\[data-mgi-resume\]::before \{ opacity: 0; \}/);
  assert.match(css, /\[data-mgi-resume\]::after \{\s*opacity: 1;/);
  const rm = css.slice(css.indexOf("prefers-reduced-motion"));
  assert.match(rm, /\[data-mgi-resume\]::after \{ animation: none; \}/);   // reduced motion stays static for the resumed icon too
});
