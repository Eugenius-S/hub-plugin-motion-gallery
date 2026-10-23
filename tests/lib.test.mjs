import { test } from "node:test";
import assert from "node:assert/strict";
import { categories, chatText, excerpt, filterItems, fmtDuration, linksOf, matches, mediaUrl, metaLine, posterName, processPort, sessionOf, sourceList, tagList, targets } from "../lib.js";

const ITEMS = [
  { slug: "a-1", category: "Product", author: "Anna", tags: ["loop", "3d"], prompt: "A glossy bottle spins on a pedestal" },
  { slug: "b-2", category: "Kinetic type", author: "Boris", tags: ["type"], prompt: "Letters fly in\nand snap to a grid" },
  { slug: "c-3", category: "Product", author: "Carla", tags: ["3d"], prompt: "Sneaker unboxing, macro lens" },
];

test("processPort is the page port + 12, 8787 when unknown", () => {
  assert.equal(processPort("8787"), 8799);
  assert.equal(processPort(9000), 9012);
  assert.equal(processPort(""), 8799);
});

test("fmtDuration", () => {
  assert.equal(fmtDuration(5), "0:05");
  assert.equal(fmtDuration(80), "1:20");
  assert.equal(fmtDuration(6.5), "0:07");
  for (const bad of [0, -1, "x", null, undefined, NaN]) assert.equal(fmtDuration(bad), "");
});

test("categories and tags: counts, biggest first", () => {
  assert.deepEqual(categories(ITEMS), [{ name: "Product", n: 2 }, { name: "Kinetic type", n: 1 }]);
  assert.deepEqual(tagList(ITEMS).map((t) => t.name), ["3d", "loop", "type"]);
  assert.equal(tagList(ITEMS, 2).length, 2);
  assert.deepEqual(categories([{ slug: "x" }]), []);
});

test("filter: every word, any field, case-insensitive", () => {
  assert.deepEqual(filterItems(ITEMS, { q: "bottle" }).map((i) => i.slug), ["a-1"]);
  assert.deepEqual(filterItems(ITEMS, { q: "GRID letters" }).map((i) => i.slug), ["b-2"]);
  assert.deepEqual(filterItems(ITEMS, { q: "carla" }).map((i) => i.slug), ["c-3"]);
  assert.deepEqual(filterItems(ITEMS, { q: "kinetic" }).map((i) => i.slug), ["b-2"]);
  assert.deepEqual(filterItems(ITEMS, { q: "bottle grid" }), []);
  assert.equal(filterItems(ITEMS, { q: "  " }).length, 3);
});

test("filter: category and ALL chosen tags", () => {
  assert.deepEqual(filterItems(ITEMS, { category: "Product" }).map((i) => i.slug), ["a-1", "c-3"]);
  assert.deepEqual(filterItems(ITEMS, { tags: ["3d"] }).map((i) => i.slug), ["a-1", "c-3"]);
  assert.deepEqual(filterItems(ITEMS, { tags: ["3d", "loop"] }).map((i) => i.slug), ["a-1"]);
  assert.deepEqual(filterItems(ITEMS, { category: "Kinetic type", tags: ["3d"] }), []);
  assert.equal(matches({ slug: "z" }, { tags: ["x"] }), false);
});

test("captions", () => {
  assert.equal(metaLine(ITEMS[0]), "Product · Anna");
  assert.equal(metaLine({ author: "Anna" }), "Anna");
  assert.equal(metaLine({}), "");
  assert.equal(excerpt("a\n\n  b"), "a b");
  const long = excerpt("w ".repeat(200), 20);
  assert.ok(long.length <= 20 && long.endsWith("…"));
});

test("chatText is the full prompt, untouched inside", () => {
  assert.equal(chatText({ prompt: "  line1\nline2  " }), "line1\nline2");
  assert.equal(chatText({}), "");
  assert.equal(chatText(null), "");
});

test("sessionOf reads only #/s/<name>", () => {
  assert.equal(sessionOf("#/s/ads-1"), "ads-1");
  assert.equal(sessionOf("#/s/%D0%B0%D0%B1"), "аб");
  assert.equal(sessionOf("#/s/a/extra"), "a");
  assert.equal(sessionOf("#/x/motion-gallery"), "");
  assert.equal(sessionOf(""), "");
  assert.equal(sessionOf("#/s/%E0%A4%A"), "");
});

test("targets: the last opened first, no duplicates, unknown last ignored", () => {
  const s = [{ name: "a" }, { name: "b" }, { name: "c" }, { name: "b" }, {}];
  assert.deepEqual(targets(s, "c"), ["c", "a", "b"]);
  assert.deepEqual(targets(s, "zzz"), ["a", "b", "c"]);
  assert.deepEqual(targets(null, "a"), []);
});

test("posterName and mediaUrl", () => {
  assert.equal(posterName({ slug: "a b/c" }, "image/png"), "a-b-c.png");
  assert.equal(posterName({ slug: "x" }, "image/unknown"), "x.jpg");
  assert.equal(mediaUrl("http://h:1", "/f/a.mp4"), "http://h:1/f/a.mp4");
  assert.equal(mediaUrl("http://h:1", "https://cdn/x.jpg"), "https://cdn/x.jpg");
  assert.equal(mediaUrl("http://h:1", ""), "");
});

test("sources: counts, filter by one source, the source is searchable", () => {
  const items = [
    { slug: "a", sources: ["skillry", "remotion"], prompt: "x" },
    { slug: "b", sources: ["skillry"], prompt: "y" },
    { slug: "c", prompt: "z" },
  ];
  assert.deepEqual(sourceList(items), [{ name: "skillry", n: 2 }, { name: "remotion", n: 1 }]);
  assert.deepEqual(filterItems(items, { source: "skillry" }).map((i) => i.slug), ["a", "b"]);
  assert.deepEqual(filterItems(items, { source: "remotion" }).map((i) => i.slug), ["a"]);
  assert.deepEqual(filterItems(items, { q: "remotion" }).map((i) => i.slug), ["a"]);
  assert.deepEqual(filterItems(items, {}).length, 3);
});

test("linksOf: links first, an old post/page as a fallback, only http(s)", () => {
  assert.deepEqual(linksOf({ links: [{ source: "s", url: "https://e.com/1" }, { source: "bad", url: "javascript:1" }] }), [{ source: "s", url: "https://e.com/1" }]);
  assert.deepEqual(linksOf({ post: "https://e.com/p", page: "https://e.com/g" }), [{ source: "", url: "https://e.com/p" }, { source: "", url: "https://e.com/g" }]);
  assert.deepEqual(linksOf({ post: "ftp://x" }), []);
  assert.deepEqual(linksOf(null), []);
});
