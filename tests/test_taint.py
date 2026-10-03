"""Data lineage: a task inherits the highest classification it has read."""
from conftest import ADMIN

CONTRACT = "/clients/A/contracts/acquisition.txt"


async def test_external_mail_allowed_before_reading(new_task, call, backend):
    t = await new_task()
    r = await call(t, "mail.send", to="partner@client-A.example", subject="Hi", body="Meeting at 10.")
    assert r.status_code == 200 and backend.counters["mail.send"] == 1


async def test_external_mail_blocked_after_confidential_read(new_task, call, backend):
    t = await new_task()
    await call(t, "doc.read", path=CONTRACT)
    r = await call(t, "mail.send", to="partner@client-A.example", subject="Hi", body="Paraphrased summary.")
    m = r.json()["mandate"]
    assert r.status_code == 403 and m["rule_id"] == "IFC-001" and m["reason_code"] == "DATA_FLOW_VIOLATION"
    assert backend.counters["mail.send"] == 0


async def test_internal_sinks_still_allowed_after_read(new_task, call):
    t = await new_task()
    await call(t, "doc.read", path=CONTRACT)
    assert (await call(t, "notes.write", title="memo", body="risks")).status_code == 200
    assert (await call(t, "mail.send", to="boss@lawfirm.example", subject="memo", body="risks")).status_code == 200


async def test_query_sink_blocked_after_read(new_task, call):
    t = await new_task()
    await call(t, "doc.read", path=CONTRACT)
    r = await call(t, "legal_db.search", query="break fee")
    assert r.json()["mandate"]["rule_id"] == "IFC-001"  # INTERNAL sink < CONFIDENTIAL task


async def test_public_document_does_not_taint(new_task, call):
    t = await new_task()
    await call(t, "doc.read", path="/public/templates/nda_template.txt")
    r = await call(t, "mail.send", to="partner@client-A.example", subject="Template", body="see template")
    assert r.status_code == 200


async def test_classification_visible_in_task(client, new_task, call):
    t = await new_task()
    await call(t, "doc.read", path=CONTRACT)
    r = await client.get(f"/admin/tasks/{t['task_id']}", headers=ADMIN)
    assert r.json()["classification"] == "CONFIDENTIAL"


async def test_disabling_ifc_control_changes_decision(client, new_task, call):
    await client.patch("/admin/controls/ifc_taint", headers=ADMIN, json={"enabled": False})
    t = await new_task()
    await call(t, "doc.read", path=CONTRACT)
    r = await call(t, "mail.send", to="partner@client-A.example", subject="Hi", body="x")
    assert r.status_code == 200
