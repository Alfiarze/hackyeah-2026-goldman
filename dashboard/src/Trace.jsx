// One request through the gateway, drawn as a pipeline: what the agent sent, each check it passed or failed,
// whether the tool or model actually ran, and what the agent got back. Used by scenarios and "Be the agent".
import React from "react";
import { human, t } from "./i18n.js";
import { Id, Mark, Stamp, describe, num, sandboxLine } from "./ui.jsx";

export const STAGES = [
  { id: "mandate", label: "Pass", hint: "Is this tool, file or recipient on the task's mandate?" },
  { id: "signatures", label: "Known attacks", hint: "Does it match a signature from the attack feed?" },
  { id: "deterministic", label: "Patterns", hint: "Personal data, passwords and keys, injection phrases." },
  { id: "data_flow", label: "Data flow", hint: "May data this confidential go to this destination?" },
  { id: "semantic", label: "AI review", hint: "A model scores the text for manipulation." },
  { id: "budget", label: "Budget", hint: "Tokens and calls are reserved before anything runs." },
  { id: "execute", label: "Runs", hint: "Only now is the tool or model actually called." },
  { id: "output", label: "Result check", hint: "The answer is checked before the agent sees it." },
];
const IDX = Object.fromEntries(STAGES.map((s, i) => [s.id, i]));
const stageOf = (s) => (s === "model_call" ? "execute" : s);

// Works out, from a decision, which stage stopped or changed the request and which stages never ran.
export function stageStates(decision, ran) {
  const states = STAGES.map(() => "pass");
  if (!decision) return states.map(() => "na");
  const timings = decision.timings || {};
  const hits = (decision.findings || []).filter((f) => f.action !== "ALLOW");
  const afterRun = (f) => ran && ["tool_results", "model_output", "file_content"].includes(f.detail?.target);
  let stop = -1;
  for (const f of hits) {
    const i = afterRun(f) || (ran && decision.action === "BLOCK" && f.action === "BLOCK") ? IDX.output : IDX[stageOf(f.stage)] ?? IDX.deterministic;
    if (f.action === "BLOCK") { states[i] = "block"; stop = stop === -1 ? i : Math.min(stop, i); }
    else if (states[i] !== "block") states[i] = "redact";
  }
  STAGES.forEach((s, i) => {
    if (stop !== -1 && i > stop) states[i] = "skip";
    else if (states[i] === "pass" && i < IDX.execute && timings[s.id] === undefined && s.id !== "mandate") states[i] = "na";
  });
  if (stop === -1 || stop > IDX.execute) states[IDX.execute] = ran ? "pass" : (decision.action === "BLOCK" ? "skip" : "pass");
  return states;
}

const STATE_WORD = { pass: "passed", redact: "masked", block: "stopped", skip: "not reached", na: "not needed" };

export function Pipeline({ decision, ran, animate = false }) {
  const states = stageStates(decision, ran);
  const last = states.reduce((acc, s, i) => (s === "skip" ? acc : i), 0);
  return (
    <ol className={`pipe ${animate ? "is-animated" : ""}`} aria-label={t("Checks in order")}>
      {STAGES.map((s, i) => {
        const ms = decision?.timings?.[s.id] ?? (s.id === "execute" ? decision?.timings?.model_call : undefined);
        return (
          <li key={s.id} className={`pipe-node pipe-${states[i]}`} style={{ "--i": i, "--last": last }} title={t(s.hint)}>
            <span className="pipe-dot" aria-hidden="true" />
            <span className="pipe-label">{t(s.label)}</span>
            <span className="pipe-state">{t(STATE_WORD[states[i]])}{ms !== undefined && states[i] !== "skip" ? ` · ${num(ms, 1)} ms` : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Args({ args }) {
  const entries = Object.entries(args || {});
  if (!entries.length) return null;
  return (
    <dl className="args">
      {entries.map(([k, v]) => (
        <React.Fragment key={k}><dt>{k}</dt><dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd></React.Fragment>
      ))}
    </dl>
  );
}

const CHANNEL = { tool: "calls the tool", model: "asks the model", mcp: "calls the MCP server", registry: "registers the model" };

function Response({ response, ran, decision }) {
  if (!response) return null;
  if (response.kind === "withheld") return <p className="resp resp-block">{t("[content withheld from the agent]")}</p>;
  if (response.kind === "error") return <p className="resp resp-block">{t("Refused")}: <Id>{response.text}</Id></p>;
  if (!response.text) return null;
  return (
    <div className="resp">
      <pre className="excerpt">{response.text}</pre>
      {!ran && decision?.action === "BLOCK" && <p className="small muted">{t("Nothing ran; this is the gateway's refusal.")}</p>}
    </div>
  );
}

// A full step: who did what, the pipeline, why it was decided so, and what came back.
export function TraceStep({ n, title, why, request, decision, response, ran, action, rule, sandbox, extra, animate }) {
  const fired = (decision?.findings || []).filter((f) => f.action !== "ALLOW");
  const act = action || decision?.action;
  return (
    <article className={`trace ${act ? `trace-${act.toLowerCase()}` : ""} ${animate ? "is-animated" : ""}`}>
      <header className="trace-head">
        {n !== undefined && <span className="trace-n">{String(n).padStart(2, "0")}</span>}
        <div className="trace-title">
          <h3>{t(title)}</h3>
          {why && <p>{t(why)}</p>}
        </div>
        {act && <Stamp a={act} rule={rule || decision?.rule_id} />}
      </header>

      {request && (
        <div className="trace-req">
          <span className="label">{t("The agent {what}", { what: t(CHANNEL[request.channel] || "sends") })} <Id>{request.target}</Id></span>
          <Args args={request.args} />
        </div>
      )}

      {decision && <Pipeline decision={decision} ran={ran} animate={animate} />}

      {fired.length > 0 && (
        <ul className="trace-why">
          {fired.map((f, i) => (
            <li key={i}><Mark a={f.action} /> <span><b>{human(f.reason_code)}</b> <span className="muted">{describe(f)}</span></span> <Id>{f.rule_id}</Id></li>
          ))}
        </ul>
      )}

      {(decision || ran !== undefined) && request?.channel !== "registry" && (
        <p className={`trace-ran ${ran ? "is-ran" : "is-not"}`}>
          {ran ? (act === "BLOCK" ? t("The tool ran, but its output was held back from the agent.") : t("It ran.")) : t("It never ran: the tool or model was not called.")}
        </p>
      )}
      {sandbox && <p className="small sandbox-line">{sandboxLine(sandbox, true)}</p>}
      {extra}
      {response && <><span className="label">{t("What the agent got back")}</span><Response response={response} ran={ran} decision={decision} /></>}
    </article>
  );
}
