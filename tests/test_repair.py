"""Hermetic tests for the approval-gated sandbox repair loop.

These tests use a copied disposable dbt/DuckDB sandbox and a deterministic fake proposal generator;
they never contact DataHub, Anthropic, or a production system.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import repair  # noqa: E402


class Node:
    def __init__(self, urn: str, columns: list[str]):
        self.urn = urn
        self.schema_fields = columns


VALID_SQL = """select
    customer_id,
    full_name,
    email_address as email,
    created_at
from {{ ref('raw_customers') }}
"""


def fake_generator(_context):
    return True, VALID_SQL, "Map the CRM v2 email_address field back to the analytics email contract."


def schema_drift_report():
    return {
        "summary": "Customer contactability dropped after a schema mapping mismatch.",
        "suspects": [{
            "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.customers,PROD)",
            "why": "The upstream CRM v2 exposes email_address while staging emits legacy email with a 100% null rate.",
        }],
    }


def evidence():
    return [
        Node("urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.customers,PROD)",
             ["customer_id", "full_name", "email_address", "created_at"]),
        Node("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.staging.stg_customers,PROD)",
             ["customer_id", "full_name", "email", "created_at"]),
    ]


class RepairTests(unittest.TestCase):
    def test_rejects_non_read_only_or_wrong_mapping_sql(self):
        for bad in ("drop table x", "select customer_id from {{ ref('raw_customers') }}", "select email_address as email from other"):
            ok, _reason = repair._safe_generated_sql(bad)
            self.assertFalse(ok)

    def test_proposal_is_safe_and_does_not_execute(self):
        proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=fake_generator)
        self.assertEqual(proposal["state"], "approval_required")
        self.assertFalse(proposal["attempted"])
        self.assertIn("email_address as email", proposal["fixed_sql"])
        self.assertIn("approve", proposal["approval_required"].lower())

    def test_unapproved_proposal_cannot_run(self):
        proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=fake_generator)
        receipt = repair.execute_sandbox_trial(proposal, approval=None)
        self.assertEqual(receipt["state"], "approval_required")
        self.assertFalse(receipt["attempted"])

    def test_rejected_model_output_never_reaches_the_sandbox(self):
        def unsafe_generator(_context):
            return True, "drop table customer_pii", "Unsafe example that must be rejected."

        proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=unsafe_generator)
        self.assertEqual(proposal["state"], "proposal_rejected")
        self.assertFalse(proposal["attempted"])
        self.assertIn("rejected before execution", proposal["reason"])

    def test_missing_sandbox_is_an_explicit_recoverable_failure(self):
        proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=fake_generator)
        with tempfile.TemporaryDirectory() as tmp:
            receipt = repair.execute_sandbox_trial(proposal, approval="unit-test", sandbox=Path(tmp) / "missing")
        self.assertEqual(receipt["state"], "sandbox_unavailable")
        self.assertTrue(receipt["attempted"])
        self.assertFalse(receipt["verified"])

    def test_approved_trial_flips_real_assertion_and_rolls_back(self):
        source = ROOT / "repair_sandbox"
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "sandbox"
            shutil.copytree(source, sandbox, ignore=shutil.ignore_patterns("target", "logs", "sandbox.duckdb", "receipts"))
            proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=fake_generator)
            receipt = repair.execute_sandbox_trial(proposal, approval="unit-test", sandbox=sandbox)
            self.assertTrue(receipt["attempted"], receipt)
            self.assertTrue(receipt["verified"], receipt)
            self.assertFalse(receipt["before"]["passed"], receipt)
            self.assertTrue(receipt["after"]["passed"], receipt)
            self.assertTrue(receipt["rollback_verified"], receipt)
            self.assertEqual((sandbox / "models" / "stg_customers.sql").read_text(encoding="utf-8"), repair.BROKEN_SQL)


if __name__ == "__main__":
    unittest.main()
