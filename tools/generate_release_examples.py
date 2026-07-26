"""Generate judge-facing repair artifacts by running the real verification code."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repair import build_handoff_packet, execute_sandbox_trial, propose_repair


@dataclass
class Node:
    urn: str
    fields: list[str]


SCHEMA_FIXED = """select
    customer_id,
    full_name,
    email_address as email,
    created_at
from {{ ref('raw_customers') }}
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(case: str, proposal: dict) -> dict:
    target = ROOT / "examples" / "generated" / case
    target.mkdir(parents=True, exist_ok=True)
    receipt = execute_sandbox_trial(proposal, approval="release-example-generator")
    if not (
        receipt.get("state") == "sandbox_verified"
        and receipt.get("verified")
        and receipt.get("rollback_verified")
    ):
        raise RuntimeError(f"{case} failed verification: {receipt}")
    files = {
        "proposed-change.diff": str(proposal.get("diff") or ""),
        "proposed-model.sql": str(proposal.get("fixed_sql") or ""),
        "sandbox-verification-receipt.json": json.dumps(
            receipt, indent=2, sort_keys=True, default=str
        )
        + "\n",
    }
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8", newline="\n")
    (target / "human-handoff.zip").write_bytes(build_handoff_packet(receipt))
    return {
        "case": case,
        "state": receipt["state"],
        "verified": receipt["verified"],
        "rollback_verified": receipt["rollback_verified"],
        "proposal_sha256": receipt["proposal_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(target.iterdir())
            if path.is_file()
        },
    }


def main() -> int:
    generated = ROOT / "examples" / "generated"
    generated.mkdir(parents=True, exist_ok=True)

    evidence = [
        Node(
            "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.customers,PROD)",
            ["customer_id", "full_name", "email_address", "created_at"],
        ),
        Node(
            "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.staging.stg_customers,PROD)",
            ["customer_id", "full_name", "email", "created_at"],
        ),
    ]
    schema_report = {
        "summary": "Customer contactability dropped after a schema mapping mismatch.",
        "suspects": [{
            "urn": evidence[0].urn,
            "why": "The source exposes email_address while staging still selects legacy email.",
        }],
    }
    schema = propose_repair(
        None,
        schema_report,
        evidence,
        fix_generator=lambda _context: (
            True,
            SCHEMA_FIXED,
            "Map the observed email_address field back to the downstream email contract.",
        ),
    )
    partial = propose_repair(
        None,
        {
            "summary": "The upstream orders ingestion silently loaded 44% fewer rows.",
            "suspects": [{
                "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD)",
                "why": "A partial load returned 44% fewer rows while the job reported success.",
            }],
        },
        [Node("urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD)", [])],
    )
    stale = propose_repair(
        None,
        {
            "summary": "The exchange-rate feed is six days stale.",
            "suspects": [{
                "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.ref.exchange_rates,PROD)",
                "why": "No current rate has arrived for six days.",
            }],
        },
        [Node("urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.ref.exchange_rates,PROD)", [])],
    )
    cases = [
        emit("schema-drift", schema),
        emit("partial-load", partial),
        emit("stale-feed", stale),
    ]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/generate_release_examples.py",
        "verification_contract": (
            "Every case executed the product sandbox, passed its assertion, verified rollback, "
            "and produced a hash-bound handoff ZIP."
        ),
        "cases": cases,
    }
    (generated / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
