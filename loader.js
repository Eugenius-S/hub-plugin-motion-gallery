// Hub Motion Gallery: the running man (Icons8 Running, ios7) shown while something loads: gallery.json, a poster, a video.
// The animated PNG lives in the plugin (never fetched from a foreign address); with reduced motion it is one still frame of the same icon.
const FILE = (still) => new URL(still ? "./loader/runner.png" : "./loader/runner-anim.png", import.meta.url).href;
const calm = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// <img class="mg-run"> (decorative); the caller removes it when the wait is over; `size` in px (48-64 for a page, less on a card)
export function runner(el, size = 56) {
  const img = el("img", "mg-run");
  img.alt = "";
  img.decoding = "async";
  img.draggable = false;
  img.src = FILE(calm());
  img.style.width = img.style.height = size + "px";
  img.setAttribute("aria-hidden", "true");
  return img;
}

// the dark theme of the hub paints text light: the black icon is inverted (the hub sets color-scheme on the root)
export const isDark = () => getComputedStyle(document.documentElement).colorScheme.split(/\s+/).includes("dark");
