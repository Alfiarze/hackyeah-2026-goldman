"""Code execution control: block in strict, sandboxed run otherwise, evidence in the response."""
from conftest import ADMIN, APP


async def code_task(client, agent_key="agent-a", agent_id="demo-agent"):
    r = await client.post("/v1/tasks", headers=APP, json={
        "principal": "analyst", "agent_id": agent_id, "profile": "data_task"})
    assert r.status_code == 201, r.text
    b = r.json()
    return b | {"headers": {"Authorization": f"Bearer {agent_key}", "X-Mandate-Lease": b["lease"]}}


async def run_code(client, task, code):
    return await client.post("/v1/tools/code.run/call", headers=task["headers"], json={"args": {"code": code}})


async def test_sandbox_runs_and_returns_evidence(client):
    t = await code_task(client)
    r = await run_code(client, t, "print(2+2)")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["sandbox"]["status"] == "ok"
    assert body["result"]["content"] == "hello from the sandbox"
    assert body["mandate"]["tool_invoked"] is True


async def test_sandbox_reports_blocked_network(client):
    t = await code_task(client)
    r = await run_code(client, t, "# NETWORK\nimport urllib.request")
    assert r.status_code == 200
    assert r.json()["result"]["sandbox"]["network_attempted"] is True


async def test_sandbox_reports_timeout(client):
    t = await code_task(client)
    r = await run_code(client, t, "# LOOP")
    assert r.json()["result"]["sandbox"]["status"] == "timeout"


async def test_code_blocked_in_strict_profile(client):
    await client.put("/admin/policy/profile", headers=ADMIN, json={"profile": "strict"})
    t = await code_task(client)
    r = await run_code(client, t, "print(1)")
    assert r.status_code == 403 and r.json()["mandate"]["rule_id"] == "SBX-001"


async def test_code_not_in_mandate_for_contract_review(client, new_task, call):
    t = await new_task()  # contract_review has no code.run
    r = await call(t, "code.run", code="print(1)")
    assert r.status_code == 403 and r.json()["mandate"]["rule_id"] == "MANDATE-TOOL"


async def test_disabling_control_blocks_code(client):
    await client.patch("/admin/controls/code_execution", headers=ADMIN, json={"enabled": False})
    t = await code_task(client)
    r = await run_code(client, t, "print(1)")
    assert r.status_code == 403 and r.json()["mandate"]["reason_code"] == "CODE_EXECUTION_BLOCKED"
