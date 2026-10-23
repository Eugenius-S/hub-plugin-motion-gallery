// Hub Motion Gallery: the running man (Icons8 Running, ios7) shown while something loads: gallery.json, a poster, a video.
// The animated PNG lives in the plugin (never fetched from a foreign address); with reduced motion it is one still frame of the same icon.
const FILE = (still) => new URL(still ? "./loader/runner.png" : "./loader/runner-anim.png", import.meta.url).href;
const calm = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// The size is that of the palette icon of Hub Design (its "Style" button, the menu): the silhouette is ~94% of the 100 px picture,
// 20 px gives ~19 px of runner against ~17-18 px of the palette. The same everywhere: under the list, on a card, in the lightbox.
export const RUNNER_PX = 20;

// <img class="mg-run"> (decorative); the caller removes it when the wait is over
export function runner(el, size = RUNNER_PX) {
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
