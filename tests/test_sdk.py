"""The Python SDK against the real gateway app (async client over ASGI; the sync client shares the logic)."""
import httpx
import pytest

from aegis_sdk import AsyncAegis, Blocked, BudgetExceeded, Rejected
from aegis_sdk.client import _check

CONTRACT = "/clients/A/contracts/acquisition.txt"


@pytest.fixture
async def sdk(app):
    client = AsyncAegis("http://gw", app_key="test-app", agent_key="agent-a",
                        transport=httpx.ASGITransport(app=app))
    yield client
    await client.aclose()


async def new_task(sdk, profile="contract_review"):
    return await sdk.create_task(principal="lawyer_anna", agent_id="demo-agent", profile=profile,
                                 params={"client": "A"} if profile == "contract_review" else {})


async def test_task_tool_and_chat(sdk):
    task = await new_task(sdk)
    doc = await task.call("doc.read", path=CONTRACT)
    assert doc.decision.allowed and "SHARE PURCHASE AGREEMENT" in doc.content
    answer = await task.chat("summarise", model="mock/echo")
    assert answer.content and answer.decision.action in ("ALLOW", "REDACT")
    info = await task.info()
    assert info.classification == "CONFIDENTIAL" and info.mandate["case"] == "A"


async def test_blocked_raises_with_decision(sdk, backend):
    task = await new_task(sdk)
    await task.call("doc.read", path=CONTRACT)
    with pytest.raises(Blocked) as exc:
        await task.call("mail.send", to="partner@client-A.example", subject="s", body="b")
    assert exc.value.rule_id == "IFC-001" and exc.value.tool_invoked is False
    assert exc.value.decision.blocked and backend.counters["mail.send"] == 0


async def test_bound_tool_and_mcp(sdk):
    task = await new_task(sdk)
    search = task.tool("legal_db.search")
    assert (await search(query="break fee")).decision.allowed
    names = {t["name"] for t in await task.mcp_tools()}
    assert "doc.read" in names and "code.run" not in names


async def test_sandbox_via_sdk(sdk):
    task = await new_task(sdk, profile="data_task")
    r = await task.run_code("print(1)")
    assert r.sandbox["status"] == "ok"


async def test_complete_kills_lease(sdk):
    async with await new_task(sdk) as task:
        await task.call("legal_db.search", query="x")
    with pytest.raises(Rejected) as exc:
        await task.call("legal_db.search", query="x")
    assert exc.value.reason_code == "CAPABILITY_COMPLETED"


async def test_delegate_and_escalation(sdk, app):
    parent = await new_task(sdk)
    child = await parent.delegate(agent_id="other-agent", agent_key="agent-b", tools=["legal_db.search"])
    assert (await child.call("legal_db.search", query="x")).decision.allowed
    with pytest.raises(Rejected):
        await parent.delegate(agent_id="other-agent", agent_key="agent-b", tools=["code.run"])


async def test_wrong_agent_key_rejected(sdk, app):
    task = await new_task(sdk)
    other = AsyncAegis("http://gw", agent_key="agent-b", transport=httpx.ASGITransport(app=app))
    with pytest.raises(Rejected) as exc:
        await other.task(task.task_id, task.lease).call("legal_db.search", query="x")
    assert exc.value.reason_code == "LEASE_AGENT_MISMATCH"
    await other.aclose()


async def test_create_task_needs_app_key(app):
    agent_only = AsyncAegis("http://gw", agent_key="agent-a", transport=httpx.ASGITransport(app=app))
    with pytest.raises(ValueError):
        await agent_only.create_task(principal="x", agent_id="demo-agent", profile="research")
    await agent_only.aclose()


def test_budget_status_maps_to_budget_exceeded():
    resp = httpx.Response(429, json={"error": {"reason_code": "BUDGET_EXCEEDED"},
                                     "mandate": {"action": "BLOCK", "reason_code": "BUDGET_EXCEEDED",
                                                 "rule_id": "BUD-001", "stage": "budget"}})
    with pytest.raises(BudgetExceeded) as exc:
        _check(resp)
    assert exc.value.rule_id == "BUD-001"
