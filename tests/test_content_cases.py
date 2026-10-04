from pathlib import Path

import pytest
import yaml

from conftest import ADMIN

CASES = yaml.safe_load((Path(__file__).parent / "cases" / "content.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_content_case(client, gw, case):
    if case.get("profile"):
        r = await client.put("/admin/policy/profile", headers=ADMIN, json={"profile": case["profile"]})
        assert r.status_code == 200, r.text
    body = {"text": case["text"], "target": case.get("target", "user_input")}
    for key in ("sink", "classification"):
        if key in case:
            body[key] = case[key]
    r = await client.post("/admin/playground/evaluate", headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert decision["action"] == case["expect"], decision
    if "rule" in case:
        assert case["rule"] in {f["rule_id"] for f in decision["findings"]}
    assert r.json()["executed"] is False
