"""Budget escrow: reserve before execute, atomic across scopes, no overspend under concurrency."""
import asyncio

from conftest import ADMIN

MSG = [{"role": "user", "content": "ping"}]


async def chat(client, t, max_tokens=100, model="mock/echo"):
    return await client.post("/v1/chat/completions", headers=t["headers"],
                             json={"model": model, "messages": MSG, "max_tokens": max_tokens})


async def test_within_budget(client, new_task):
    t = await new_task()
    r = await chat(client, t)
    assert r.status_code == 200
    assert r.json()["usage"]["reserved_tokens"] >= r.json()["usage"]["total_tokens"]


async def test_request_larger_than_budget_blocked_before_model(client, new_task, monkeypatch):
    called = []
    import aegis.engine as engine

    async def fake(*a, **k):
        called.append(1)
    monkeypatch.setattr(engine, "complete", fake)
    t = await new_task()  # contract_review: 20k tokens
    r = await chat(client, t, max_tokens=50_000)
    assert r.status_code == 429 and r.json()["mandate"]["rule_id"] == "BUD-001"
    assert called == []


async def test_default_max_tokens_bounds_reservation(client, new_task):
    t = await new_task()
    r = await client.post("/v1/chat/completions", headers=t["headers"], json={"model": "mock/echo", "messages": MSG})
    assert r.json()["usage"]["reserved_tokens"] >= 1024


async def test_concurrent_agents_never_overspend(client, gw):
    r = await client.post("/admin/simulate/agents?n=30&pool_tokens=10000&max_tokens=1000", headers=ADMIN)
    s = r.json()
    assert s["executed"] + s["prevented"] == 30 and s["other"] == 0
    assert s["overspend_tokens"] == 0
    assert 0 < s["executed"] < 30


async def test_parallel_requests_on_one_task(client, new_task, gw):
    t = await new_task()
    await gw.pool.execute("UPDATE budgets SET token_limit=3000, concurrency_limit=100 WHERE scope_id=$1",
                          f"task:{t['task_id']}")
    results = await asyncio.gather(*(chat(client, t, max_tokens=900) for _ in range(10)))
    ok = sum(r.status_code == 200 for r in results)
    row = await gw.pool.fetchrow("SELECT * FROM budgets WHERE scope_id=$1", f"task:{t['task_id']}")
    assert ok == 3 and row["spent"] + row["reserved"] <= 3000 and row["active_calls"] == 0


async def test_runaway_loop_stopped_by_call_limit(new_task, call):
    t = await new_task()  # contract_review: 30 calls
    statuses = [(await call(t, "notes.write", title="loop", body="again")).status_code for _ in range(32)]
    assert statuses[:30] == [200] * 30 and statuses[30] == 429


async def test_uncertain_reservation_keeps_tokens(gw, new_task):
    t = await new_task()
    res = await gw.escrow.reserve(t["task_id"], [__import__("aegis.budget", fromlist=["Scope"]).Scope(
        f"task:{t['task_id']}")], tokens=500)
    await gw.escrow.mark_uncertain(res)
    row = await gw.pool.fetchrow("SELECT * FROM budgets WHERE scope_id=$1", f"task:{t['task_id']}")
    assert row["reserved"] == 500 and row["active_calls"] == 0
    assert await gw.escrow.reconcile(res, 120)
    row = await gw.pool.fetchrow("SELECT * FROM budgets WHERE scope_id=$1", f"task:{t['task_id']}")
    assert row["reserved"] == 0 and row["spent"] == 120


async def test_model_not_allowed(client, new_task):
    t = await new_task()
    r = await chat(client, t, model="cloud/some-random-model")
    assert r.status_code == 403 and r.json()["mandate"]["rule_id"] == "MODEL-001"


# ---------------------------------------------------------------- model providers and data flow

async def test_confidential_task_cannot_prompt_cloud_model(client, new_task, call, monkeypatch):
    import aegis.engine as engine
    called = []

    async def fake(*a, **k):
        called.append(1)
    monkeypatch.setattr(engine, "complete", fake)
    gw = client._transport.app.state.gw
    gw.settings.llm_location = "cloud"
    t = await new_task()
    await call(t, "doc.read", path="/clients/A/contracts/acquisition.txt")
    r = await chat(client, t, model="main/deepseek/deepseek-v4.1-flash")
    gw.settings.llm_location = "onprem"
    m = r.json()["mandate"]
    assert r.status_code == 403 and m["rule_id"] == "IFC-001"
    assert m["findings"][0]["detail"]["sink"] == "llm:external" and called == []


async def test_confidential_task_may_use_onprem_model(client, new_task, call, monkeypatch):
    import aegis.engine as engine
    from aegis.llm import Completion

    async def fake(model, *a, **k):
        return Completion(f"answer from {model}", 5, 5)
    monkeypatch.setattr(engine, "complete", fake)
    t = await new_task()
    await call(t, "doc.read", path="/clients/A/contracts/acquisition.txt")
    r = await chat(client, t, model="main/deepseek/deepseek-v4.1-flash")
    assert r.status_code == 200 and "main/deepseek/deepseek-v4.1-flash" in r.json()["choices"][0]["message"]["content"]


async def test_unconfigured_provider_fails_cleanly(client, new_task):
    t = await new_task()
    r = await chat(client, t, model="main/deepseek/deepseek-v4.1-flash")
    assert r.status_code == 502 and r.json()["mandate"]["reason_code"] == "MODEL_UNAVAILABLE"


async def test_simulation_reports_refusals_instead_of_crashing(client):
    """If every request is refused before the budget stage (here: the mock model is taken off the allowlist),
    the race reports why instead of failing with a 500."""
    r = await client.delete("/admin/models/mock/echo", headers=ADMIN)
    assert r.status_code == 200, r.text
    r = await client.post("/admin/simulate/agents?n=5&pool_tokens=1000&max_tokens=100", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] == 0 and body["other"] == 5 and body["overspend_tokens"] == 0
    assert body["failures"]


async def test_race_admits_exactly_what_fits(client):
    """Each agent reserves prompt + max_tokens; exactly floor(pool / reserve) of them may run."""
    r = await client.post("/admin/simulate/agents?n=30&pool_tokens=10000&max_tokens=1000", headers=ADMIN)
    body = r.json()
    assert body["reserve_per_request"] == body["prompt_tokens_per_request"] + 1000
    assert body["executed"] == body["fit"] == 10000 // body["reserve_per_request"]
    assert body["prevented"] == 30 - body["fit"] and body["overspend_tokens"] == 0
