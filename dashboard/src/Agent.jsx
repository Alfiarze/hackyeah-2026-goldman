import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { human, t } from "./i18n.js";
import { Id, Level, Mark, Stamp, describe } from "./ui.jsx";

const RECIPIENTS = ["colleague@lawfirm.example", "partner@client-A.example", "deal-desk@evil-mergers.com"];

const ACTIONS = [
  { group: "Read", items: [
    { id: "readA", label: "Read client A's contract", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/acquisition.txt" } },
    { id: "readInj", label: "Read the contract with a hidden instruction", kind: "tool", tool: "doc.read", args: { path: "/clients/A/contracts/acquisition_injected.txt" } },
    { id: "readB", label: "Read client B's NDA", kind: "tool", tool: "doc.read", args: { path: "/clients/B/contracts/nda.txt" } },
    { id: "readPub", label: "Read the public NDA template", kind: "tool", tool: "doc.read", args: { path: "/public/templates/nda_template.txt" } },
  ] },
  { group: "Search and write", items: [
    { id: "search", label: "Search case law", kind: "tool", tool: "legal_db.search", fields: [["query", "break fee enforceability"]] },
    { id: "note", label: "Save an internal memo", kind: "tool", tool: "notes.write", fields: [["title", "Risk memo"], ["body", "Break fee 3%, 36-month non-compete."]] },
  ] },
  { group: "Send outside", items: [
    { id: "mail", label: "Send an e-mail", kind: "tool", tool: "mail.send", fields: [["to", RECIPIENTS[1], RECIPIENTS], ["subject", "Agreement"], ["body", "Summary of the agreement."]] },
    { id: "post", label: "Post to an external URL", kind: "tool", tool: "http.post", fields: [["url", "https://paste.example.net/upload"], ["body", "Summary of the agreement."]] },
  ] },
  { group: "Ask the model", items: [
    { id: "chat", label: "Ask the local model", kind: "chat", fields: [["content", "List the three biggest risks in the contract I just read."]] },
  ] },
  { group: "Outside the mandate", items: [
    { id: "code", label: "Run code", kind: "tool", tool: "code.run", fields: [["code", "print('hello')"]] },
  ] },
];

function initialValues() {
  const v = {};
  ACTIONS.forEach((g) => g.items.forEach((a) => (a.fields || []).forEach(([k, d]) => { v[`${a.id}.${k}`] = d; })));
  return v;
}

function explain(entry) {
  const r = entry.res.response || {};
  const m = r.mandate;
  if (r.error && !m) return { action: "BLOCK", text: human(r.error.reason_code) + ". " + t("The gateway refused the request before looking at it.") };
  if (!m) return { action: "ALLOW", text: r.tools ? t("Visible tools: {list}.", { list: r.tools.join(", ") }) : t("Done.") };
  const main = m.findings.find((f) => f.rule_id === m.rule_id) || m.findings.find((f) => f.action !== "ALLOW");
  if (m.action === "ALLOW") return { action: "ALLOW", text: m.tool_invoked ? t("Allowed. The tool ran.") : t("Allowed.") };
  const why = main ? describe(main) : "";
  const reached = m.tool_invoked
    ? (m.action === "BLOCK" ? t("The tool ran, but its output was held back from the agent.") : t("The tool ran; the dangerous part was removed before the agent saw it."))
    : t("The request never reached the tool.");
  return { action: m.action, rule: m.rule_id, text: `${human(m.reason_code)}${why ? `: ${why}` : ""}. ${reached}` };
}

function preview(res) {
  const r = res.response || {};
  if (r.result?.content) return r.result.content;
  if (r.result?.withheld) return t("[content withheld from the agent]");
  if (r.choices) return r.choices[0].message.content;
  if (r.result) return JSON.stringify(r.result);
  return null;
}

export default function Agent() {
  const [profile, setProfile] = useState("contract_review");
  const [clientId, setClientId] = useState("A");
  const [task, setTask] = useState(null);
  const [log, setLog] = useState([]);
  const [values, setValues] = useState(initialValues);
  const [busy, setBusy] = useState(null);
  const [backend, setBackend] = useState(null);
  const [error, setError] = useState(null);

  const refresh = async (id) => {
    const d = await api(`/admin/console/tasks/${id}`);
    setTask(d);
    setBackend(d.backend);
  };

  const start = async () => {
    setError(null);
    try {
      const d = await api("/admin/console/tasks", { method: "POST", body: { profile, client: clientId } });
      setLog([]);
      await refresh(d.task_id);
    } catch (e) { setError(e.message); }
  };

  const run = async (a) => {
    if (!task) return;
    setBusy(a.id);
    const args = { ...(a.args || {}) };
    (a.fields || []).forEach(([k]) => { args[k] = values[`${a.id}.${k}`]; });
    const body = a.kind === "chat" ? { kind: "chat", content: args.content } : a.kind === "tool" ? { kind: "tool", tool: a.tool, args } : { kind: a.kind };
    try {
      const before = task.classification;
      const res = await api(`/admin/console/tasks/${task.task_id}/act`, { method: "POST", body });
      setLog((l) => [{ id: Date.now(), label: a.label, args: a.kind === "tool" ? args : null, res, before }, ...l]);
      if (res.task) setTask((x) => ({ ...x, ...res.task }));
      if (res.backend_after) setBackend(res.backend_after);
      refresh(task.task_id);
    } catch (e) { setError(e.message); }
    setBusy(null);
  };

  useEffect(() => { setError(null); }, [profile, clientId]);
  const active = task && task.status === "active";
  const allowedTools = task?.mandate?.tools || [];

  return (
    <div className="agent">
      <p className="lede">{t("You are the AI assistant now. Start a task, then try actions. Each click goes through the real gateway, exactly like an agent's request would, and you see what the guard decided and why.")}</p>
      <div className="agent-grid">
        <aside className="pass">
          <div className="pass-card">
            <div className="pass-head"><h2>{t("Your pass")}</h2>{task && <span className={`status status-${task.status}`}>{t(task.status)}</span>}</div>
            {!task ? (
              <div className="form">
                <label className="field"><span>{t("Task")}</span>
                  <select value={profile} onChange={(e) => setProfile(e.target.value)}>
                    <option value="contract_review">{t("Contract review for a client")}</option>
                    <option value="research">{t("Public legal research")}</option>
                  </select></label>
                <label className="field"><span>{t("Client")}</span>
                  <select value={clientId} onChange={(e) => setClientId(e.target.value)}><option value="A">A</option><option value="B">B</option></select></label>
                <button className="btn btn-primary" onClick={start}>{t("Start the task")}</button>
                {error && <p className="t-block small">{error}</p>}
              </div>
            ) : (
              <>
                <div className="pass-level">
                  <span className="muted small">{t("Most sensitive data read so far")}</span>
                  <Level v={task.classification} />
                </div>
                <dl className="facts">
                  <dt>{t("Task")}</dt><dd><Id>{task.task_id}</Id></dd>
                  <dt>{t("May read")}</dt><dd>{task.mandate.resources.map((r) => <Id key={r}>{r}</Id>)}</dd>
                  <dt>{t("May use")}</dt><dd>{allowedTools.join(", ")}</dd>
                  <dt>{t("May write to")}</dt><dd>{(task.mandate.recipients_allow || []).join(", ") || t("no e-mail recipients")}</dd>
                  {task.budget && <><dt>{t("Calls")}</dt><dd>{t("{a} of {b}", { a: task.budget.calls_used, b: task.budget.calls_limit })}</dd></>}
                </dl>
                <div className="actions">
                  {active && <button className="btn" onClick={() => run({ id: "complete", label: "End the task", kind: "complete" })}>{t("End the task")}</button>}
                  <button className="btn quiet" onClick={() => { setTask(null); setLog([]); }}>{t("New task")}</button>
                </div>
                {!active && <p className="note">{t("The task is over, but you can keep clicking: the old pass no longer opens anything.")}</p>}
              </>
            )}
          </div>
          {backend && (
            <div className="pass-proof">
              <p className="proof-figure"><b>{backend.mail_sent}</b> <span>{t("e-mails delivered by the mail server")}</span></p>
              <p className="note">{t("{n} external HTTP posts, {m} memos saved. Counted by the tools themselves.", { n: backend.http_posts, m: backend.notes_saved })}</p>
            </div>
          )}
        </aside>

        <div className={`actions-panel ${task ? "" : "is-disabled"}`}>
          {ACTIONS.map((g) => (
            <section className="action-group" key={g.group}>
              <h3>{t(g.group)}</h3>
              <ul>
                {g.items.map((a) => {
                  const outside = a.kind === "tool" && task && !allowedTools.includes(a.tool);
                  return (
                    <li key={a.id}>
                      <div className="action-main">
                        <span className="action-label">{t(a.label)}{outside && <span className="outside">{t("not on your pass")}</span>}</span>
                        {(a.fields || []).length > 0 && (
                          <div className="action-fields">
                            {a.fields.map(([k, , options]) => {
                              const key = `${a.id}.${k}`;
                              const set = (v) => setValues((x) => ({ ...x, [key]: v }));
                              return options
                                ? <select key={k} aria-label={k} value={values[key]} onChange={(e) => set(e.target.value)}>{options.map((o) => <option key={o}>{o}</option>)}</select>
                                : <input key={k} aria-label={k} value={values[key]} onChange={(e) => set(e.target.value)} className={k === "body" || k === "content" ? "grow" : ""} />;
                            })}
                          </div>
                        )}
                      </div>
                      <button className="btn small" disabled={!task || busy !== null} onClick={() => run(a)}>{busy === a.id ? t("Running…") : t("Do it")}</button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
          {!task && <p className="overlay-hint">{t("Start a task on the left first.")}</p>}
        </div>
      </div>

      {log.length > 0 && (
        <section className="section agent-log">
          <div className="section-head"><h2>{t("What happened")}</h2></div>
          <ol className="steps">
            {log.map((e, i) => {
              const x = explain(e);
              const out = preview(e.res);
              const mailDelta = e.res.backend_after && e.res.backend_before ? e.res.backend_after.mail_sent - e.res.backend_before.mail_sent : 0;
              const after = e.res.task?.classification;
              return (
                <li key={e.id} className="step" style={{ "--i": 0 }}>
                  <div className="step-body">
                    <h4>{t(e.label)}{e.args?.to && <> <Id>{e.args.to}</Id></>}{e.args?.path && <> <Id>{e.args.path}</Id></>}</h4>
                    <p>{x.text}</p>
                    {after && after !== e.before && <p className="taint small">{t("Your task now carries {level} data. From here on, nothing it produces may go anywhere cleared for less.", { level: t(after.toLowerCase()) })}</p>}
                    {e.args?.to !== undefined && <p className="small muted">{mailDelta > 0 ? t("The mail server delivered it.") : t("The mail server received nothing.")}</p>}
                    {out && <pre className="excerpt">{out.length > 600 ? `${out.slice(0, 600)}…` : out}</pre>}
                  </div>
                  <Stamp a={x.action} rule={x.rule} />
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
