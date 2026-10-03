"""The sample contracts offered for upload in the console: the clean one passes, the defective one is
stopped and every planted defect is reported."""
from pathlib import Path

from conftest import ADMIN

ROOT = Path(__file__).parents[1]
# source tree: dashboard/public/samples; the Docker image only has the built copy in dashboard/dist/samples
SAMPLES = next(p for p in (ROOT / "dashboard" / "public" / "samples", ROOT / "dashboard" / "dist" / "samples") if p.is_dir())


async def check(client, name):
    if name.endswith(".pdf"):  # through the same upload path the console uses
        r = await client.post("/admin/playground/extract", headers=ADMIN | {"Content-Type": "application/pdf"},
                              content=(SAMPLES / name).read_bytes())
        assert r.status_code == 200, r.text
        text = r.json()["text"]
    else:
        text = (SAMPLES / name).read_text(encoding="utf-8")
    r = await client.post("/admin/playground/evaluate", headers=ADMIN, json={"text": text, "target": "tool_results"})
    assert r.status_code == 200, r.text
    return r.json()["decision"]


import pytest


@pytest.mark.parametrize("name", ["umowa-czysta.txt", "umowa-czysta.pdf"])
async def test_clean_contract_passes(client, name):
    d = await check(client, name)
    assert d["action"] == "ALLOW", d


@pytest.mark.parametrize("name", ["umowa-z-defektami.txt", "umowa-z-defektami.pdf"])
async def test_defective_contract_reports_every_defect(client, name):
    """In the PDF the instruction for the AI is white 1-point text: invisible on the page, still extracted."""
    d = await check(client, name)
    assert d["action"] == "BLOCK"
    by_rule = {f["rule_id"]: f["detail"] for f in d["findings"]}
    assert {"PESEL", "NIP", "ID_CARD", "IBAN", "ADDRESS"} <= set(by_rule["PII-001"]["entities"])
    assert {"PASSWORD", "CONNECTION_STRING"} <= set(by_rule["SEC-001"]["types"])
    patterns = set(by_rule["INJ-001"]["patterns"])
    assert {"IGNORE_INSTRUCTIONS_PL", "HIDDEN_AI_NOTE_PL", "CONCEALMENT_PL", "MARKDOWN_EXFIL"} <= patterns
    assert any(p.startswith("OBFUSCATED_") for p in patterns)  # the base64 paragraph
    assert {"ATK-EXEC-002", "ATK-TRC-001"} <= set(by_rule)


async def test_extract_rejects_garbage(client):
    r = await client.post("/admin/playground/extract", headers=ADMIN | {"Content-Type": "application/pdf"},
                          content=b"%PDF-1.7 this is not really a pdf")
    assert r.status_code == 422
    r = await client.post("/admin/playground/extract", headers=ADMIN, content=bytes([0xff, 0xfe, 0x00, 0x81]))
    assert r.status_code == 415
