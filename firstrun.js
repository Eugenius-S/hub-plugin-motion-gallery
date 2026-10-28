// Hub Motion Gallery: the question of the first start - a card over the page. Nothing is downloaded until the owner answers (the plugin process holds
// it back; linkctl.py): Download / Don't download / I'll change it in the settings. The same question waits in Telegram; the first answer from either
// place settles it. The card also names the agents the owner set for the gallery (settings: agents; none by default) and gives "Install" for the ones the hub lacks.
import { currentLang, makeT } from "./i18n.js";

export const POLL_MS = 8000;      // a question answered in Telegram goes away from the page within this time
export const RETRY_MS = 4000;     // the plugin process may start after the page: ask again a few times
export const TRIES = 5;
export const REPAINT_MS = 2000;   // the agent rows follow the hub snapshot (an installed agent appears there)

export const STR = {
  en: {
    title: "Motion Gallery: download the reference videos?",
    body: "Configured: {sources} sources of motion references - sites and repositories with prompts and videos ({ready} of them are read by the downloader now).",
    cost: "Download: about {items} examples, {mb} MB of disk and {minutes} minutes in the background. Nothing is downloaded until you answer.",
    sources: "Sources",
    yes: "Download",
    no: "Don't download",
    settings: "I'll change it in the settings",
    hint: "Settings → Motion Gallery: sources. The question can be shown again there.",
    agents: "Motion Gallery works with these agents:",
    install: "Install",
    asked: "Request sent to the hub, waiting",
    here: "in the hub",
    error: "No answer from Motion Gallery. Try again.",
  },
  ru: {
    title: "Motion Gallery: скачать референсы?",
    body: "Настроено: {sources} источников референсов моушна: сайты и репозитории с промтами и видео (скачивалка пока читает {ready} из них).",
    cost: "Скачка: около {items} примеров, {mb} МБ на диске и {minutes} минут в фоне. Пока вы не ответите, ничего не скачивается.",
    sources: "Источники",
    yes: "Качаем",
    no: "Не качаем",
    settings: "Поменяю в настройках",
    hint: "Настройки → Motion Gallery: источники. Там же вопрос можно показать снова.",
    agents: "Motion Gallery работает с агентами:",
    install: "Поставить",
    asked: "Запрос отправлен хабу, ждём",
    here: "уже в хабе",
    error: "Нет ответа от Motion Gallery. Попробуйте ещё раз.",
  },
};
export const t = makeT(STR);

// "https://github.com/owner/repo" -> "owner/repo"; a site -> its host
export function sourceName(url) {
  try {
    const u = new URL(url);
    return u.hostname === "github.com" ? u.pathname.replace(/^\/|\/$/g, "") : u.hostname;
  } catch { return String(url || ""); }
}

export const agentTitle = (name) => name;   // the plugin names no agents of its own: the owner's word as it is

// hub: the Plugin API; base() - the address of the plugin process; local() - only the hub opened on this computer reaches it (the other pages: Telegram only);
// agents(names) - lacking() of lib.js for the agents the plugin named: [{name, state: "ask"|"wait"}], the ones the hub does not have yet; install(name) - a message
// to the hub; onSettings(settings) - the settings the plugin process reports (agents, composer_button) every time it answers
export function createFirstRun({ hub, base, local = () => true, agents = () => [], install = async () => {}, onSettings = () => {}, setTimer = setTimeout, clear = clearTimeout }) {
  const el = hub.el;
  const S = { q: null, timer: 0, tick: 0, busy: false, err: "", sig: "", tries: 0 };
  const node = el("div", "mg-q");
  node.hidden = true;
  node.setAttribute("role", "dialog");
  node.setAttribute("aria-modal", "true");

  const call = async (method, body) => {
    const res = await fetch(`${base()}/fetch`, {
      method, cache: "no-store", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    return { ok: res.ok, data };
  };

  function paint() {
    const q = S.q;
    node.hidden = !q;
    if (!q) { node.replaceChildren(); S.sig = ""; return; }
    const rows = agents(q.agents || []);
    const sig = JSON.stringify([currentLang(), q, rows.map((r) => r.name + r.state), S.busy, S.err]);
    if (sig === S.sig) return;
    S.sig = sig;
    node.setAttribute("aria-label", t("title"));
    const card = el("div", "mg-q-card");
    const list = el("details", "mg-q-src");
    list.append(el("summary", "", t("sources")), ...(q.links || []).map((u) => el("div", "mg-q-link", sourceName(u))));
    card.append(el("h2", "mg-q-h", t("title")), el("p", "mg-q-p", t("body", q)), el("p", "mg-q-p mg-q-cost", t("cost", q)));
    if (q.links && q.links.length) card.append(list);
    const box = el("div", "mg-q-agents");
    box.append(el("div", "mg-q-ah", t("agents")));
    for (const name of q.agents || []) {
      const r = rows.find((x) => x.name === name);
      const row = el("div", "mg-q-arow");
      row.dataset.agent = name;
      row.append(el("span", "mg-q-an", agentTitle(name)));
      if (!r) row.append(el("span", "mg-q-ok", t("here")));
      else {
        const b = el("button", "mg-q-ab", r.state === "wait" ? t("asked") : t("install"));
        b.type = "button";
        b.disabled = r.state === "wait";
        b.addEventListener("click", async () => { await install(name); paint(); });
        row.append(b);
      }
      box.append(row);
    }
    if ((q.agents || []).length) card.append(box);
    const btns = el("div", "mg-q-btns");
    for (const [id, cls] of [["yes", "mg-q-b mg-q-yes"], ["no", "mg-q-b"], ["settings", "mg-q-b"]]) {
      const b = el("button", cls, t(id));
      b.type = "button";
      b.dataset.choice = id;
      b.disabled = S.busy;
      b.addEventListener("click", () => answer(id));
      btns.append(b);
    }
    card.append(btns, el("p", "mg-q-hint", t("hint")));
    if (S.err) card.append(el("p", "mg-q-err", S.err));
    node.replaceChildren(card);
  }

  async function answer(choice) {
    if (S.busy) return;
    S.busy = true;
    S.err = "";
    paint();
    try {
      const r = await call("POST", { action: "firstrun", choice });
      if (r.ok) S.q = null;
      else S.err = t("error");
    } catch { S.err = t("error"); }
    S.busy = false;
    stopTimers();
    paint();
    if (S.q) schedule();
  }

  function stopTimers() { clear(S.timer); clear(S.tick); S.timer = S.tick = 0; }
  function schedule() {
    clear(S.timer);
    clear(S.tick);
    S.timer = setTimer(refresh, POLL_MS);
    S.tick = setTimer(function again() { paint(); if (S.q) S.tick = setTimer(again, REPAINT_MS); }, REPAINT_MS);
  }

  // asks the plugin process whether the question waits; polls while it does (the settings tab calls it too after "show the question again")
  async function refresh() {
    stopTimers();
    if (!local()) { S.q = null; return paint(); }
    let down = false;
    try {
      const r = await call("GET");
      S.q = r.ok && r.data && r.data.firstrun ? r.data.firstrun : null;
      down = !r.ok;
      if (r.ok && r.data && r.data.settings) onSettings(r.data.settings);
    } catch { S.q = null; down = true; }
    paint();
    if (S.q) { S.tries = 0; schedule(); }
    else if (down && S.tries++ < TRIES) S.timer = setTimer(refresh, RETRY_MS);   // the plugin process is still starting
  }

  return { node, refresh, paint, answer, state: S };
}
