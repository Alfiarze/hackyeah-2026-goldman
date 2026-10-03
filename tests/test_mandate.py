"""Task-scoped capabilities: tools, resources, recipients, lease binding, lifecycle."""
from conftest import ADMIN, APP

CONTRACT = "/clients/A/contracts/acquisition.txt"


async def test_allowed_tool_and_resource(new_task, call):
    t = await new_task()
    r = await call(t, "doc.read", path=CONTRACT)
    assert r.status_code == 200 and r.json()["mandate"]["tool_invoked"] is True


async def test_tool_not_in_mandate(new_task, call, backend):
    t = await new_task()
    r = await call(t, "code.run", code="print(1)")
    assert r.status_code == 403 and r.json()["mandate"]["rule_id"] == "MANDATE-TOOL"
    assert backend.counters["code.run"] == 0


async def test_other_client_document_blocked(new_task, call, backend):
    t = await new_task()
    r = await call(t, "doc.read", path="/clients/B/contracts/nda.txt")
    assert r.json()["mandate"]["rule_id"] == "MANDATE-RES"
    assert backend.counters["doc.read"] == 0


async def test_path_traversal_blocked(new_task, call):
    t = await new_task()
    r = await call(t, "doc.read", path="/clients/A/../B/contracts/nda.txt")
    assert r.status_code == 403 and r.json()["mandate"]["rule_id"] == "MANDATE-RES"


async def test_recipient_not_allowed(new_task, call, backend):
    t = await new_task()
    r = await call(t, "mail.send", to="someone@unknown.example", subject="s", body="hello")
    assert r.json()["mandate"]["rule_id"] == "MANDATE-RCPT"
    assert backend.counters["mail.send"] == 0


async def test_unknown_agent_key(client, new_task):
    t = await new_task()
    r = await client.post("/v1/tools/doc.read/call", json={"args": {"path": CONTRACT}},
                          headers={"Authorization": "Bearer nope", "X-Mandate-Lease": t["lease"]})
    assert r.status_code == 401


async def test_missing_lease(client):
    r = await client.post("/v1/tools/doc.read/call", json={"args": {}}, headers={"Authorization": "Bearer agent-a"})
    assert r.status_code == 401 and r.json()["error"]["reason_code"] == "LEASE_REQUIRED"


async def test_lease_of_other_agent_rejected(client, new_task):
    t = await new_task()  # bound to demo-agent
    r = await client.post("/v1/tools/doc.read/call", json={"args": {"path": CONTRACT}},
                          headers={"Authorization": "Bearer agent-b", "X-Mandate-Lease": t["lease"]})
    assert r.status_code == 403 and r.json()["error"]["reason_code"] == "LEASE_AGENT_MISMATCH"


async def test_forged_lease_signature(client, new_task):
    t = await new_task()
    forged = t["task_id"] + "." + "0" * 32
    r = await client.post("/v1/tools/doc.read/call", json={"args": {"path": CONTRACT}},
                          headers={"Authorization": "Bearer agent-a", "X-Mandate-Lease": forged})
    assert r.status_code == 403 and r.json()["error"]["reason_code"] == "LEASE_INVALID"


async def test_task_creation_requires_app_key(client):
    r = await client.post("/v1/tasks", json={"principal": "x", "agent_id": "demo-agent", "profile": "research"})
    assert r.status_code == 401


async def test_unknown_profile(client):
    r = await client.post("/v1/tasks", headers=APP, json={"principal": "x", "agent_id": "a", "profile": "root"})
    assert r.status_code == 400


async def test_completed_task_lease_is_dead(client, new_task, call):
    t = await new_task()
    r = await client.post(f"/v1/tasks/{t['task_id']}/complete", headers=t["headers"])
    assert r.status_code == 200
    r = await call(t, "legal_db.search", query="break fee")
    assert r.status_code == 403 and r.json()["error"]["reason_code"] == "CAPABILITY_COMPLETED"


async def test_revoked_by_admin(client, new_task, call):
    t = await new_task()
    assert (await client.post(f"/admin/tasks/{t['task_id']}/revoke", headers=ADMIN)).status_code == 200
    r = await call(t, "legal_db.search", query="x")
    assert r.json()["error"]["reason_code"] == "CAPABILITY_REVOKED"


async def test_expired_lease(gw, new_task, call):
    t = await new_task()
    await gw.pool.execute("UPDATE tasks SET status='active' WHERE id=$1", t["task_id"])
    # expiry is part of the signed lease, so shortening it in the DB also invalidates the signature
    await gw.pool.execute("UPDATE tasks SET expires_at = now() - interval '1 second' WHERE id=$1", t["task_id"])
    r = await call(t, "legal_db.search", query="x")
    assert r.status_code == 403


async def test_mandate_disabled_by_policy_allows_tool(client, new_task, call):
    r = await client.patch("/admin/controls/mandate", headers=ADMIN, json={"enabled": False})
    assert r.status_code == 200
    t = await new_task()
    r = await call(t, "code.run", code="print(1)")
    assert r.status_code == 200
