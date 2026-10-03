# aegis-sdk

Python client for the Aegis control gateway. It depends only on `httpx` and has sync and async clients.

```bash
pip install ./sdk            # or: pip install "./sdk[openai]" for the OpenAI drop-in
```

## Use it

```python
from aegis_sdk import Aegis, Blocked

aegis = Aegis("http://localhost:8000", app_key="dev-app-key", agent_key="agent-key-demo")

# The trusted app creates the task. The agent gets a lease bound to it.
with aegis.create_task(principal="lawyer_anna", agent_id="demo-agent",
                       profile="contract_review", params={"client": "A"}) as task:
    doc = task.call("doc.read", path="/clients/A/contracts/acquisition.txt")
    answer = task.chat(f"List the three biggest risks:\n{doc.content}")
    task.call("notes.write", title="Risk memo", body=answer.content)

    try:
        task.call("mail.send", to="partner@client-A.example", subject="Contract", body=answer.content)
    except Blocked as e:
        print(e.rule_id, e.reason_code, e.tool_invoked)   # IFC-001 DATA_FLOW_VIOLATION False
# Leaving the block completes the task, and its lease stops working.
```

Async has the same surface:

```python
from aegis_sdk import AsyncAegis

async with AsyncAegis("http://localhost:8000", app_key="...", agent_key="...") as aegis:
    task = await aegis.create_task(principal="analyst", agent_id="demo-agent", profile="data_task")
    result = await task.run_code("print(sum(range(10)))")   # runs in the gateway's sandbox
    print(result.content, result.sandbox["status"])
```

## What you get

| Call | Goes to |
|---|---|
| `aegis.create_task(...)` | `POST /v1/tasks`, called by the trusted app (`app_key`) |
| `aegis.task(task_id, lease)` | attaches to a task whose lease the app handed over |
| `task.chat(prompt, model=, max_tokens=, system=)` | `POST /v1/chat/completions` |
| `task.call(tool, **args)` / `task.tool(name)` | `POST /v1/tools/{tool}/call` |
| `task.run_code(code)` | `code.run` in the sandbox |
| `task.mcp_tools()` / `task.mcp_call(name, **args)` | `POST /mcp`, JSON-RPC through the MCP proxy |
| `task.delegate(agent_id=, agent_key=, tools=, ...)` | `POST /v1/tasks/{id}/delegate`; the child mandate must be a subset of the parent's |
| `task.complete()` / `with task:` | ends the task and kills the lease |
| `task.info()` | the mandate, the classification read so far, the status |
| `task.openai_client()` | an `openai.OpenAI` client whose calls go through Aegis |
| `task.call_approved(tool, timeout=, **args)` | like `call`, but waits until a person approves the call (then it runs once) |
| `aegis.register_model(name, source_url=, files=, packages=)` | `POST /v1/models/register`: supply-chain check, weights and LoRA compared with the sha256 pinned in the policy |
| `aegis.request(method, path, task=)` | any endpoint without a helper yet; errors still map to the exceptions below |

## Admin client

```python
from aegis_sdk import Admin

admin = Admin("http://localhost:8000", admin_key="dev-admin-key")
for a in admin.approvals():                 # pending people's approvals (APPROVAL-001)
    admin.approve(a["id"])                  # or admin.deny(...)
admin.check("Mój PESEL to 44051401359").redacted        # dry run: 'Mój PESEL to [REDACTED:PESEL]'
admin.check_document(open("umowa.pdf", "rb").read(), "umowa.pdf").hidden_parts   # metadata, XMP, comments...
admin.update_policy(new_yaml)               # broken YAML -> AegisError(422), the previous version stays active
admin.rollback(seq); admin.revoke_task(task_id); admin.export_audit("csv")
admin.request("GET", "/admin/memory")       # anything not wrapped yet
```

`AsyncAdmin` has the same methods.

## Does the SDK keep up with the gateway?

New rules, reason codes and findings need no SDK change: the SDK carries the gateway's decision as it is
(`e.decision.rule_id`, `findings`, `detail`). Code is needed only for a new endpoint (until then, `request()`
reaches it) or for a new exception type. `tests/test_sdk.py::test_sdk_covers_every_agent_endpoint` fails when a
`/v1` or `/mcp` route has no SDK method, so a gap cannot slip through.

Every response carries a `Decision` with these fields: `action` (`ALLOW` / `REDACT` / `BLOCK`), `rule_id`,
`reason_code`, `stage`, `policy_version`, `tool_invoked`, `findings`, `timings`.

## Errors

| Exception | When |
|---|---|
| `Rejected` | Bad agent key, or a lease that is forged, belongs to another agent, or is expired, revoked or completed. The call is refused before evaluation (401/403/404). |
| `Blocked` | Policy said no. `e.decision` holds the rule and the evidence (403). |
| `BudgetExceeded` | A budget scope had no room (429). Subclass of `Blocked`. |
| `RateLimited` | Too many requests this minute, or the task was cut off by the circuit breaker (429). Subclass of `BudgetExceeded`. |
| `ApprovalRequired` | The call waits for a person's approval; `approval_id` names it. Retry the identical call once approved. Subclass of `Blocked`. |
| `Unavailable` | The model or tool was unreachable and the gateway failed closed (502). Subclass of `Blocked`. |

The agent never holds tool credentials. Tools run behind the gateway, which holds them.
