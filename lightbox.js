// Hub Motion Gallery: the lightbox - one example full screen, like a photo viewer. The full video with sound and the
// controls (seeking), the caption and the author; Left/Right step through the list, Escape and the cross close.
// It sits above the page and above the gallery overlay; while it is open it takes the keys (capture phase on window), so
// Escape closes only the lightbox and the gallery over a chat stays.
import { linksOf, lightVideo, mediaUrl, metaLine, stepIndex } from "./lib.js";
import { runnerDisc } from "./loader.js";

let current = null;

// props: el (hub.el), tr, base() -> process address, items (the list to step through), index, onClose?,
//        onDelete(item)? - the example is taken out of the gallery (with the undo plate, see main.js): the lightbox drops it
//        from its list and shows the next one (the previous one at the end, closes when none is left)
// returns { box, close }; a new one closes the one that is open
export function openLightbox({ el, tr, base, items, index, onClose, onDelete = null }) {
  current?.close();
  const list = items.slice();
  if (!list.length) return null;
  let at = stepIndex(index, 0, list.length);
  const opener = document.activeElement;
  const ico = (name) => { const s = el("span", "mg-ico mg-ico-" + name); s.setAttribute("aria-hidden", "true"); return s; };
  const button = (cls, name, label) => {
    const b = el("button", cls);
    b.type = "button";
    b.append(ico(name));
    b.title = label;
    b.setAttribute("aria-label", label);
    return b;
  };

  const box = el("div", "mg-lb");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.tabIndex = -1;
  const x = button("mg-lb-btn mg-lb-x", "close", tr("close"));
  const prev = button("mg-lb-btn mg-lb-nav mg-lb-prev", "chevron", tr("prev"));
  const next = button("mg-lb-btn mg-lb-nav mg-lb-next", "chevron", tr("next"));
  const stage = el("div", "mg-lb-stage");
  const err = el("div", "mg-lb-err");
  err.setAttribute("role", "status");
  err.hidden = true;
  const cap = el("div", "mg-lb-cap");
  const count = el("div", "mg-lb-count");
  const title = el("div", "mg-lb-title");
  const meta = el("div", "mg-lb-meta");
  // the prompt: a block that opens on demand (the caption stays short), the text inside scrolls
  const prompt = el("details", "mg-lb-prompt");
  const promptHead = el("summary", "mg-lb-sum", tr("prompt"));
  const text = el("div", "mg-lb-text");
  prompt.append(promptHead, text);
  // the row under the caption: "To the source" (only when the example has a link) and "Delete" (only when the process allows it)
  const actions = el("div", "mg-lb-actions");
  const link = el("a", "mg-lb-act mg-lb-link", tr("to_source"));
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const del = onDelete ? el("button", "mg-lb-act mg-lb-del", tr("delete")) : null;
  if (del) del.type = "button";
  actions.append(link, ...(del ? [del] : []));
  cap.append(count, title, meta, prompt, actions);
  box.append(stage, cap, prev, next, x);
  let video = null;

  function release() {
    stage.querySelector(".mg-disc")?.remove();
    if (!video) return;
    video.pause();
    video.removeAttribute("src");
    video.load();   // lets go of the connection
    video.remove();
    video = null;
  }

  function show(i) {
    at = i;
    const item = list[at];
    release();
    err.hidden = true;
    const src = mediaUrl(base(), lightVideo(item));
    video = document.createElement("video");
    video.className = "mg-lb-video";
    video.controls = true;
    video.playsInline = true;
    video.preload = "auto";
    video.poster = mediaUrl(base(), item.poster);
    video.setAttribute("aria-label", item.title || item.slug);
    const v = video;
    const unwait = () => stage.querySelector(".mg-disc")?.remove();
    v.addEventListener("loadeddata", unwait);
    v.addEventListener("error", () => { unwait(); if (video === v) { err.textContent = tr("video_failed"); err.hidden = false; } });
    stage.prepend(video);
    if (src) { stage.append(runnerDisc(el)); v.src = src; v.play().catch(() => {}); }   // the click that opened it allows sound
    else { err.textContent = tr("no_video"); err.hidden = false; }
    box.setAttribute("aria-label", [item.title, metaLine(item)].filter(Boolean).join(" · ") || item.slug);
    count.textContent = tr("count", { n: at + 1, total: list.length });
    title.textContent = item.title || "";
    title.hidden = !item.title;
    meta.textContent = metaLine(item);
    meta.hidden = !meta.textContent;
    const body = item.prompt || item.skill?.desc || "";
    text.textContent = body;
    prompt.hidden = !body;
    prompt.open = false;
    const links = linksOf(item);
    link.hidden = !links.length;
    if (links.length) {
      link.href = links[0].url;
      link.title = [tr("open_post"), links[0].source].filter(Boolean).join(" · ");
    }
    prev.disabled = at <= 0;
    next.disabled = at >= list.length - 1;
  }

  const go = (d) => { const i = stepIndex(at, d, list.length); if (i !== at) show(i); };

  // the cross-out: the owner's handler hides the card and starts the undo; here the entry leaves the list at once
  function remove() {
    if (!onDelete) return;
    const item = list[at];
    list.splice(at, 1);
    onDelete(item);
    if (!list.length) return close();
    show(Math.min(at, list.length - 1));
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); return close(); }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      e.stopPropagation();
      return go(e.key === "ArrowLeft" ? -1 : 1);
    }
    if (e.key === " " && !e.target.closest?.("button, video, a, summary")) { e.preventDefault(); if (video) (video.paused ? video.play().catch(() => {}) : video.pause()); return; }
    if (e.key === "Tab") {   // the focus stays inside: the buttons, the video controls, the link
      const ring = [x, prev, next, video, promptHead, link, del].filter((n) => n && !n.hidden && !n.disabled);
      if (!ring.length) return e.preventDefault();
      const i = ring.indexOf(document.activeElement);
      e.preventDefault();
      ring[i < 0 ? 0 : (i + (e.shiftKey ? -1 : 1) + ring.length) % ring.length].focus();
    }
  }

  function close() {
    if (current?.box !== box) return;
    current = null;
    removeEventListener("keydown", onKey, true);
    removeEventListener("hashchange", close);
    release();
    box.remove();
    if (opener?.isConnected && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    onClose?.();
  }

  x.addEventListener("click", close);
  del?.addEventListener("click", remove);
  prev.addEventListener("click", () => go(-1));
  next.addEventListener("click", () => go(1));
  box.addEventListener("click", (e) => { if (e.target === box || e.target === stage) close(); });   // a click beside the picture
  addEventListener("keydown", onKey, true);
  addEventListener("hashchange", close);
  document.body.append(box);
  current = { box, close };
  show(at);
  box.focus({ preventScroll: true });
  return current;
}

export const closeLightbox = () => current?.close();
