import React from "react";
import { getLang, human, t } from "./i18n.js";
export const LEVELS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"];
export const WORD = { ALLOW: "Allowed", REDACT: "Redacted", BLOCK: "Blocked" };
export const locale = () => (getLang() === "pl" ? "pl-PL" : "en-GB");
export const num = (n, d = 0) => (n === null || n === undefined ? "—" : Number(n).toLocaleString(locale(), { maximumFractionDigits: d }));
export const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString(locale()) : "");
export const Id = ({ children }) => (children ? <span className="id">{children}</span> : null);
export const lvl = (v) => t(v.toLowerCase());

export function Mark({ a }) {
  if (!a) return null;
  return <span className={`mark mark-${a.toLowerCase()}`}>{t(WORD[a] || a)}</span>;
}

export function Stamp({ a, rule }) {
  if (!a) return null;
  return (
    <span className={`stamp stamp-${a.toLowerCase()}`}>
      <span className="stamp-word">{t(WORD[a])}</span>
      {rule && <span className="stamp-rule">{rule}</span>}
    </span>
  );
}

export function Level({ v }) {
  const i = LEVELS.indexOf(v);
  return <span className={`level level-${i}`} title={lvl(v)}><i style={{ "--n": i + 1 }} />{lvl(v)}</span>;
}


export function describe(f) {
  const d = f.detail || {};
  if (d.entities) return t("found {list}", { list: d.entities.join(", ") });
  if (d.types) return t("found {list}", { list: d.types.join(", ") });
  if (d.patterns) return t("matched {list}", { list: d.patterns.map(human).join(", ") });
  if (d.risk !== undefined) return t("risk {risk} from {backend}", { risk: d.risk, backend: t(d.backend) }) + (d.reason ? `: ${d.reason}` : "");
  if (d.task_classification) return t("{level} data cannot go to {sink} (cleared for {clearance})", { level: lvl(d.task_classification), sink: d.sink, clearance: lvl(d.sink_clearance) });
  if (d.tool && d.allowed) return t("{tool} is not on this task's pass", { tool: d.tool });
  if (d.recipient !== undefined) return t("{r} is not an allowed recipient for this task", { r: d.recipient || "?" });
  if (d.resource !== undefined) return t("{p} is outside the files this task may read", { p: d.resource });
  if (d.model) return t("model {m} is not approved", { m: d.model });
  if (d.dimension) return t("the {scope} budget has no room for this ({dim})", { scope: d.scope, dim: t(d.dimension) });
  if (d.tool) return t("{tool} is quarantined", { tool: d.tool });
  if (d.title) return d.title;
  return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
}
