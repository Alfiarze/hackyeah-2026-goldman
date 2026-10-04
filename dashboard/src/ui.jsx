import React, { useMemo, useState } from "react";
import { api } from "./api.js";
import { human, t } from "./i18n.js";
export const LEVELS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"];
export const WORD = { ALLOW: "Allowed", REDACT: "Redacted", BLOCK: "Blocked", CONTAINED: "Contained", PENDING: "Awaiting approval" };
export const locale = () => "en-GB";
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
  if (d.limit_per_minute) return t("{scope}: {n} requests this minute, the limit is {limit}", { scope: d.scope, n: d.count, limit: d.limit_per_minute });
  if (d.threshold && d.window_seconds) return t("{n} blocked requests in the last {s} s (threshold {th}): the task is cut off", { n: d.blocked_recently, s: d.window_seconds, th: d.threshold });
  if (d.expected && d.got) return t("{file}: expected sha256 {e}…, got {g}…", { file: d.file, e: d.expected.slice(0, 12), g: d.got.slice(0, 12) });
  if (d.approval_id) return t("waits for a person's decision ({id})", { id: d.approval_id });
  if (d.kinds) return t("found {list}", { list: d.kinds.map((k) => t(k.replace("_", " "))).join(", ") }) + (d.items?.length ? `: ${d.items[0]}` : "");
  if (d.entities) return t("found {list}", { list: d.entities.map(human).join(", ") });
  if (d.types) return t("found {list}", { list: d.types.map(human).join(", ") });
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

const SBX = { ok: "exited cleanly", nonzero_exit: "exited with an error", timeout: "killed at the time limit",
  oom: "killed at the memory limit", runner_error: "could not run", skipped: "skipped" };

export function sandboxLine(sb, host = false) {
  const status = t(SBX[sb.status] || sb.status);
  const ms = Math.round(sb.duration_ms);
  const net = sb.network_attempted ? t("; network was blocked") : "";
  return host
    ? t("Ran in an isolated container: {status}, {ms} ms{net}. Host untouched.", { status, ms, net })
    : t("Sandbox: {status}, {ms} ms{net}", { status, ms, net });
}

// The Aegis mark: guilloche rings drawn as fine intaglio lines (same as the landing page).
export function Rosette({ size = 30, className = "" }) {
  const groups = useMemo(() => {
    const ring = (base, amp, lobes, phase) => {
      const pts = [];
      for (let i = 0; i <= 900; i++) {
        const a = (i / 900) * Math.PI * 2;
        const rad = base + amp * Math.sin(lobes * a + phase);
        pts.push(`${(32 + rad * Math.cos(a)).toFixed(2)},${(32 + rad * Math.sin(a)).toFixed(2)}`);
      }
      return `M${pts.join("L")}Z`;
    };
    return {
      outer: [0, 1, 2, 3].map((k) => ring(26, 3.4, 12, (k * Math.PI) / 6)),
      middle: [0, 1, 2].map((k) => ring(17, 4.2, 9, (k * Math.PI) / 4.5)),
      inner: [0, 1].map((k) => ring(8, 2.6, 7, k * Math.PI)),
    };
  }, []);
  return (
    <svg className={`rosette ${className}`} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      {Object.entries(groups).map(([name, ds]) => (
        <g key={name} className={`r-${name}`}>{ds.map((d, i) => <path key={i} d={d} />)}</g>
      ))}
    </svg>
  );
}


// Approve or deny a held high-risk call (policy: approvals).
export function ApprovalButtons({ id, onDone }) {
  const [busy, setBusy] = useState(false);
  const decide = async (verdict) => {
    setBusy(true);
    try { await api(`/admin/approvals/${id}/${verdict}`, { method: "POST" }); onDone?.(verdict); } finally { setBusy(false); }
  };
  return (
    <span className="actions">
      <button className="btn small btn-primary" disabled={busy} onClick={() => decide("approve")}>{t("Approve this call")}</button>
      <button className="btn small btn-danger" disabled={busy} onClick={() => decide("deny")}>{t("Deny")}</button>
    </span>
  );
}


// Minimal Markdown for model answers: headings, lists, code blocks, bold, italic, inline code, links.
// Builds React elements only (never innerHTML), so model output cannot inject markup.
function inline(text, key = "i") {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0, m, n = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0], k = `${key}-${n++}`;
    if (tok.startsWith("`")) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={k}>{inline(tok.slice(2, -2), k)}</strong>);
    else if (tok.startsWith("[")) out.push(<a key={k} href={m[2]} target="_blank" rel="noopener noreferrer">{tok.slice(1, tok.indexOf("]"))}</a>);
    else out.push(<em key={k}>{inline(tok.slice(1, -1), k)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }) {
  const lines = String(text || "").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      i++;
      blocks.push(<pre key={blocks.length} className="md-pre"><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { const Tag = `h${Math.min(6, h[1].length + 2)}`; blocks.push(<Tag key={blocks.length} className="md-h">{inline(h[2])}</Tag>); i++; continue; }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "")); i++; }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={blocks.length} className="md-list">{items.map((it, j) => <li key={j}>{inline(it, `l${j}`)}</li>)}</List>);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*+]|\d+[.)])\s+)/.test(lines[i])) { para.push(lines[i]); i++; }
    blocks.push(<p key={blocks.length}>{para.flatMap((p, j) => (j ? [<br key={`b${j}`} />, ...inline(p, `p${j}`)] : inline(p, `p${j}`)))}</p>);
  }
  return <div className="md">{blocks}</div>;
}
