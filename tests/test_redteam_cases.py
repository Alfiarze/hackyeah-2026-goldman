"""The red-team corpus as part of the self-testing suite: the same cases `make redteam` replays
against a live stack, run here in-process through the playground API (no model server needed).
Expectations are minimum-enforcement: the deterministic layer alone must reach REDACT/BLOCK,
ALLOW must be exact — so the suite passes with the heuristic backend (CI, no model) and stays
valid when a real semantic model tightens REDACT to BLOCK."""

from pathlib import Path

import pytest
import yaml

from conftest import ADMIN

CASES = yaml.safe_load((Path(__file__).parent / "cases" / "redteam.yaml").read_text(encoding="utf-8"))

SEVERITY = {"ALLOW": 0, "REDACT": 1, "BLOCK": 2}


def met_expectation(action: str, expect: str) -> bool:
    if expect == "ALLOW":
        return action == "ALLOW"
    return SEVERITY.get(action, -1) >= SEVERITY[expect]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_redteam_case(client, case):
    body = {"text": case["text"], "target": case.get("target", "user_input")}
    for key in ("sink", "classification", "tool"):
        if key in case:
            body[key] = case[key]
    r = await client.post("/admin/playground/evaluate", headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    decision = r.json()["decision"]
    assert met_expectation(decision["action"], case["expect"]), (
        f"{case['id']} ({case.get('technique')}): got {decision['action']}, "
        f"want at least {case['expect']}; findings={[f['rule_id'] for f in decision.get('findings', [])]}")
    if "rule" in case:
        assert case["rule"] in {f["rule_id"] for f in decision["findings"]}
    assert r.json()["executed"] is False
