// The console is English-only. t() stays as the single place for interpolation:
// t("Hello {name}", {name}) -> "Hello Anna".

export function getLang() { return "en"; }
document.documentElement.lang = "en";

export function t(s, vars) {
  let out = s;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v);
  return out;
}

// reason codes and stage names come from the API as identifiers
export function human(code) {
  if (!code) return "";
  return code.toLowerCase().replaceAll("_", " ");
}
