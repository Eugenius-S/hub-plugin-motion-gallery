// Hub Motion Gallery: keeps the hover of the menu icon going when the page rebuilds the menu. The hub puts new nodes into the ☰ menu
// on every snapshot, so the icon under a held mouse is a brand-new element each time: without this its filled layer fades in again
// with a bounce and the rings are born in the center again (a visible jerk of the loop every second or two). The new node takes the
// hover look at once (data-mgi-resume, navicon.css) and the start time of the rings of the node it replaces, so the loop does not
// notice. The button in the input is never rebuilt, it needs nothing.
const OURS = '.ext-icon[style*="motion-gallery/icon.svg"], .mg-oi';
const RESUME = "data-mgi-resume";
const GRACE = 400;      // ms between the removal of the old icon and the start of the rings of the new one that still counts as the same hover
const RELEASE = 600;    // ms the forced look may last when the pointer is not over the new icon after all
const isRing = (a) => String(a.animationName || "").startsWith("mgi-ring");

export function keepRings(doc = document) {
  let carry = null;   // {start, at}: ring start time of the icon that was just removed
  const rest = (n) => (n.nodeType === 1 ? (n.matches(OURS) ? [n] : [...n.querySelectorAll(OURS)]) : []);
  const release = (icon, t0) => {
    const row = icon.closest(".srow.nav, .mg-open");
    if (!icon.isConnected || !row || row.matches(":hover, :focus-visible, .on") || performance.now() - t0 > RELEASE) icon.removeAttribute(RESUME);
    else requestAnimationFrame(() => release(icon, t0));
  };
  // the start of the rings is read here, and the inherited one set here: the event comes before the style of that frame is painted
  doc.addEventListener("animationstart", (e) => {
    if (!String(e.animationName).startsWith("mgi-ring") || !e.target.getAnimations) return;
    const rings = e.target.getAnimations({ subtree: true }).filter(isRing);
    if (!rings.length || rings[0].startTime == null) return;
    if (carry && performance.now() - carry.at < GRACE) rings.forEach((a) => { a.startTime = carry.start; });
    e.target.__mgiStart = rings[0].startTime;
  }, true);
  new MutationObserver((records) => {
    for (const r of records) for (const n of r.removedNodes) for (const i of rest(n)) if (i.__mgiStart != null) carry = { start: i.__mgiStart, at: performance.now() };
    if (!carry || performance.now() - carry.at >= GRACE) return;
    for (const r of records) for (const n of r.addedNodes) for (const i of rest(n)) {
      if (i.__mgiStart != null || i.hasAttribute(RESUME)) continue;
      i.setAttribute(RESUME, "");
      // the rings exist as soon as the style is computed (getAnimations does it now): set the old phase before the first frame is drawn
      for (const a of i.getAnimations({ subtree: true }).filter(isRing)) a.startTime = carry.start;
      i.__mgiStart = carry.start;
      requestAnimationFrame(() => release(i, performance.now()));
    }
  }).observe(doc.body, { childList: true, subtree: true });
}
