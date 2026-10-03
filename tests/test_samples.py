"""The sample contracts offered for upload in the console: the clean one passes, the defective one is
stopped and every planted defect is reported."""
from pathlib import Path

from conftest import ADMIN

SAMPLES = Path(__file__).parents[1] / "dashboard" / "public" / "samples"


async def check(client, name):
    text = (SAMPLES / name).read_text(encoding="utf-8")
    r = await client.post("/admin/playground/evaluate", headers=ADMIN, json={"text": text, "target": "tool_results"})
    assert r.status_code == 200, r.text
    return r.json()["decision"]


async def test_clean_contract_passes(client):
    d = await check(client, "umowa-czysta.txt")
    assert d["action"] == "ALLOW", d


async def test_defective_contract_reports_every_defect(client):
    d = await check(client, "umowa-z-defektami.txt")
    assert d["action"] == "BLOCK"
    by_rule = {f["rule_id"]: f["detail"] for f in d["findings"]}
    assert {"PESEL", "NIP", "ID_CARD", "IBAN", "ADDRESS"} <= set(by_rule["PII-001"]["entities"])
    assert {"PASSWORD", "CONNECTION_STRING"} <= set(by_rule["SEC-001"]["types"])
    patterns = set(by_rule["INJ-001"]["patterns"])
    assert {"IGNORE_INSTRUCTIONS_PL", "HIDDEN_AI_NOTE_PL", "CONCEALMENT_PL", "MARKDOWN_EXFIL"} <= patterns
    assert any(p.startswith("OBFUSCATED_") for p in patterns)  # the base64 paragraph
    assert {"ATK-EXEC-002", "ATK-TRC-001"} <= set(by_rule)
