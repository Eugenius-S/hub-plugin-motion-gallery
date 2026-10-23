// Hub Motion Gallery: the grid of examples - used by the view and by the overlay from a chat input.
// Many entries are fine: the DOM is built once per list, a filter only hides cards; posters get their address when a card
// comes near the screen (IntersectionObserver), a video exists only while the mouse is over a card, one at a time.
import { categories, filterItems, fmtDuration, mediaUrl, metaLine, sourceList, tagList } from "./lib.js";
import { closeLightbox, openLightbox } from "./lightbox.js";
import { LOADING_PX, isDark, runner, runnerDisc } from "./loader.js";

const HOVER_MS = 140;   // the mouse must stay this long: a sweep over the grid starts no video

// props: el (hub.el), tr (translator), base() -> process address or "" (not reachable from here), onPick(item),
//        onDelete(item)? - the cross in the corner of a card (shown only when the process allows deleting): the caller hides the
//        card with hide() for the time of the undo and takes the example off the disk when that time is over,
//        session? { get(), set(name), list() } - "Insert into" choice (the view; the overlay inserts into its own chat)
export function createGallery({ el, tr, base, onPick, onDelete = null, session = null }) {
  const ico = (name) => { const s = el("span", "mg-ico mg-ico-" + name); s.setAttribute("aria-hidden", "true"); return s; };
  const S ={ data: null, status: "loading", q: "", category: "", source: "", tags: new Set(), cards: new Map(), sig: "", shown: 0, added: new Set(), pending: new Set(), canDelete: false };
  let cur = null, timer = 0, io = null, toolsSig = "", light = null;

  const root = el("div", "mg");
  const search = el("input", "mg-search");
  search.type = "search";
  search.autocomplete = "off";
  search.addEventListener("input", () => { S.q = search.value; applyFilter(); });
  const reload = el("button", "mg-btn");
  reload.type = "button";
  reload.append(ico("refresh"));
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
    if (!src || card.dataset.nopreview) return;
    const v = document.createElement("video");
    v.className = "mg-video";
    v.muted = true;
    v.loop = true;
    v.playsInline = true;
    v.preload = "none";
    v.disablePictureInPicture = true;
    v.addEventListener("playing", () => card.classList.add("playing"));
    // no preview file (yet): the card stays a calm poster and is not asked again until the list is reloaded
    v.addEventListener("error", () => { card.dataset.nopreview = "1"; if (cur?.v === v) stop(); });
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
    // the link to the source and the prompt live in the lightbox only (the card is a poster and a name)
    const cap = el("div", "mg-cap");
    const meta = metaLine(item);
    if (meta) cap.append(el("div", "mg-meta", meta));
    if (item.title) cap.append(el("div", "mg-title", item.title));
    card.append(media, cap);
    card.title = item.title || item.slug;
    const zoom = el("button", "mg-zoom");
    zoom.type = "button";
    zoom.append(ico("zoom"));
    zoom.title = tr("expand");
    zoom.setAttribute("aria-label", tr("expand"));
    zoom.addEventListener("click", (e) => { e.stopPropagation(); expand(item); });   // not a pick: nothing goes into the chat
    zoom.addEventListener("keydown", (e) => e.stopPropagation());
    media.append(zoom);
    if (S.canDelete && onDelete) {
      const del = el("button", "mg-del");
      del.type = "button";
      del.append(ico("close"));
      del.title = tr("delete");
      del.setAttribute("aria-label", tr("delete"));
      del.addEventListener("click", (e) => { e.stopPropagation(); onDelete(item); });   // no dialog: the undo plate is the safety net
      del.addEventListener("keydown", (e) => e.stopPropagation());
      media.append(del);
    }
    const done = el("span", "mg-added");
    done.append(ico("check"));
    done.hidden = !S.added.has(item.slug);
    media.append(done);
    card.addEventListener("mouseenter", () => { clearTimeout(timer); timer = setTimeout(() => play(card, item), HOVER_MS); });
    card.addEventListener("mouseleave", () => { clearTimeout(timer); if (cur?.card === card) stop(); });
    card.addEventListener("click", (e) => onPick(item, e));
    card.addEventListener("keydown", (e) => { if (e.target === card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onPick(item, e); } });
    return card;
  }

  // the lightbox steps through what the filters show now, in the order of the grid
  function expand(item) {
    stop();
    const shown = (S.data?.items || []).filter((i) => !S.cards.get(i.slug)?.hidden && !S.pending.has(i.slug));
    light = openLightbox({ el, tr, base, items: shown, index: shown.indexOf(item), onDelete: S.canDelete ? onDelete : null, onClose: () => { light = null; } });
  }

  function observe() {
    io?.disconnect();
    io = new IntersectionObserver((hits) => {
      for (const h of hits) {
        if (!h.isIntersecting) continue;
        const img = h.target;
        if (img.dataset.src && !img.src) {
          // the running man stays on the card from the moment the poster is asked until it is drawn
          const run = runnerDisc(el);
          const done = () => run.remove();
          img.addEventListener("load", done, { once: true });
          img.addEventListener("error", done, { once: true });
          img.after(run);
          img.src = img.dataset.src;
        }
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
    let text = "";
    if (S.status === "ok" && items.length && !S.shown) text = tr("no_match");
    else if (S.status === "ok" && !items.length) text = S.data?.ready ? tr("empty") : S.data?.configured ? tr("no_file") : tr("not_set");
    else text = { loading: tr("loading"), offline: tr("offline"), nolocal: tr("local_only") }[S.status] || "";
    // while gallery.json loads: the running man above the text; rebuilt only when the note changes (this runs on every snapshot
    // and must not restart the animation)
    const run = S.status === "loading" && !items.length;
    const sig = (run ? "run:" : "") + text;
    if (note.dataset.sig !== sig) {
      note.dataset.sig = sig;
      note.textContent = text;
      if (run) note.prepend(runner(el, LOADING_PX));
    }
    note.hidden = !text;
  }

  function applyFilter() {
    stop();
    const items = S.data?.items || [];
    const keep = new Set(filterItems(items, { q: S.q, category: S.category, source: S.source, tags: [...S.tags] }).map((i) => i.slug));
    for (const [slug, card] of S.cards) card.hidden = !keep.has(slug) || S.pending.has(slug);
    S.shown = [...keep].filter((slug) => !S.pending.has(slug)).length;
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
    const canDelete = !!data.can_delete;
    const sig = canDelete + JSON.stringify(data.items.map((i) => [i.slug, i.poster, i.preview, i.video, i.prompt, i.category, i.author, i.duration, i.title, i.skill, i.tags, i.sources, i.links, i.post, i.page]));
    S.data = data;
    if (sig !== S.sig) {
      S.sig = sig;
      S.canDelete = canDelete;
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
    root.classList.toggle("mg-dark", isDark());
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

  // a card the owner has put into the chat gets a check mark (the gallery stays open: more can be picked)
  function mark(slug) {
    S.added.add(slug);
    const badge = S.cards.get(slug)?.querySelector(".mg-added");
    if (badge) badge.hidden = false;
  }

  // the card of an example that waits for its undo is out of the grid (on = hide, off = back)
  function hide(slug, on) {
    on ? S.pending.add(slug) : S.pending.delete(slug);
    stop();
    applyFilter();
  }

  update();
  load();
  return { node: root, load, update, stop, mark, hide, focus: () => search.focus(), destroy() { stop(); if (light) closeLightbox(); io?.disconnect(); } };
}
