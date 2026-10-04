"""`make redteam`: replay the adversarial corpus (tests/cases/redteam.yaml) through the live
gateway — the scanner discipline of promptfoo/garak, but against our enforcement pipeline.

Each case names a technique (OWASP LLM / agentic taxonomy) and the decision the gateway MUST
return. The runner prints one line per case and a per-technique summary, and exits non-zero
if any expectation fails — usable as CI evidence and as a live jury demo (`make redteam-live`
against a running stack). Nothing is executed: every probe is a playground dry run.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).parents[1]
ADMIN_KEY_HEADER = {"X-Admin-Key": ""}
EVALUATE = "/admin/playground/evaluate"

# Minimum-enforcement semantics: expect is the level the DETERMINISTIC layer alone must reach.
# The semantic guard may only tighten REDACT -> BLOCK when a real model is active; ALLOW must be exact.
SEVERITY = {"ALLOW": 0, "REDACT": 1, "BLOCK": 2}


def met_expectation(action: str, expect: str) -> bool:
    if expect == "ALLOW":
        return action == "ALLOW"
    return SEVERITY.get(action, -1) >= SEVERITY[expect]


async def main(base_url: str, admin_key: str) -> int:
    cases = yaml.safe_load((ROOT / "tests" / "cases" / "redteam.yaml").read_text(encoding="utf-8"))
    headers = {"X-Admin-Key": admin_key}
    failures: list[str] = []
    by_action = Counter()

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        r = await client.get("/health")
        r.raise_for_status()
        # Pin the profile so results are reproducible no matter what was toggled in the dashboard before.
        r = await client.put("/admin/policy/profile", headers=headers, json={"profile": "balanced"})
        r.raise_for_status()
        print("profile pinned to 'balanced' for reproducible results\n")
        for case in cases:
            body = {"text": case["text"], "target": case.get("target", "user_input")}
            for key in ("sink", "classification", "tool"):
                if key in case:
                    body[key] = case[key]
            r = await client.post(EVALUATE, headers=headers, json=body)
            r.raise_for_status()
            payload = r.json()
            decision = payload["decision"]
            action, rule = decision["action"], decision.get("rule_id", "")
            rules = {f["rule_id"] for f in decision.get("findings", [])}
            expect_action, expect_rule = case["expect"], case.get("rule")
            ok = met_expectation(action, expect_action) and (expect_rule is None or expect_rule in rules)
            by_action[action] += 1
            tightened = ok and expect_action == "REDACT" and action == "BLOCK"
            status = "PASS" if ok else "FAIL"
            if not ok:
                failures.append(case["id"])
            note = "  [semantic tightened REDACT->BLOCK]" if tightened else ""
            print(f"{status}  {case['id']:6} {case.get('technique', '')[:44]:44} "
                  f"-> {action:6} (want {expect_action}"
                  f"{', ' + expect_rule if expect_rule else ''})  got rules {sorted(rules) or '-'}{note}")

    total = len(cases)
    print(f"\n{total - len(failures)}/{total} probes met the expectation "
          f"({', '.join(f'{k}={v}' for k, v in sorted(by_action.items()))})")
    if failures:
        print("FAILED probes: " + ", ".join(failures))
        return 1
    print("All adversarial probes handled by the deterministic pipeline; "
          "no semantic-model dependency required.")
    return 0


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    key = sys.argv[2] if len(sys.argv) > 2 else "dev-admin-key"
    sys.exit(asyncio.run(main(base, key)))
