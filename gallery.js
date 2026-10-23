// Hub Motion Gallery: the grid of examples - used by the view and by the overlay from a chat input.
// Many entries are fine: the DOM is built once per list, a filter only hides cards; posters get their address when a card
// comes near the screen (IntersectionObserver), a video exists only while the mouse is over a card, one at a time.
import { categories, excerpt, filterItems, fmtDuration, linksOf, mediaUrl, metaLine, sourceList, tagList } from "./lib.js";

const HOVER_MS = 140;   // the mouse must stay this long: a sweep over the grid starts no video

// props: el (hub.el), tr (translator), base() -> process address or "" (not reachable from here), onPick(item),
//        session? { get(), set(name), list() } - "Insert into" choice (the view; the overlay inserts into its own chat)
export function createGallery({ el, tr, base, onPick, session = null }) {
  const S = { data: null, status: "loading", q: "", category: "", source: "", tags: new Set(), cards: new Map(), sig: "", shown: 0 };
  let cur = null, timer = 0, io = null, toolsSig = "";

  const root = el("div", "mg");
  const search = el("input", "mg-search");
  search.type = "search";
  search.autocomplete = "off";
  search.addEventListener("input", () => { S.q = search.value; applyFilter(); });
  const reload = el("button", "mg-btn", "↻");
  reload.type = "button";
  reload.addEventListener("click", () => load());
  const pickBox = el("label", "mg-target");
  const pick = el("select", "mg-select");
  pick.addEventListener("change", () => session?.set(pick.value));
  const pickLbl = el("span", "", "");
  pickBox.append(pickLbl, pick);
  const bar = el("div", "mg-bar");
  bar.append(search, ...(session ? [pickBox] : []), reload);
  const cats = el("div", "mg-chips");
  const srcs = el("div", "mg-chips mg-sources");
  const tags = el("div", "mg-chips mg-tags");
  const count = el("div", "mg-count");
  const note = el("div", "mg-note");
  const grid = el("div", "mg-grid");
  root.append(bar, cats, srcs, tags, count, note, grid);

  function stop() {
    clearTimeout(timer);
    if (!cur) return;
    cur.v.pause();
    cur.v.removeAttribute("src");
    cur.v.load();   // lets go of the connection
    cur.v.remove();
    cur.card.classList.remove("playing");
    cur = null;
  }

  function play(card, item) {
    stop();
    const src = mediaUrl(base(), item.preview);
    if (!src) return;
    const v = document.createElement("video");
    v.className = "mg-video";
    v.muted = true;
    v.loop = true;
    v.playsInline = true;
    v.preload = "none";
    v.disablePictureInPicture = true;
    v.addEventListener("playing", () => card.classList.add("playing"));
    v.addEventListener("error", () => { if (cur?.v === v) stop(); });
    v.src = src;
    card.querySelector(".mg-media").append(v);
    cur = { card, v };
    v.play().catch(() => {});
  }

  function buildCard(item) {
    const card = el("div", "mg-card");
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.dataset.slug = item.slug;
    const media = el("div", "mg-media");
    const img = el("img", "mg-poster");
    img.alt = "";
    img.decoding = "async";
    img.draggable = false;
    img.dataset.src = mediaUrl(base(), item.poster);
    media.append(img);
    const dur = fmtDuration(item.duration);
    if (dur) media.append(el("span", "mg-dur", dur));
    const links = linksOf(item);
    if (links.length) {
      const a = el("a", "mg-link", "↗");
      a.href = links[0].url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = [tr("open_post"), links[0].source].filter(Boolean).join(" · ");
      a.addEventListener("click", (e) => e.stopPropagation());
      media.append(a);
    }
    const cap = el("div", "mg-cap");
    const meta = metaLine(item);
    if (meta) cap.append(el("div", "mg-meta", meta));
    if (item.prompt) cap.append(el("div", "mg-prompt", excerpt(item.prompt)));
    card.append(media, cap);
    card.title = item.prompt ? item.prompt.slice(0, 400) : item.slug;
    card.addEventListener("mouseenter", () => { clearTimeout(timer); timer = setTimeout(() => play(card, item), HOVER_MS); });
    card.addEventListener("mouseleave", () => { clearTimeout(timer); if (cur?.card === card) stop(); });
    card.addEventListener("click", () => onPick(item));
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(item); } });
    return card;
  }

  function observe() {
    io?.disconnect();
    io = new IntersectionObserver((hits) => {
      for (const h of hits) {
        if (!h.isIntersecting) continue;
        const img = h.target;
        if (img.dataset.src && !img.src) img.src = img.dataset.src;
        io.unobserve(img);
      }
    }, { rootMargin: "400px 0px" });
    for (const card of S.cards.values()) io.observe(card.querySelector(".mg-poster"));
  }

  function chip(label, on, fn, n) {
    const b = el("button", "mg-chip" + (on ? " on" : ""), n != null ? `${label} ${n}` : label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(on));
    b.addEventListener("click", fn);
    return b;
  }

  function drawChips() {
    const items = S.data?.items || [];
    cats.replaceChildren();
    const cl = categories(items);
    if (cl.length > 1) {
      cats.append(chip(tr("all"), !S.category, () => { S.category = ""; drawChips(); applyFilter(); }, items.length));
      for (const c of cl) cats.append(chip(c.name, S.category === c.name, () => { S.category = S.category === c.name ? "" : c.name; drawChips(); applyFilter(); }, c.n));
    }
    srcs.replaceChildren();
    const sl = sourceList(items);
    if (sl.length > 1) {
      for (const c of sl) srcs.append(chip(c.name, S.source === c.name, () => { S.source = S.source === c.name ? "" : c.name; drawChips(); applyFilter(); }, c.n));
    }
    tags.replaceChildren();
    for (const t of tagList(items)) {
      const on = S.tags.has(t.name);
      tags.append(chip("#" + t.name, on, () => { on ? S.tags.delete(t.name) : S.tags.add(t.name); drawChips(); applyFilter(); }));
    }
  }

  // texts under the filters (the count, the hints); a video keeps playing: this runs on every snapshot too
  function drawNote() {
    const items = S.data?.items || [];
    count.textContent = items.length ? tr("count", { n: S.shown, total: items.length }) : "";
    if (S.status === "ok" && items.length && !S.shown) note.textContent = tr("no_match");
    else if (S.status === "ok" && !items.length) note.textContent = S.data?.ready ? tr("empty") : S.data?.configured ? tr("no_file") : tr("not_set");
    else note.textContent = { loading: tr("loading"), offline: tr("offline"), nolocal: tr("local_only") }[S.status] || "";
    note.hidden = !note.textContent;
  }

  function applyFilter() {
    stop();
    const items = S.data?.items || [];
    const keep = new Set(filterItems(items, { q: S.q, category: S.category, source: S.source, tags: [...S.tags] }).map((i) => i.slug));
    for (const [slug, card] of S.cards) card.hidden = !keep.has(slug);
    S.shown = keep.size;
    drawNote();
  }

  async function load() {
    const b = base();
    if (!b) { S.status = "nolocal"; return applyFilter(); }
    let data = null;
    try {
      const r = await fetch(b + "/gallery.json", { cache: "no-store" });
      if (r.ok) data = await r.json();
    } catch { /* the process is not up */ }
    if (!data || !Array.isArray(data.items)) { S.status = "offline"; return applyFilter(); }
    S.status = "ok";
    const sig = JSON.stringify(data.items.map((i) => [i.slug, i.poster, i.preview, i.prompt, i.category, i.author, i.duration, i.tags, i.sources, i.links, i.post, i.page]));
    S.data = data;
    if (sig !== S.sig) {
      S.sig = sig;
      S.cards = new Map(data.items.map((i) => [i.slug, buildCard(i)]));
      grid.replaceChildren(...S.cards.values());
      if (S.category && !data.items.some((i) => i.category === S.category)) S.category = "";
      if (S.source && !data.items.some((i) => (i.sources || []).includes(S.source))) S.source = "";
      for (const t of [...S.tags]) if (!data.items.some((i) => (i.tags || []).includes(t))) S.tags.delete(t);
      drawChips();
      observe();
    }
    applyFilter();
  }

  // texts and the "insert into" choice are redrawn on every snapshot (the language may change, sessions come and go)
  function update() {
    search.placeholder = tr("search");
    reload.title = tr("reload");
    reload.setAttribute("aria-label", tr("reload"));
    pickLbl.textContent = tr("insert_into");
    if (session) {
      const names = session.list(), last = session.get();
      const sig = names.join("\n") + "\u0000" + last;
      if (sig !== toolsSig) {
        toolsSig = sig;
        pick.replaceChildren(...names.map((n) => { const o = el("option", "", n); o.value = n; return o; }));
        pick.value = last && names.includes(last) ? last : names[0] || "";
      }
      pickBox.hidden = !names.length;
    }
    drawNote();
  }

  update();
  load();
  return { node: root, load, update, stop, focus: () => search.focus(), destroy() { stop(); io?.disconnect(); } };
}
