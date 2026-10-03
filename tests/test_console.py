"""Agent console: operator acts as an agent; actions use the real pipeline."""
from conftest import ADMIN


async def start(client, **kw):
    r = await client.post("/admin/console/tasks", headers=ADMIN, json=kw)
    assert r.status_code == 201
    return r.json()["task_id"]


async def act(client, tid, **body):
    r = await client.post(f"/admin/console/tasks/{tid}/act", headers=ADMIN, json=body)
    assert r.status_code == 200
    return r.json()


async def test_console_requires_admin(client):
    assert (await client.post("/admin/console/tasks", json={})).status_code == 401


async def test_console_flow_read_then_exfiltrate(client):
    tid = await start(client)
    r = await act(client, tid, kind="tool", tool="doc.read", args={"path": "/clients/A/contracts/acquisition.txt"})
    assert r["http_status"] == 200 and r["task"]["classification"] == "CONFIDENTIAL"
    r = await act(client, tid, kind="tool", tool="mail.send",
                  args={"to": "partner@client-A.example", "subject": "s", "body": "b"})
    assert r["http_status"] == 403 and r["response"]["mandate"]["rule_id"] == "IFC-001"
    assert r["backend_after"]["mail_sent"] == r["backend_before"]["mail_sent"]


async def test_console_chat_and_complete(client):
    tid = await start(client)
    r = await act(client, tid, kind="chat", content="hello", model="mock/echo")
    assert r["http_status"] == 200
    assert (await act(client, tid, kind="complete"))["http_status"] == 200
    r = await act(client, tid, kind="tool", tool="legal_db.search", args={"query": "x"})
    assert r["http_status"] == 403 and r["response"]["error"]["reason_code"] == "CAPABILITY_COMPLETED"


async def test_console_cannot_drive_other_tasks(client, new_task):
    t = await new_task()
    r = await client.post(f"/admin/console/tasks/{t['task_id']}/act", headers=ADMIN, json={"kind": "complete"})
    assert r.status_code == 404
