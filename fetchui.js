// Hub Motion Gallery: the "Motion Gallery: sources" tab of the hub settings. The links to the sources are a list of fields (a new empty one appears when
// one is filled); the plugin process remembers them (linkctl.py). "Download" first asks for an estimate (how many examples, how much disk) and then
// asks "It takes about N GB. Compress the videos?": Compress / As is / Cancel. The downloaded videos, previews and prompts show in the gallery at once.
// All the work is in the process; the page only asks and shows (GET /fetch once a second while a run is on).
import { currentLang, makeT } from "./i18n.js";

export const LINKS_MAX = 40;      // the same as links.LINKS_MAX
export const POLL_MS = 1000;

export const STR = {
  en: {
    title: "Motion Gallery: sources",
    lead: "Downloads motion examples (a video, a preview and a prompt each) from the links below into the local gallery. Add a link: a site or a repository. Fill one field and a new empty one appears.",
    links: "Links", ph: "https://… (link)",
    del: "Remove the link (the examples it brought stay in the gallery)",
    site: "reads {site}", no_site: "no reader for this site yet",
    again: "Show the first-start question again", waiting: "The question about downloading the examples waits for your answer on the page and in Telegram.",
    go: "Download", stop: "Stop", stopping: "Stopping…", planning: "Counting what there is…",
    plan_none: "Nothing new to download: everything the readers find is already in the gallery.",
    plan_q: "{n} examples will take about {size}{exact}. Compress the videos?",
    plan_exact: "", plan_about: " (an estimate)",
    plan_small: "Compressed: about {size}.",
    plan_skip: "No reader yet, skipped: {links}.",
    plan_err: "Could not read {link}: {err}.",
    no_ffmpeg: "ffmpeg is not installed, so the videos cannot be compressed.",
    squeeze: "Compress", asis: "As is", cancel: "Cancel",
    prog: "{done} of {total}", counts: "added {added}", now: "Now: {name}", size: "{size} saved",
    s_done: "Done. Added {added}.", s_stopped: "Stopped. Added {added}. Press Download to continue: what is saved is skipped.",
    s_error: "The download stopped: too many failures in a row. Press Download to try again.",
    s_full: "The disk limit of {limit} MB is reached. Added {added}. Free some room or raise disk_limit_mb in the plugin settings, then press Download.",
    errs: "Problems: {list}",
    e_no_links: "Add at least one link.",
    e_too_many: "At most {max} links.",
    e_bad_link: "This is not a link: {link}",
    e_busy: "A download is already running.",
    e_page: "No answer from Motion Gallery. Open it once or restart the plugin.",
    e_internal: "That did not work. Try again.",
    e_local: "Downloading works only on the computer that runs the hub: open the hub via localhost.",
    kb: "KB", mb: "MB", gb: "GB",
  },
  ru: {
    title: "Motion Gallery: источники",
    lead: "Скачивает примеры движения (видео, превью и промт) по ссылкам ниже в локальную галерею. Добавьте ссылку: сайт или репозиторий. Заполните поле, и появится новое пустое.",
    links: "Ссылки", ph: "https://… (ссылка)",
    del: "Убрать ссылку (то, что она принесла, остаётся в галерее)",
    site: "читаем {site}", no_site: "для этого сайта пока нет читалки",
    again: "Показать вопрос первого запуска снова", waiting: "Вопрос о скачке примеров ждёт ответа на странице и в Telegram.",
    go: "Скачать", stop: "Стоп", stopping: "Останавливается…", planning: "Считаем, что есть…",
    plan_none: "Нового нет: всё, что находят читалки, уже в галерее.",
    plan_q: "Примеров: {n}. Займёт ~{size}{exact}. Сжать видео?",
    plan_exact: "", plan_about: " (оценка)",
    plan_small: "После сжатия: около {size}.",
    plan_skip: "Читалки пока нет, пропущено: {links}.",
    plan_err: "Не получилось прочитать {link}: {err}.",
    no_ffmpeg: "ffmpeg не установлен, поэтому видео сжать нельзя.",
    squeeze: "Сжать", asis: "Как есть", cancel: "Отмена",
    prog: "{done} из {total}", counts: "добавлено {added}", now: "Сейчас: {name}", size: "сохранено {size}",
    s_done: "Готово. Добавлено {added}.", s_stopped: "Остановлено. Добавлено {added}. «Скачать» продолжит: сохранённое пропускается.",
    s_error: "Скачивание остановилось: слишком много сбоев подряд. Нажмите «Скачать», чтобы повторить.",
    s_full: "Достигнут предел места на диске: {limit} МБ. Добавлено {added}. Освободите место или увеличьте disk_limit_mb в настройках плагина и нажмите «Скачать».",
    errs: "Сбои: {list}",
    e_no_links: "Добавьте хотя бы одну ссылку.",
    e_too_many: "Не больше {max} ссылок.",
    e_bad_link: "Это не ссылка: {link}",
    e_busy: "Скачивание уже идёт.",
    e_page: "Нет ответа от Motion Gallery. Откройте её один раз или перезапустите плагин.",
    e_internal: "Не получилось. Попробуйте ещё раз.",
    e_local: "Скачивание работает только на компьютере, где запущен хаб: откройте хаб по localhost.",
    kb: "КБ", mb: "МБ", gb: "ГБ",
  },
};

export const t = makeT(STR);

// the pasted text -> the links: separated by spaces, commas or lines, no repeats, no empty
export function parseLinks(text) {
  const out = [];
  for (const x of String(text || "").split(/[\s,;]+/)) if (x && !out.includes(x)) out.push(x);
  return out;
}

const RUNNING = ["running", "stopping"];
export const isRunning = (st) => !!st && RUNNING.includes(st.state);

// 0..100 for the bar; before the list is known (total 0) the bar is empty
export const percent = (st) => (st && st.total > 0 ? Math.max(0, Math.min(100, Math.round((100 * st.done) / st.total))) : 0);

// bytes -> "65 MB" / "1,4 GB" (Russian writes the decimal with a comma); the smallest step is a megabyte
export function fmtSize(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  const gb = n / 1024 ** 3;
  const dec = (v) => (currentLang().startsWith("ru") ? String(v).replace(".", ",") : String(v));
  if (gb >= 1) return `${dec(Math.round(gb * 10) / 10)} ${t("gb")}`;
  return `${Math.max(1, Math.round(n / 1024 ** 2))} ${t("mb")}`;
}

export const siteName = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return String(url || ""); } };

// the error codes of the process -> the word
export function problem(code, link) {
  if (!code) return "";
  const key = "e_" + code;
  return key in STR.en ? t(key, { max: LINKS_MAX, link: link || "" }) : t("e_internal");
}

// the line after a run: how it ended
export function summary(st) {
  if (!st) return "";
  const v = { added: st.added || 0, limit: st.limit || 0 };
  if (st.state === "done") return t("s_done", v);
  if (st.state === "stopped") return t("s_stopped", v);
  if (st.state === "error") return t("s_error");
  if (st.state === "full") return t("s_full", v);
  return "";
}

// the question after the estimate -> the lines the page draws: the question, what compressing would give, the notes
export function planText(plan) {
  const lines = { q: "", small: "", notes: [], none: false };
  if (!plan.n) lines.none = true;
  else {
    lines.q = t("plan_q", { n: plan.n, size: fmtSize(plan.bytes), exact: plan.exact ? t("plan_exact") : t("plan_about") });
    if (plan.ffmpeg) lines.small = t("plan_small", { size: fmtSize(plan.small) });
    else lines.notes.push(t("no_ffmpeg"));
  }
  const skipped = plan.skipped || [];
  if (skipped.length) lines.notes.push(t("plan_skip", { links: skipped.map(siteName).join(", ") }));
  for (const l of plan.links || []) if (l.error) lines.notes.push(t("plan_err", { link: siteName(l.url), err: l.error }));
  return lines;
}

export function createFetchUi({ hub, base, local = () => true, onAdded = () => {}, onAgain = () => {} }) {
  const el = hub.el;
  const S = { st: null, links: [], first: "", ffmpeg: false, err: "", info: "", timer: 0, busy: false, added: 0, off: false, tried: 0, plan: null, planning: false, drafts: [], sig: "" };
  const go = el("button", "mg-f-go btn");
  go.type = "button";
  const stop = el("button", "mg-f-stop btn quiet");
  stop.type = "button";
  const lead = el("p", "mg-f-lead");
  const lab = el("label", "mg-f-lab");
  const lst = el("div", "mg-f-list");
  const again = el("button", "mg-f-again btn quiet");   // the question of the first start (firstrun.js): asked again from here
  again.type = "button";
  const wait = el("p", "mg-f-lead mg-f-wait");
  const planBox = el("div", "mg-f-plan");
  const planQ = el("p", "mg-f-plan-q");
  const planSmall = el("p", "mg-f-plan-note");
  const planNotes = el("div", "mg-f-plan-notes");
  const planBtns = el("div", "mg-f-row");
  const squeeze = el("button", "mg-f-squeeze btn");
  squeeze.type = "button";
  const asis = el("button", "mg-f-asis btn");
  asis.type = "button";
  const cancel = el("button", "mg-f-cancel btn quiet");
  cancel.type = "button";
  planBtns.append(squeeze, asis, cancel);
  planBox.append(planQ, planSmall, planNotes, planBtns);
  const bar = el("div", "mg-f-bar");
  const fill = el("div", "mg-f-fill");
  bar.append(fill);
  bar.setAttribute("role", "progressbar");
  const prog = el("div", "mg-f-prog");
  const now = el("div", "mg-f-now");
  const msg = el("div", "mg-f-msg");
  msg.setAttribute("role", "status");
  const row = el("div", "mg-f-row");
  row.append(go, stop);
  const box = el("div", "mg-f");
  box.append(lead, lab, lst, again, wait, row, planBox, bar, prog, now, msg);

  const call = async (method, body) => {
    const res = await fetch(`${base()}/fetch`, {
      method, cache: "no-store", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    return { ok: res.ok, data };
  };

  // --- the fields: the links the plugin remembers, then the drafts (the last one is always empty) ---
  function newDraft() {
    const input = el("input", "mg-f-field");
    input.type = "text";
    input.spellcheck = false;
    const d = { input, wrap: el("div", "mg-f-link draft") };
    d.wrap.append(input);
    input.addEventListener("input", () => {
      if (input.value.trim() && S.drafts[S.drafts.length - 1] === d) { S.drafts.push(newDraft()); paint(); }
    });
    input.addEventListener("change", () => { commit(d); });
    input.addEventListener("keydown", (e) => { if (e && e.key === "Enter") commit(d); });
    return d;
  }
  S.drafts.push(newDraft());

  // a filled field becomes a saved link (the plugin keeps it); true when nothing is left in it
  async function commit(d) {
    const urls = parseLinks(d.input.value);
    if (!urls.length || d.busy) return true;
    d.busy = true;
    try {
      for (const u of urls) {
        const r = await call("POST", { action: "add", url: u });
        if (!r.ok) { S.err = problem((r.data && r.data.error) || "internal", u); paint(); return false; }
      }
    } catch { S.err = t("e_page"); paint(); return false; } finally { d.busy = false; }
    S.drafts = S.drafts.filter((x) => x !== d);
    if (!S.drafts.length || S.drafts[S.drafts.length - 1].input.value.trim()) S.drafts.push(newDraft());
    S.err = "";
    S.plan = null;
    await poll(true);
    return true;
  }

  async function del(url) {
    S.err = S.info = "";
    S.plan = null;
    try {
      const r = await call("POST", { action: "remove", url });
      if (!r.ok) S.err = problem((r.data && r.data.error) || "internal", url);
    } catch { S.err = t("e_page"); }
    await poll(true);
  }

  function linkRow(l, run) {
    const w = el("div", "mg-f-link saved");
    const u = el("span", "mg-f-url", l.url);
    u.title = l.url;
    const n = el("span", "mg-f-n", l.site ? t("site", { site: l.site }) : t("no_site"));
    n.classList.toggle("none", !l.site);
    const x = el("button", "mg-f-del btn quiet", "✕");
    x.type = "button";
    x.disabled = run;
    x.title = t("del");
    x.setAttribute("aria-label", t("del"));
    x.addEventListener("click", () => del(l.url));
    w.append(u, n, x);
    return w;
  }

  function paint() {
    const st = S.st;
    const run = isRunning(st);
    lead.textContent = t("lead");
    lab.textContent = t("links");
    const pending = S.first === "pending";
    again.textContent = t("again");
    again.hidden = pending || !S.first || S.off;
    wait.textContent = t("waiting");
    wait.hidden = !pending || S.off;
    // the list is built again only when it changed: a field that is typed in must not lose its focus
    const sig = JSON.stringify([currentLang(), run, S.links.map((l) => [l.url, l.site]), S.drafts.length, S.off]);
    if (sig !== S.sig) {
      S.sig = sig;
      for (const d of S.drafts) { d.input.placeholder = t("ph"); d.input.disabled = run || S.off; }
      lst.replaceChildren(...S.links.map((l) => linkRow(l, run)), ...S.drafts.map((d) => d.wrap));
    }
    go.textContent = S.planning ? t("planning") : t("go");
    go.disabled = run || S.busy || S.planning || !!S.plan || S.off;
    stop.textContent = st && st.state === "stopping" ? t("stopping") : t("stop");
    stop.hidden = !run;
    stop.disabled = !st || st.state === "stopping";
    // the question after the estimate
    const pl = S.plan ? planText(S.plan) : null;
    planBox.hidden = !pl;
    if (pl) {
      planQ.textContent = pl.none ? t("plan_none") : pl.q;
      planSmall.textContent = pl.small;
      planSmall.hidden = !pl.small;
      planNotes.replaceChildren(...pl.notes.map((n) => el("p", "mg-f-plan-note", n)));
      squeeze.textContent = t("squeeze");
      squeeze.hidden = pl.none;
      squeeze.disabled = !S.plan.ffmpeg || S.busy;
      asis.textContent = t("asis");
      asis.hidden = pl.none;
      asis.disabled = S.busy;
      cancel.textContent = t("cancel");
    }
    const show = !!st && (run || st.total > 0);
    bar.hidden = prog.hidden = !show;
    fill.style.transform = `scaleX(${percent(st) / 100})`;   // transform, not width: no layout on every tick
    bar.setAttribute("aria-valuenow", String(percent(st)));
    prog.textContent = show ? `${t("prog", { done: st.done, total: st.total })} · ${t("counts", { added: st.added })} · ${t("size", { size: fmtSize(st.bytes) })}` : "";
    now.textContent = run && st.current ? t("now", { name: st.current }) : "";
    const bad = S.off ? t("e_local") : S.err;
    const errs = !run && st && st.errors && st.errors.length ? t("errs", { list: st.errors.join("; ") }) : "";
    msg.textContent = bad || (run ? "" : [S.info || summary(st), errs].filter(Boolean).join(" "));
    msg.classList.toggle("bad", !!bad);
  }

  // the status arrived: the gallery is told about new examples (during a run too, so they appear while it goes)
  function take(status) {
    if (!status || typeof status !== "object") return;
    if (Array.isArray(status.links)) S.links = status.links;
    if (typeof status.first === "string") S.first = status.first;
    if (typeof status.ffmpeg === "boolean") S.ffmpeg = status.ffmpeg;
    const st = status.fetch || null;
    if (!st) return paint();
    const was = S.st;
    S.st = st;
    const grew = (st.added || 0) > S.added || (was && isRunning(was) && !isRunning(st) && (st.added || 0) > 0);
    S.added = st.added || 0;
    if (grew) onAdded();
    if (isRunning(st)) schedule();
    paint();
  }

  const schedule = () => { clearTimeout(S.timer); S.timer = setTimeout(poll, POLL_MS); };

  // keep: after an action the word about its failure stays
  async function poll(keep) {
    clearTimeout(S.timer);
    try {
      const r = await call("GET");
      if (r.ok) { if (keep !== true) S.err = ""; return take(r.data); }
      S.err = t("e_page");
    } catch { S.err = t("e_page"); }
    paint();
    if (isRunning(S.st)) schedule();
  }

  // "Download": the filled fields are saved, then the estimate; the question "Compress?" follows it
  go.addEventListener("click", async () => {
    S.err = S.info = "";
    S.busy = true;
    paint();
    try {
      for (const d of [...S.drafts]) if (d.input.value.trim() && !(await commit(d))) { S.busy = false; return paint(); }
      S.planning = true;
      S.busy = false;
      paint();
      const r = await call("POST", { action: "plan", urls: S.links.map((l) => l.url) });
      if (r.ok && r.data) S.plan = r.data;
      else S.err = problem((r.data && r.data.error) || "internal");
    } catch { S.err = t("e_page"); }
    S.planning = S.busy = false;
    paint();
  });
  async function begin(compress) {
    const urls = S.links.map((l) => l.url);
    S.err = S.info = "";
    S.busy = true;
    paint();
    try {
      const r = await call("POST", { action: "start", urls, compress });
      if (r.ok) { S.plan = null; S.added = 0; await poll(true); }
      else { S.err = problem((r.data && r.data.error) || "internal"); if (r.data && r.data.error === "busy") S.plan = null; }
    } catch { S.err = t("e_page"); }
    S.busy = false;
    paint();
    onAgain();   // the first-start card may have been settled by this start: it asks the plugin at once
  }
  squeeze.addEventListener("click", () => begin(true));
  asis.addEventListener("click", () => begin(false));
  cancel.addEventListener("click", () => { S.plan = null; paint(); });
  stop.addEventListener("click", async () => {
    try { await call("POST", { action: "stop" }); await poll(true); } catch { S.err = t("e_page"); paint(); }
  });
  again.addEventListener("click", async () => {
    try { await call("POST", { action: "firstrun", choice: "again" }); } catch { S.err = t("e_page"); }
    await poll(true);
    onAgain();   // the card on the page asks the plugin at once
  });

  return {
    node: box,
    // called with every snapshot of the hub: draws, and on the first call (or after a return to the tab) asks for the status
    render(root) {
      if (!root.contains(box)) root.replaceChildren(box);
      S.off = !local();
      paint();
      // the first call asks for the status; a silent process is asked again, but not oftener than every 5 s
      if (!S.off && !S.st && Date.now() - S.tried > 5000) { S.tried = Date.now(); poll(); }
    },
    state: S,
    poll,
    commit,
    del,
  };
}
