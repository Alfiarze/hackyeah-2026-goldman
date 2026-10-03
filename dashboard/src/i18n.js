// Tiny i18n: English source strings are the keys; Polish translations below.
// t("Hello {name}", {name}) interpolates. Missing keys fall back to English.
import PL from "./pl.js";

const KEY = "aegis.lang";
let lang = (() => {
  try { return localStorage.getItem(KEY) || (navigator.language || "en").slice(0, 2); } catch { return "en"; }
})() === "pl" ? "pl" : "en";

export function getLang() { return lang; }
export function setLang(l) {
  lang = l;
  try { localStorage.setItem(KEY, l); } catch { /* private mode */ }
  document.documentElement.lang = l;
}
document.documentElement.lang = lang;

export function t(s, vars) {
  let out = (lang === "pl" && PL[s]) || s;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v);
  return out;
}

// reason codes and stage names come from the API as identifiers
export function human(code) {
  if (!code) return "";
  const key = code.toLowerCase().replaceAll("_", " ");
  return t(key);
}
