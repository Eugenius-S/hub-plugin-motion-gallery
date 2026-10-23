// Hub Motion Gallery: UI language. English by default, Russian when the hub language is Russian; any other language -> English.
// The language is read at USE time (never at module load): main.js registers a source (`() => hub.lang`) in register().
let source = () => "en";

export const setLangSource = (fn) => { source = typeof fn === "function" ? fn : () => "en"; };

export const baseLang = (lang) => String(lang || "").split("-")[0].toLowerCase();

export function pick(STR, lang) {
  const base = baseLang(lang);
  return Object.hasOwn(STR, base) ? base : "en";
}

// each module keeps its own table `{en: {...}, ru: {...}}`; `{name}` is a placeholder, replaced in one pass
export function makeT(STR) {
  return (key, vars) => {
    const text = (STR[pick(STR, source())] || {})[key] ?? STR.en[key] ?? key;
    return vars ? String(text).replace(/\{(\w+)\}/g, (m, k) => (Object.hasOwn(vars, k) ? vars[k] : m)) : text;
  };
}

// the hub language as set now ("ru", "en-GB" -> "en"); read at use time
export const currentLang = () => baseLang(source()) || "en";
