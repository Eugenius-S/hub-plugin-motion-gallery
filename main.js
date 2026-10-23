// Hub Motion Gallery: a grid of motion examples with hover previews. A click puts the example into a chat input: the poster
// as a picture and the full prompt as text; nothing is sent - the owner edits it and sends it. Two ways in: the view in the
// menu (inserts into the last opened chat, or the one chosen at the top) and a button in the input of any chat (the gallery
// opens over the page and inserts into that chat). Files are served by the plugin process (server.py).
import { createGallery } from "./gallery.js";
import { makeT, setLangSource } from "./i18n.js";
import { insertInto, waitComposer } from "./insert.js";
import { chatText, posterName, processPort, sessionOf, targets } from "./lib.js";

const STR = {
  en: {
    subtitle: "motion examples: hover to play, click to put into a chat",
    title: "Motion Gallery",
    open_in: "Motion examples: put into this chat",
    search: "Search prompts, authors, tags…",
    reload: "Reload the gallery",
    insert_into: "Insert into",
    all: "All",
    count: "{n} of {total}",
    open_post: "Open the original post",
    loading: "Loading…",
    empty: "The gallery has no examples yet. Add entries to gallery.json in the gallery folder.",
    no_file: "No gallery.json in the gallery folder. Add one (slug, category, author, duration, tags, prompt, preview, poster).",
    not_set: "No gallery folder set. In hub.json set extensions → motion-gallery → gallery_dir to a folder with gallery.json, previews/ and posters/, then reload.",
    no_match: "Nothing matches the search.",
    offline: "The plugin process is not responding. Restart the plugin: hub restart ext:<account>:motion-gallery",
    local_only: "Motion Gallery works only on this computer: open the hub via localhost.",
    no_poster: "The poster did not load: only the prompt was put in.",
    no_chat: "The chat input did not open: choose a chat and try again.",
    close: "Close",
  },
  ru: {
    subtitle: "примеры движения: наведи — играет, клик — в чат",
    title: "Галерея движения",
    open_in: "Примеры движения: вставить в этот чат",
    search: "Поиск по промтам, авторам, тегам…",
    reload: "Обновить галерею",
    insert_into: "Вставлять в",
    all: "Все",
    count: "{n} из {total}",
    open_post: "Открыть исходный пост",
    loading: "Загрузка…",
    empty: "В галерее пока нет примеров. Добавьте записи в gallery.json в папке галереи.",
    no_file: "В папке галереи нет gallery.json. Добавьте его (slug, category, author, duration, tags, prompt, preview, poster).",
    not_set: "Папка галереи не задана. В hub.json укажите extensions → motion-gallery → gallery_dir — папку с gallery.json, previews/ и posters/, и обновите.",
    no_match: "По запросу ничего не найдено.",
    offline: "Процесс плагина не отвечает. Перезапустите плагин: hub restart ext:<аккаунт>:motion-gallery",
    local_only: "Галерея движения работает только на этом компьютере: откройте хаб через localhost.",
    no_poster: "Постер не загрузился: вставлен только промт.",
    no_chat: "Поле ввода чата не открылось: выберите чат и повторите.",
    close: "Закрыть",
  },
};
const tr = makeT(STR);
const ID = "motion-gallery";
const LAST = "motion-gallery:last";   // the chat opened last (localStorage): the page may start right on this view

let hub = null;
let main = null;      // the gallery of the view, lives between snapshots
let over = null;      // the open overlay {node, g, off}

const local = () => ["localhost", "127.0.0.1"].includes(location.hostname);
const base = () => (local() ? `${location.protocol}//${location.hostname}:${processPort(location.port)}` : "");
const lastChat = () => { try { return localStorage.getItem(LAST) || ""; } catch { return ""; } };
const sessions = () => (hub.snapshot()?.sessions || []);

function remember(hash) {
  const name = sessionOf(hash);
  if (name) try { localStorage.setItem(LAST, name); } catch { /* storage is off */ }
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

// the poster of an example as a File (the process serves it, a remote poster too); null - did not load
async function posterFile(item) {
  try {
    const r = await fetch(`${base()}/poster/${encodeURIComponent(item.slug)}`);
    if (!r.ok) return null;
    const b = await r.blob();
    if (!b.size || !b.type.startsWith("image/")) return null;
    return new File([b], posterName(item, b.type), { type: b.type });
  } catch { return null; }
}

// the example goes into the input `form` (a promise of the form: the chat may still be opening); the poster loads meanwhile
async function putIn(formPromise, item) {
  const [form, file] = await Promise.all([formPromise, posterFile(item)]);
  if (!form || !form.isConnected) return toast(tr("no_chat"));
  const res = insertInto(form, { text: chatText(item), file });
  if (!res.file) toast(tr("no_poster"));
}

// the view: into the chat chosen at the top (the last opened one by default)
function pickFromView(item) {
  const name = chosen();
  if (!name) return toast(tr("no_chat"));
  const ok = () => sessionOf(location.hash) === name;
  main.stop();
  if (!ok()) location.hash = "#/s/" + encodeURIComponent(name);
  putIn(waitComposer(ok), item);
}

let picked = "";   // the choice at the top of the view; empty - the chat opened last
const chosen = () => {
  const names = targets(sessions(), lastChat());
  return picked && names.includes(picked) ? picked : names[0] || "";
};

function render(root) {
  if (!main) {
    main = createGallery({
      el: hub.el, tr, base, onPick: pickFromView,
      session: { get: chosen, set: (n) => { picked = n; }, list: () => targets(sessions(), lastChat()) },
    });
    root.replaceChildren(main.node);
  } else main.update();
  over?.g.update();
}

// the gallery over the page, for the input `form` of a chat
function openOver(form) {
  if (over) return;
  const back = hub.el("div", "mg-over");
  const panel = hub.el("div", "mg-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  const x = hub.el("button", "mg-close", "✕");
  x.type = "button";
  const g = createGallery({ el: hub.el, tr, base, onPick: (item) => { close(); putIn(Promise.resolve(form), item); } });
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  function close() {
    if (!over) return;
    removeEventListener("keydown", onKey, true);
    g.destroy();
    back.remove();
    over = null;
    if (form.isConnected) form.querySelector("textarea")?.focus();
  }
  x.addEventListener("click", close);
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  addEventListener("keydown", onKey, true);
  panel.append(x, g.node);
  back.append(panel);
  document.body.append(back);
  over = { node: back, g };
  x.title = tr("close");
  x.setAttribute("aria-label", tr("close"));
  g.focus();
}

export default function register(h) {
  hub = h;
  setLangSource(() => hub.lang);   // read on every use, never at load
  hub.addStyle("style.css");
  remember(location.hash);
  addEventListener("hashchange", () => remember(location.hash));
  hub.addView({
    id: ID, title: tr("title"), subtitle: tr("subtitle"), icon: "icon.svg", full: true,
    render,
    show() { main?.load(); },   // new previews may have been added since the last visit
    hide() { main?.stop(); },
  });
  // a button before the microphone in the input of any chat (the composer.tools slot - an addition of this hub)
  if (typeof hub.addSlot === "function") {
    hub.addSlot("composer.tools", {
      id: "gallery",
      render(root, snap, ctx) {
        if (!ctx.session) return root.replaceChildren();   // not a session chat (a plugin's own input, forms)
        let b = root.firstChild;
        if (!b) {
          b = hub.el("button", "btn round quiet mg-open");
          b.type = "button";
          b.innerHTML = '<span class="mg-oi" aria-hidden="true"></span>';
          b.addEventListener("click", () => { const form = root.closest("form"); if (form) openOver(form); });
          root.append(b);
        }
        b.title = tr("open_in");
        b.setAttribute("aria-label", tr("open_in"));
      },
    });
  }
}
