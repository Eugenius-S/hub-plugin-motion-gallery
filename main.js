// Hub Motion Gallery: a grid of motion examples with hover previews. A click puts a tag "(Name)" of the example into a chat
// input at the cursor; nothing is sent - the owner edits it and sends it, and the prompt of every tag still in the text and the
// links to its video and preview travel with the message (insert.js). Two ways in: the view in the
// menu (inserts into the last opened chat, or the one chosen at the top) and a button in the input of any chat (the gallery
// opens over the page and inserts into that chat). Files are served by the plugin process (server.py).
import { createAttach } from "./attach.js";
import { createFetchUi, t as tf } from "./fetchui.js";
import { createFirstRun } from "./firstrun.js";
import { createGallery } from "./gallery.js";
import { makeT, setLangSource } from "./i18n.js";
import { insertTag, interceptSend, tagsOf, waitComposer } from "./insert.js";
import { ASK_TTL, chatText, hubName, installText, lacking, linksOf, mediaUrl, processPort, sessionOf, tagFor, targets } from "./lib.js";

const STR = {
  en: {
    subtitle: "motion examples: hover to play, click to add a tag to a chat",
    title: "Motion Gallery",
    open_in: "Motion examples: put into this chat",
    open_row: "Motion examples",
    search: "Search prompts, authors, tags…",
    reload: "Reload the gallery",
    insert_into: "Insert into chat",
    all: "All",
    count: "{n} of {total}",
    open_post: "Open the original post",
    loading: "Loading…",
    empty: "The gallery has no examples yet. Download them: Settings → Motion Gallery: sources.",
    no_file: "gallery.json is not readable: not in the gallery folder, or not at the media_base address (a dead link, no access). Check the setting and reload.",
    not_set: "No examples yet. Download them: Settings → Motion Gallery: sources (or point the gallery at a folder or a link in hub.json: extensions → motion-gallery → gallery_dir or media_base).",
    not_sent: "The request to the hub was not sent: {err}",
    no_match: "Nothing matches the search.",
    offline: "The plugin process is not responding. Restart the plugin: hub restart ext:<account>:motion-gallery",
    local_only: "Motion Gallery works only on this computer: open the hub via localhost.",
    prompt: "Prompt",
    to_source: "To the source",
    delete: "Delete",
    deleted: "Deleted: {name}",
    undo: "Undo",
    delete_failed: "The example was not deleted: the gallery refused or did not answer. It is back in the list.",
    no_chat: "The chat input did not open: choose a chat and try again.",
    close: "Close",
    expand: "View full screen",
    prev: "Previous example",
    next: "Next example",
    no_video: "This example has no video, only a poster.",
    video_failed: "The video did not load.",
    attach_title: "What goes with the message",
    attach_label: "Attach the prompts of {n} examples to the message ({chars} characters, from outside sources)",
    attach_on: "On: the prompts are added under the message as reference material, not instructions.",
    attach_off: "Off: only the tags go with the message.",
    attach_show: "Show",
    attach_hide: "Hide",
    attach_chars: "{n} characters go",
    attach_cut: "(the rest, {n}, is cut)",
    attach_none: "no prompt, only links",
  },
  ru: {
    subtitle: "примеры движения: наведи, и играет; клик ставит тег в чат",
    title: "Галерея движения",
    open_in: "Примеры движения: вставить в этот чат",
    open_row: "Примеры движения",
    search: "Поиск по промтам, авторам, тегам…",
    reload: "Обновить галерею",
    insert_into: "Вставлять в чат",
    all: "Все",
    count: "{n} из {total}",
    open_post: "Открыть исходный пост",
    loading: "Загрузка…",
    empty: "В галерее пока нет примеров. Скачайте их: Настройки → Motion Gallery: источники.",
    no_file: "gallery.json не читается: нет в папке галереи или по адресу media_base (ссылка не отвечает или нет доступа). Проверьте настройку и обновите.",
    not_set: "Примеров пока нет. Скачайте их: Настройки → Motion Gallery: источники (или укажите в hub.json папку или ссылку: extensions → motion-gallery → gallery_dir или media_base).",
    not_sent: "Запрос хабу не отправлен: {err}",
    no_match: "По запросу ничего не найдено.",
    offline: "Процесс плагина не отвечает. Перезапустите плагин: hub restart ext:<аккаунт>:motion-gallery",
    local_only: "Галерея движения работает только на этом компьютере: откройте хаб через localhost.",
    prompt: "Промт",
    to_source: "К источнику",
    delete: "Удалить",
    deleted: "Удалено: {name}",
    undo: "Отменить",
    delete_failed: "Пример не удалён: галерея отказала или не ответила. Он вернулся в список.",
    no_chat: "Поле ввода чата не открылось: выберите чат и повторите.",
    close: "Закрыть",
    expand: "Открыть на весь экран",
    prev: "Предыдущий пример",
    next: "Следующий пример",
    no_video: "У примера нет видео, только постер.",
    video_failed: "Видео не загрузилось.",
    attach_title: "Что уходит вместе с сообщением",
    attach_label: "Приложить к сообщению промты ({n} шт., {chars} знаков, из внешних источников)",
    attach_on: "Включено: промты добавятся под сообщением как справочный материал, не как указания.",
    attach_off: "Выключено: с сообщением уходят только теги.",
    attach_show: "Показать",
    attach_hide: "Скрыть",
    attach_chars: "уходит {n} знаков",
    attach_cut: "(остальное, {n}, обрезано)",
    attach_none: "промта нет, только ссылки",
  },
};
const tr = makeT(STR);
const ID = "motion-gallery";
const ASKED = "motion-gallery:asked";   // agents asked from the hub (localStorage): name -> when; "Install" waits ASK_TTL before it asks again
const LAST = "motion-gallery:last";   // the chat opened last (localStorage): the page may start right on this view

let hub = null;
let main = null;      // the gallery of the view, lives between snapshots
let over = null;      // the open overlay {node, g, off}
let attach = null;    // the plate over the chat input: what goes with the message, and the owner's switch (attach.js)
let cfg = { composer_button: true };   // the settings the plugin process reports (GET /fetch): the button in the chat input
const slotRoots = new Set();   // the nodes of that button, so a late answer of the process can take them out of inputs already drawn
function onSettings(v) {
  cfg = { ...cfg, ...v };
  if (cfg.composer_button === false) for (const r of slotRoots) r.replaceChildren();
}

const local = () => ["localhost", "127.0.0.1"].includes(location.hostname);
const base = () => (local() ? `${location.protocol}//${location.hostname}:${processPort(location.port)}` : "");
const lastChat = () => { try { return localStorage.getItem(LAST) || ""; } catch { return ""; } };
const sessions = () => (hub.snapshot()?.sessions || []);

function remember(hash) {
  const name = sessionOf(hash);
  if (name) try { localStorage.setItem(LAST, name); } catch { /* storage is off */ }
}

const askedAt = () => { try { return JSON.parse(localStorage.getItem(ASKED) || "{}") || {}; } catch { return {}; } };
const lackNow = (names = []) => lacking(hub.snapshot()?.sessions || [], askedAt(), Date.now(), names);
// "Install": a message to the hub from the owner - only the hub or the owner installs agents; the row waits until the session appears in the snapshot
async function install(name) {
  const asked = askedAt();
  if (asked[name] && Date.now() - asked[name] < ASK_TTL) return;
  const save = (v) => { try { localStorage.setItem(ASKED, JSON.stringify(v)); } catch { /* storage is off */ } };
  save({ ...asked, [name]: Date.now() });
  const r = await hub.post("/api/send", { session: hubName(sessions()), text: installText(name), action: true });
  if (r && r.error) {
    const back = askedAt();
    delete back[name];
    save(back);
    toast(tr("not_sent", { err: r.error }));
  }
}

let toastTimer = 0;
function toast(text) {
  document.querySelector(".mg-toast")?.remove();
  const t = hub.el("div", "mg-toast", text);
  t.setAttribute("role", "status");
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 5000);
}

// the tag of the example goes into the input `form` (a promise of the form: the chat may still be opening) at the cursor;
// what the tag stands for is kept with the input and added under the message when it is sent. true - it went in
async function putIn(formPromise, item) {
  const form = await formPromise;
  const ta = form?.isConnected ? form.querySelector("textarea") : null;
  if (!ta) { toast(tr("no_chat")); return false; }
  const tags = tagsOf(ta, true);
  for (const tag of [...tags.keys()]) if (!ta.value.includes(tag)) tags.delete(tag);   // deleted from the text: forgotten
  const tag = tagFor(item, new Map([...tags].map(([t, r]) => [t, r.slug])));
  const url = (src) => mediaUrl(base(), src);
  tags.set(tag, { slug: item.slug, prompt: chatText(item), video: url(item.video), preview: url(item.preview), source: linksOf(item)[0]?.url || "" });
  const went = insertTag(form, tag);
  attach?.watch(form);
  return went;
}

// Delete (the button in the lightbox): the card leaves the grid at once and a plate "Deleted · Undo" stays for a few seconds;
// only when they pass does the process take the example off the disk. Undo, or leaving the page, deletes nothing
const UNDO_MS = 6000;
const undo = new Map();   // slug -> { plate, timer }
const hideEverywhere = (slug, on) => { main?.hide(slug, on); over?.g.hide(slug, on); };

async function removeOnServer(slug) {
  try {
    const r = await fetch(base() + "/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slug }) });
    return r.ok;
  } catch { return false; }
}

function onDelete(item) {
  if (undo.has(item.slug)) return;
  hideEverywhere(item.slug, true);
  let box = document.querySelector(".mg-undos");
  if (!box) { box = hub.el("div", "mg-undos"); document.body.append(box); }
  const plate = hub.el("div", "mg-undo");
  plate.setAttribute("role", "status");
  const back = hub.el("button", "mg-undo-btn", tr("undo"));
  back.type = "button";
  plate.append(hub.el("span", "mg-undo-name", tr("deleted", { name: item.title || item.slug })), back);
  box.append(plate);
  const rec = { plate, timer: 0 };
  undo.set(item.slug, rec);
  const finish = () => { clearTimeout(rec.timer); plate.remove(); undo.delete(item.slug); };
  back.addEventListener("click", () => { finish(); hideEverywhere(item.slug, false); });
  rec.timer = setTimeout(async () => {
    const ok = await removeOnServer(item.slug);
    await Promise.all([main?.load(), over?.g.load()]);   // the list as the process has it now
    finish();
    hideEverywhere(item.slug, false);
    if (!ok) toast(tr("delete_failed"));
  }, UNDO_MS);
}

// inserts go one after another: quick clicks on several cards keep their order (the poster of each loads on its own time)
let queue = Promise.resolve();
const enqueue = (fn) => (queue = queue.then(fn, fn));

// the view: into the chat chosen at the top (the last opened one by default)
function pickFromView(item) {
  const name = chosen();
  if (!name) return toast(tr("no_chat"));
  const ok = () => sessionOf(location.hash) === name;
  main.stop();
  if (!ok()) location.hash = "#/s/" + encodeURIComponent(name);
  enqueue(() => putIn(waitComposer(ok), item));
}

let picked = "";   // the choice at the top of the view; empty - the chat opened last
const chosen = () => {
  const names = targets(sessions(), lastChat());
  return picked && names.includes(picked) ? picked : names[0] || "";
};

function render(root) {
  if (!main) {
    main = createGallery({
      el: hub.el, tr, base, onPick: pickFromView, onDelete,
      session: { get: chosen, set: (n) => { picked = n; }, list: () => targets(sessions(), lastChat()) },
    });
    root.replaceChildren(main.node);
  } else main.update();
  over?.g.update();
}

const syncButtons = () => { for (const b of document.querySelectorAll(".mg-open")) { b.classList.toggle("on", !!over); b.setAttribute("aria-pressed", String(!!over)); } };

// the gallery over the page, docked right above the input `form` of a chat: the input stays free and in reach, a click on a
// card puts the example into it and the gallery stays open (more can be picked, typing goes on); the cross in the corner,
// the button again or Escape (in the gallery or in the input) close it
function openOver(form) {
  if (over) return;
  const panel = hub.el("div", "mg-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", tr("title"));
  const scroll = hub.el("div", "mg-scroll");
  const x = hub.el("button", "mg-close");
  x.type = "button";
  x.append(typeof hub.icon === "function" ? hub.icon("close") : tr("close"));
  x.title = tr("close");
  x.setAttribute("aria-label", tr("close"));
  const input = () => form.querySelector("textarea");
  const g = createGallery({
    el: hub.el, tr, base, onDelete,
    onPick: (item, ev) => {
      enqueue(() => putIn(Promise.resolve(form), item)).then((ok) => { if (ok) g.mark(item.slug); });
      if (ev?.detail) input()?.focus({ preventScroll: true });   // a mouse pick: typing goes on right away
    },
  });
  function place() {
    if (!form.isConnected) return close();
    const r = form.getBoundingClientRect();
    panel.style.left = r.left + "px";
    panel.style.width = r.width + "px";
    const lift = attach?.height() || 0;   // the plate "what goes with the message" sits between the input and the panel
    panel.style.bottom = Math.max(0, innerHeight - r.top + 8 + lift) + "px";
    panel.style.maxHeight = Math.max(200, r.top - 24 - lift) + "px";
  }
  const ro = new ResizeObserver(place);   // the input grows with the text and the chips
  const off = () => close();
  // Escape closes it from the gallery and from the chat input (a mouse pick leaves the focus in the input)
  const onKey = (e) => { if (e.key === "Escape" && !e.defaultPrevented && (panel.contains(e.target) || form.contains(e.target))) close(); };
  function close() {
    if (!over) return;
    ro.disconnect();
    removeEventListener("resize", place);
    removeEventListener("hashchange", off);
    document.removeEventListener("keydown", onKey);
    g.destroy();
    panel.remove();
    over = null;
    syncButtons();
    if (form.isConnected) input()?.focus({ preventScroll: true });
  }
  x.addEventListener("click", close);
  // a mouse press on a card must not take the focus from the input
  panel.addEventListener("mousedown", (e) => { if (e.target.closest(".mg-card")) e.preventDefault(); });
  scroll.append(g.node);
  panel.append(scroll, x);
  document.body.append(panel);
  over = { node: panel, g, close, place };
  place();
  ro.observe(form);
  addEventListener("resize", place);
  addEventListener("hashchange", off);
  document.addEventListener("keydown", onKey);
  syncButtons();
  g.focus();
}

export default function register(h) {
  hub = h;
  setLangSource(() => hub.lang);   // read on every use, never at load
  hub.addStyle("style.css");
  attach = createAttach({ el: hub.el, tr, onSize: () => over?.place?.() });
  interceptSend(document, () => attach.allowed());   // the prompts go only when the owner switched it on
  hub.addStyle("navicon.css");   // the icon turns filled with radial waves on hover (the input button)
  // the question of the first start (what is configured, how long and how much the download takes): a card over the page until it is answered; in Telegram too
  const first = createFirstRun({ hub, base, local, agents: lackNow, install, onSettings });
  document.body.append(first.node);
  first.refresh();
  const fetchUi = createFetchUi({ hub, base, local, onAdded: () => { main?.load(); over?.g.load(); }, onAgain: () => first.refresh() });
  hub.addSettings({ id: "sources", title: tf("title"), render: (root) => fetchUi.render(root) });
  remember(location.hash);
  addEventListener("hashchange", () => remember(location.hash));
  hub.addView({
    id: ID, title: tr("title"), subtitle: tr("subtitle"), icon: "icon.svg", full: true,
    render,
    show() { main?.load(); },   // new previews may have been added since the last visit
    hide() { main?.stop(); },
  });
  // the button that opens the gallery over the chat input: before the microphone where the hub has the composer.tools slot
  // (an addition of this hub), otherwise a compact row above the input in session.composer (the shared hub has it). Never both.
  // A hub with neither place would put a "no such slot" error on the Plugins tab, so a slot is asked for only where it exists
  const slot = hub.capabilities?.composerTools === 1 ? TOOLS : place();
  if (slot && typeof hub.addSlot === "function") addButton(slot);
}

// The page names its places in SLOTS (ext.js, the module the page itself runs on). Asked once while the plugin loads - before
// register runs - so the button is in the first draw of the input, as it was. No such place (a hub without it): no slot is
// asked for, the view works alone and the Plugins tab shows no error. hub.capabilities.composerTools === 1 says the same
const TOOLS = "composer.tools", ABOVE = "session.composer";
const SLOTS = await import("/static/js/ext.js").then((m) => m.SLOTS || {}, () => ({}));
const place = () => (SLOTS[TOOLS] ? TOOLS : SLOTS[ABOVE] ? ABOVE : null);

// the input form the button belongs to: the slot of the tools row sits inside it, the row above the input - next to it in the dock
const formOf = (root) => root.closest("form") || root.closest(".dock-inner")?.querySelector("form.composer") || null;

function addButton(slot) {
  const row = slot === ABOVE;   // above the input: a compact row with a word, not a round icon among the tools
  hub.addSlot(slot, {
    id: "gallery",
    render(root, snap, ctx) {
      slotRoots.add(root);
      if (!ctx.session || cfg.composer_button === false) return root.replaceChildren();   // not a session chat (a plugin's own input, forms), or the owner switched the button off
      let b = root.firstChild;
      if (!b) {
        b = hub.el("button", row ? "btn quiet mg-open mg-row" : "btn round quiet mg-open");
        b.type = "button";
        b.innerHTML = '<span class="mg-oi" aria-hidden="true"></span>' + (row ? '<span class="mg-ol"></span>' : "");
        b.addEventListener("click", () => { const form = formOf(root); if (over) over.close(); else if (form) openOver(form); });
        root.append(b);
      }
      b.title = tr("open_in");
      b.setAttribute("aria-label", tr("open_in"));
      if (row) b.querySelector(".mg-ol").textContent = tr("open_row");
      b.classList.toggle("on", !!over);
      b.setAttribute("aria-pressed", String(!!over));
    },
  });
}
