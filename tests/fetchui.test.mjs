import { test } from "node:test";
import assert from "node:assert/strict";
import { setLangSource } from "../i18n.js";
import { LINKS_MAX, fmtSize, isRunning, parseLinks, percent, planText, problem, siteName, summary, STR as FSTR } from "../fetchui.js";
import { STR as QSTR, agentTitle, createFirstRun, sourceName } from "../firstrun.js";
import { ASK_TTL, NEEDED, hubName, installText, lacking } from "../lib.js";

const GB = 1024 ** 3;
const MB = 1024 ** 2;

test("fetchui and firstrun: en and ru have the same keys, nothing empty", () => {
  for (const S of [FSTR, QSTR]) {
    assert.deepEqual(Object.keys(S.ru).sort(), Object.keys(S.en).sort());
    for (const t of [S.en, S.ru]) for (const [k, v] of Object.entries(t)) assert.ok(typeof v === "string", k);
  }
});

test("parseLinks splits on spaces, commas and lines and drops repeats", () => {
  assert.deepEqual(parseLinks("https://a.test/x, https://b.test\nhttps://a.test/x;  \n"), ["https://a.test/x", "https://b.test"]);
  assert.deepEqual(parseLinks(""), []);
  assert.deepEqual(parseLinks(null), []);
});

test("fmtSize: megabytes up to a gigabyte, then gigabytes, a comma in Russian", () => {
  setLangSource(() => "en");
  assert.equal(fmtSize(65 * MB), "65 MB");
  assert.equal(fmtSize(10), "1 MB");
  assert.equal(fmtSize(1.44 * GB), "1.4 GB");
  setLangSource(() => "ru");
  assert.equal(fmtSize(1.44 * GB), "1,4 ГБ");
  assert.equal(fmtSize(65 * MB), "65 МБ");
});

test("the estimate asks to compress and says how big it gets (Russian)", () => {
  setLangSource(() => "ru");
  const l = planText({ n: 70, bytes: 2.5 * GB, exact: false, ffmpeg: true, small: 0.9 * GB, skipped: [], links: [] });
  assert.equal(l.q, "Примеров: 70. Займёт ~2,5 ГБ (оценка). Сжать видео?");
  assert.match(l.small, /922 МБ/);   // under a gigabyte - in megabytes
  assert.deepEqual(l.notes, []);
});

test("without ffmpeg the estimate says so and offers no size", () => {
  setLangSource(() => "en");
  const l = planText({ n: 3, bytes: 3 * MB, exact: true, ffmpeg: false, small: 1, skipped: [], links: [] });
  assert.equal(l.small, "");
  assert.equal(l.notes.length, 1);
  assert.match(l.notes[0], /ffmpeg/);
});

test("the estimate names skipped sites and unreadable links, and says when nothing is new", () => {
  setLangSource(() => "en");
  const l = planText({ n: 0, bytes: 0, ffmpeg: true, skipped: ["https://www.remotion.dev/prompts"], links: [{ url: "https://skillry.dev/x", error: "http_404" }] });
  assert.equal(l.none, true);
  assert.equal(l.q, "");
  assert.match(l.notes.join("|"), /remotion\.dev/);
  assert.match(l.notes.join("|"), /skillry\.dev.*http_404/);
});

test("problem, summary, percent, isRunning", () => {
  setLangSource(() => "en");
  assert.match(problem("too_many"), new RegExp(String(LINKS_MAX)));
  assert.equal(problem("nonsense"), problem("internal"));
  assert.equal(problem(""), "");
  assert.match(summary({ state: "done", added: 5 }), /5/);
  assert.equal(summary({ state: "running" }), "");
  assert.equal(percent({ done: 1, total: 4 }), 25);
  assert.equal(percent({ done: 0, total: 0 }), 0);
  assert.equal(percent({ done: 9, total: 4 }), 100);
  assert.ok(isRunning({ state: "stopping" }));
  assert.ok(!isRunning({ state: "done" }));
  assert.equal(siteName("https://www.prompt-motion.com/x"), "prompt-motion.com");
  assert.equal(sourceName("https://github.com/owner/repo/"), "owner/repo");
});

test("lacking: who the hub does not have yet, and who was asked a moment ago", () => {
  const sessions = [{ name: "hub", kind: "hub" }, { name: "moviemaker", kind: "agent" }];
  assert.deepEqual(NEEDED, ["screenwriter", "moviemaker"]);
  assert.deepEqual(lacking(sessions, {}, 1000), [{ name: "screenwriter", state: "ask" }]);
  assert.deepEqual(lacking(sessions, { screenwriter: 1000 }, 1000 + ASK_TTL - 1), [{ name: "screenwriter", state: "wait" }]);
  assert.deepEqual(lacking(sessions, { screenwriter: 1000 }, 1000 + ASK_TTL), [{ name: "screenwriter", state: "ask" }]);
  assert.deepEqual(lacking([{ name: "screenwriter" }, { name: "moviemaker" }], {}, 0), []);
  assert.deepEqual(lacking([{ name: "moviemaker", kind: "hub" }], {}, 0).map((x) => x.name), ["screenwriter", "moviemaker"]);   // the hub's own session is not an agent
  assert.equal(installText("moviemaker"), "specialists install moviemaker");
  assert.equal(hubName(sessions), "hub");
  assert.equal(hubName([]), "hub");
});

// ---- the question card over a fake page

function fakeEl(tag, cls = "", text = "") {
  const n = { tag, cls, text, children: [], dataset: {}, hidden: false, disabled: false, attrs: {}, handlers: {} };
  n.append = (...c) => { n.children.push(...c); };
  n.replaceChildren = (...c) => { n.children = c; };
  n.setAttribute = (k, v) => { n.attrs[k] = v; };
  n.addEventListener = (ev, fn) => { n.handlers[ev] = fn; };
  return n;
}
const walk = (n, f) => { f(n); (n.children || []).forEach((c) => c && c.children && walk(c, f)); };
const find = (n, pred) => { const out = []; walk(n, (x) => pred(x) && out.push(x)); return out; };

const QUESTION = { items: 70, mb: 65, minutes: 3, sources: 8, ready: 3, links: ["https://skillry.dev/ai-videos", "https://github.com/a/b"], agents: ["screenwriter", "moviemaker"] };

function setup({ answer = { ok: true, data: { first: "no" } }, status = { ok: true, data: { firstrun: QUESTION } }, rows = [] } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method, body: init.body });
    const r = init.method === "POST" ? answer : status;
    return { ok: r.ok, json: async () => r.data };
  };
  const timers = [];
  const installs = [];
  const fr = createFirstRun({
    hub: { el: fakeEl }, base: () => "http://x", agents: () => rows, install: async (n) => { installs.push(n); },
    setTimer: (fn, ms) => { timers.push([fn, ms]); return timers.length; }, clear: () => {},
  });
  return { fr, calls, timers, installs };
}

test("the question card shows the numbers and the three answers", async () => {
  setLangSource(() => "ru");
  const { fr } = setup();
  await fr.refresh();
  assert.equal(fr.node.hidden, false);
  const buttons = find(fr.node, (x) => x.tag === "button" && x.dataset.choice);
  assert.deepEqual(buttons.map((b) => b.text), ["Качаем", "Не качаем", "Поменяю в настройках"]);
  const text = find(fr.node, (x) => x.text).map((x) => x.text).join("\n");
  assert.match(text, /8 источников/);
  assert.match(text, /65 МБ/);
  assert.match(text, /3 минут/);
  assert.match(text, /Пока вы не ответите, ничего не скачивается/);
});

test("the card is English by default", async () => {
  setLangSource(() => "en-GB");
  const { fr } = setup();
  await fr.refresh();
  assert.deepEqual(find(fr.node, (x) => x.dataset.choice).map((b) => b.text), ["Download", "Don't download", "I'll change it in the settings"]);
});

test("an answer is sent once and the card goes away", async () => {
  setLangSource(() => "en");
  const { fr, calls } = setup();
  await fr.refresh();
  const first = fr.answer("no");
  const second = fr.answer("no");   // a double click
  await Promise.all([first, second]);
  const posts = calls.filter((c) => c.method === "POST");
  assert.equal(posts.length, 1);
  assert.deepEqual(JSON.parse(posts[0].body), { action: "firstrun", choice: "no" });
  assert.equal(fr.node.hidden, true);
});

test("a failed answer keeps the card and says so", async () => {
  setLangSource(() => "en");
  const { fr } = setup({ answer: { ok: false, data: { error: "x" } } });
  await fr.refresh();
  await fr.answer("yes");
  assert.equal(fr.node.hidden, false);
  assert.ok(find(fr.node, (x) => x.cls === "mg-q-err").length);
  assert.ok(find(fr.node, (x) => x.dataset.choice).every((b) => !b.disabled));
});

test("no question - nothing shows; another computer - nothing is asked", async () => {
  setLangSource(() => "en");
  const a = setup({ status: { ok: true, data: { firstrun: null } } });
  await a.fr.refresh();
  assert.equal(a.fr.node.hidden, true);
  const calls = [];
  globalThis.fetch = async (u) => { calls.push(u); return { ok: true, json: async () => ({ firstrun: QUESTION }) }; };
  const fr = createFirstRun({ hub: { el: fakeEl }, base: () => "http://x", local: () => false });
  await fr.refresh();
  assert.equal(fr.node.hidden, true);
  assert.equal(calls.length, 0);
});

test("a plugin process that starts after the page is asked again, then the card appears", async () => {
  setLangSource(() => "en");
  const { fr, timers } = setup({ status: { ok: false, data: null } });
  await fr.refresh();
  assert.equal(fr.node.hidden, true);
  assert.equal(timers.at(-1)[1], 4000);   // RETRY_MS
});

test("agent rows: Install for the missing, 'waiting' for the asked, 'in the hub' for the present", async () => {
  setLangSource(() => "en");
  const { fr, installs } = setup({ rows: [{ name: "screenwriter", state: "ask" }] });
  await fr.refresh();
  const rows = find(fr.node, (x) => x.dataset.agent);
  assert.deepEqual(rows.map((r) => r.dataset.agent), ["screenwriter", "moviemaker"]);
  const btn = find(rows[0], (x) => x.tag === "button")[0];
  assert.equal(btn.text, "Install");
  assert.equal(btn.disabled, false);
  assert.match(find(rows[1], (x) => x.text).map((x) => x.text).join(" "), /in the hub/);
  await btn.handlers.click();
  assert.deepEqual(installs, ["screenwriter"]);
  const waiting = setup({ rows: [{ name: "screenwriter", state: "wait" }] });
  await waiting.fr.refresh();
  const b2 = find(waiting.fr.node, (x) => x.tag === "button" && x.dataset.choice === undefined)[0];
  assert.equal(b2.disabled, true);
  assert.equal(agentTitle("moviemaker").split(" ")[0], "moviemaker");
});
