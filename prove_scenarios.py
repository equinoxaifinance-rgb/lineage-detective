"""prove_scenarios.py — run the agent against all THREE distinct incident types and verify it
autonomously fingers the correct root cause for each. Proof of generalizability, not one trick."""
import os
import sys

os.environ.setdefault("LINEAGE_RUN_MODE", "self_hosted")
sys.path.insert(0, "src")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from agent import investigate

CASES = [
    ("A. partial-load",
     "The Revenue Overview dashboard shows a ~40% drop in daily revenue since yesterday, no pipeline errors.",
     "urn:li:dataset:(urn:li:dataPlatform:looker,bi.revenue_overview,PROD)", "raw.orders"),
    ("B. schema-drift",
     "The Customer 360 dashboard shows blank/null email for most customers since yesterday, no errors.",
     "urn:li:dataset:(urn:li:dataPlatform:looker,bi.customer_360,PROD)", "stg_customers"),
    ("C. stale-data",
     "USD-converted revenue on the Finance dashboard looks frozen — it hasn't changed in days.",
     "urn:li:dataset:(urn:li:dataPlatform:looker,bi.finance_fx,PROD)", "exchange_rates"),
]

passed = 0
for label, symptom, urn, expect_root in CASES:
    r = investigate(
        symptom,
        urn,
        server="http://localhost:8080",
        reasoning_mode="evidence",
    )
    suspects = r.get("suspects", [])
    top = suspects[0] if suspects else {}
    top_urn = top.get("urn", "")
    ok = expect_root in top_urn
    passed += ok
    print(f"{label:16s} top='{top_urn.rsplit('(',1)[-1].rstrip(')').split(',')[-2] if top_urn else 'none'}' "
          f"conf={top.get('confidence')} expected_action_locus~{expect_root}  -> {'PASS' if ok else 'FAIL'}")

print(f"\n{passed}/{len(CASES)} scenarios reached the expected action locus",
      "— agent generalizes across incident types." if passed == len(CASES) else "— NOT all correct.")
sys.exit(0 if passed == len(CASES) else 1)
