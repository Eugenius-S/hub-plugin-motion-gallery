// Hub Motion Gallery: what travels with a message. The prompts come from other people's sites and repositories, so they are never added
// by themselves: a plate right above the chat input lists the examples whose tags are in the text (how many characters of every prompt
// go, with the text one click away) and carries the switch "Attach the prompts to the message". The switch is OFF until the owner turns it on
// (it is remembered in this browser); off - only the tags (and nothing else) go with the message.
import { attachList, stripRefs, usedRefs } from "./lib.js";
import { tagsOf } from "./insert.js";

export const KEY = "motion-gallery:attach";

// el - hub.el; tr - the page's translator; onSize() - the plate appeared, went or changed its height (the gallery panel sits above it)
export function createAttach({ el, tr, onSize = () => {} }) {
  let on = false;
  try { on = localStorage.getItem(KEY) === "1"; } catch { /* storage is off */ }
  let form = null, shown = "", open = false;
  const watched = new WeakSet();
  const node = el("div", "mg-attach");
  node.hidden = true;
  node.setAttribute("role", "region");
  node.setAttribute("aria-label", tr("attach_title"));
  document.body.append(node);

  const entries = () => {
    const ta = form?.isConnected ? form.querySelector("textarea") : null;
    const tags = ta ? tagsOf(ta) : null;
    return ta && tags?.size ? attachList(usedRefs(stripRefs(ta.value), tags)) : [];
  };

  function draw(list) {
    const withText = list.filter((x) => x.prompt);
    const chars = withText.reduce((n, x) => n + x.chars, 0);
    const box = el("input");
    box.type = "checkbox";
    box.checked = on;
    box.addEventListener("change", () => {
      on = box.checked;
      try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* storage is off */ }
      refresh();
    });
    const label = el("label", "mg-attach-row");
    label.append(box, el("span", "mg-attach-text", tr("attach_label", { n: withText.length, chars })));
    const more = el("button", "mg-attach-more", tr(open ? "attach_hide" : "attach_show"));
    more.type = "button";
    more.setAttribute("aria-expanded", String(open));
    more.addEventListener("click", () => { open = !open; shown = ""; refresh(); });
    const head = el("div", "mg-attach-head");
    head.append(label, more);
    node.replaceChildren(head, el("div", "mg-attach-hint", tr(on ? "attach_on" : "attach_off")));
    if (open) {
      const rows = el("div", "mg-attach-list");
      for (const x of list) {
        const row = el("div", "mg-attach-item");
        const cap = x.prompt ? tr("attach_chars", { n: x.chars }) + (x.cut ? " " + tr("attach_cut", { n: x.cut }) : "") : tr("attach_none");
        row.append(el("div", "mg-attach-cap", x.tag + " - " + cap));
        if (x.prompt) row.append(el("pre", "mg-attach-pre", x.prompt.slice(0, x.chars)));
        rows.append(row);
      }
      node.append(rows);
    }
  }

  function place() {
    const r = form.getBoundingClientRect();
    node.style.left = r.left + "px";
    node.style.width = r.width + "px";
    node.style.bottom = Math.max(0, innerHeight - r.top + 6) + "px";
  }

  // redrawn only when something changed (an opened list must not close under the cursor)
  function refresh() {
    const list = entries();
    const sig = JSON.stringify([on, open, list.map((x) => [x.tag, x.chars, x.cut])]);
    const before = height();
    if (!list.length) {
      if (!node.hidden) { node.hidden = true; shown = ""; }
    } else {
      if (sig !== shown) { draw(list); shown = sig; }
      node.hidden = false;
      place();
    }
    if (height() !== before) onSize();
  }

  const height = () => (node.hidden ? 0 : node.offsetHeight + 6);
  setInterval(() => { if (form) refresh(); }, 500);
  addEventListener("resize", () => { if (form && !node.hidden) place(); });

  return {
    node,
    allowed: () => on,
    height,
    // the input `form` the plate follows (the one a tag was put into last)
    watch(f) {
      form = f;
      const ta = f?.querySelector("textarea");
      if (ta && !watched.has(ta)) { watched.add(ta); ta.addEventListener("input", refresh); }
      refresh();
    },
  };
}
