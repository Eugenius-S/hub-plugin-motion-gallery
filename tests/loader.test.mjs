import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const el = (tag, cls) => ({ tag, className: cls, style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } });

test("the runner is the plugin's own APNG; reduced motion gets a still PNG of the same icon", async () => {
  globalThis.matchMedia = () => ({ matches: false });
  const { runner } = await import("../loader.js");
  const a = runner(el, 56);   // a caller may still ask for another size
  assert.match(a.src, /\/loader\/runner-anim.png$/);
  assert.equal(a.style.width, "56px");
  assert.equal(a.attrs["aria-hidden"], "true");
  globalThis.matchMedia = () => ({ matches: true });
  assert.match(runner(el, 48).src, /\/loader\/runner\.png$/);
});

test("by default the runner is as small as the palette icon of Hub Design (20 px): under the list, on a card, in the lightbox", async () => {
  globalThis.matchMedia = () => ({ matches: false });
  const { runner, RUNNER_PX } = await import("../loader.js");
  assert.equal(RUNNER_PX, 20);
  assert.equal(runner(el).style.width, "20px");
  for (const f of ["../gallery.js", "../lightbox.js"]) {
    const src = readFileSync(new URL(f, import.meta.url), "utf8");
    assert.ok(!/runner\(el, \d+\)/.test(src), f + " takes the default size");
  }
});

test("both files are in the plugin and are PNGs; the animated one has frames (acTL)", () => {
  const apng = readFileSync(new URL("../loader/runner-anim.png", import.meta.url));
  const png = readFileSync(new URL("../loader/runner.png", import.meta.url));
  for (const b of [apng, png]) assert.equal(b.subarray(1, 4).toString(), "PNG");
  assert.ok(apng.includes("acTL"));
  assert.ok(!png.includes("acTL"));
  assert.ok(existsSync(new URL("../loader/runner.png", import.meta.url)));
});

test("no foreign address is fetched from the page", () => {
  const src = readFileSync(new URL("../loader.js", import.meta.url), "utf8");
  assert.ok(!/https?:\/\//.test(src.replace(/^\/\/.*$/gm, "")));
});
