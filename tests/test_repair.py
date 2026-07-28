"""Hermetic tests for the approval-gated sandbox repair loop.

These tests use a copied disposable dbt/DuckDB sandbox and a deterministic fake proposal generator;
they never contact DataHub, Anthropic, or a production system.
"""
from __future__ import annotations

import shutil
import inspect
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import repair  # noqa: E402


class Node:
    def __init__(
        self,
        urn: str,
        columns: list[str],
        custom_properties: dict[str, str] | None = None,
    ):
        self.urn = urn
        self.schema_fields = columns
        self.custom_properties = custom_properties or {}


class FakeBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class FakeMessages:
    def __init__(self, payload: dict):
        self.payload = payload

    def create(self, **_kwargs):
        return type("Response", (), {"content": [FakeBlock(__import__("json").dumps(self.payload))]})()


class FakeLLM:
    def __init__(self, payload: dict):
        self.messages = FakeMessages(payload)


VALID_SQL = """select
    customer_id,
    full_name,
    email_address as email,
    created_at
from {{ ref('raw_customers') }}
"""


def fake_generator(_context):
    return True, VALID_SQL, "Map the CRM v2 email_address field back to the analytics email contract."


def verified_receipt(fixed: str, source: bytes | str) -> dict:
    source_bytes = source if isinstance(source, bytes) else source.encode("utf-8")
    receipt = {
        "verified": True,
        "state": "sandbox_verified",
        "rollback_verified": True,
        "fixed_sql": fixed,
        "proposal_sha256": hashlib.sha256(fixed.encode("utf-8")).hexdigest(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "diff": "--- a/model.sql\n+++ b/model.sql\n",
    }
    return repair._seal_receipt(receipt)


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
    def test_custom_checked_out_sql_gets_a_constrained_structural_trial(self):
        current = "select order_id, status from {{ ref('raw_orders') }}\n"
        fixed = "select order_id, coalesce(status, 'unknown') as status from {{ ref('raw_orders') }}\n"
        llm = FakeLLM({
            "applicable": True,
            "fixed_sql": fixed,
            "rationale": "The evidence shows null status values reaching the affected model.",
        })
        proposal = repair.propose_repair(
            llm,
            {
                "summary": "Order status became null downstream.",
                "suspects": [{"urn": "urn:li:dataset:(x,raw_orders,PROD)", "why": "null status"}],
            },
            [Node("urn:li:dataset:(x,raw_orders,PROD)", ["order_id", "status"])],
            target_artifact={"path": "C:/repo/models/orders.sql", "file_name": "orders.sql", "sql": current},
        )
        self.assertEqual(proposal["action_type"], "custom_dbt_sql_repair")
        self.assertEqual(proposal["state"], "approval_required")
        self.assertEqual(proposal["source_path"], "C:/repo/models/orders.sql")
        receipt = repair.execute_sandbox_trial(proposal, approval="unit-test")
        self.assertTrue(receipt["verified"], receipt)
        self.assertTrue(receipt["rollback_verified"], receipt)
        self.assertEqual(receipt["after"]["value"], "1 statement(s)")

    def test_custom_sql_repair_rejects_a_new_relation(self):
        llm = FakeLLM({
            "applicable": True,
            "fixed_sql": "select * from {{ ref('unapproved_source') }}",
            "rationale": "Unsafe scope expansion.",
        })
        proposal = repair.propose_repair(
            llm,
            {"summary": "unknown", "suspects": [{"urn": "urn:x", "why": "unknown"}]},
            [Node("urn:x", [])],
            target_artifact={
                "file_name": "orders.sql",
                "sql": "select * from {{ ref('raw_orders') }}",
            },
        )
        self.assertEqual(proposal["state"], "proposal_rejected")
        self.assertIn("unapproved dbt relations", proposal["reason"])

    def test_second_run_does_not_stack_an_identical_repair(self):
        fixed = (
            "select order_id, coalesce(status, 'unknown') as status "
            "from {{ ref('raw_orders') }}\n"
        )
        llm = FakeLLM({
            "applicable": True,
            "fixed_sql": fixed,
            "rationale": "The current file already contains the evidence-bound correction.",
        })
        proposal = repair.propose_repair(
            llm,
            {
                "summary": "Recheck the previously repaired order status path.",
                "suspects": [{"urn": "urn:x", "why": "verify current state"}],
            },
            [Node("urn:x", ["order_id", "status"])],
            target_artifact={
                "path": "C:/repo/models/orders.sql",
                "file_name": "orders.sql",
                "sql": fixed,
            },
        )
        self.assertEqual(proposal["state"], "no_change_required")
        self.assertTrue(proposal["verified"])
        self.assertFalse(proposal["attempted"])
        self.assertIn("Downstream health", proposal["boundary"])

    def test_partial_load_gets_a_verified_volume_guard_instead_of_a_fake_data_repair(self):
        report = {
            "summary": "The upstream orders ingestion silently loaded 44% fewer rows.",
            "suspects": [{
                "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD)",
                "why": "A partial load returned 40% fewer rows while the job reported success.",
            }],
        }
        proposal = repair.propose_repair(
            None,
            report,
            [Node("urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.orders,PROD)", [])],
        )
        self.assertEqual(proposal["action_type"], "partial_load_guardrail")
        self.assertEqual(proposal["state"], "approval_required")
        self.assertIn("orders_ingestion_history", proposal["fixed_sql"])
        receipt = repair.execute_sandbox_trial(proposal, approval="unit-test")
        self.assertTrue(receipt["verified"], receipt)
        self.assertFalse(receipt["before"]["passed"], receipt)
        self.assertTrue(receipt["after"]["passed"], receipt)
        self.assertTrue(receipt["rollback_verified"], receipt)

    def test_stale_feed_gets_a_verified_freshness_guard_instead_of_invented_rates(self):
        report = {
            "summary": "The FX feed is frozen because the newest rate is six days stale.",
            "suspects": [{
                "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.ref.exchange_rates,PROD)",
                "why": "The stale exchange_rates feed added 0 rows during five successful runs.",
            }],
        }
        proposal = repair.propose_repair(
            None,
            report,
            [Node("urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.ref.exchange_rates,PROD)", [])],
        )
        self.assertEqual(proposal["action_type"], "stale_feed_guardrail")
        self.assertEqual(proposal["state"], "approval_required")
        self.assertIn("current_date", proposal["fixed_sql"])
        receipt = repair.execute_sandbox_trial(proposal, approval="unit-test")
        self.assertTrue(receipt["verified"], receipt)
        self.assertTrue(receipt["after"]["passed"], receipt)
        self.assertTrue(receipt["rollback_verified"], receipt)

    def test_sandbox_runner_exposes_real_progress_events(self):
        self.assertIn("on_progress", inspect.signature(repair.execute_sandbox_trial).parameters)

    def test_rejects_non_read_only_or_wrong_mapping_sql(self):
        for bad in ("drop table x", "select customer_id from {{ ref('raw_customers') }}", "select email_address as email from other"):
            ok, _reason = repair._safe_generated_sql(bad)
            self.assertFalse(ok)

    def test_proposal_is_safe_and_does_not_execute(self):
        proposal = repair.propose_repair(None, schema_drift_report(), evidence(), fix_generator=fake_generator)
        self.assertEqual(proposal["state"], "approval_required")
        self.assertFalse(proposal["attempted"])
        self.assertIn("email_address as email", proposal["fixed_sql"])
        self.assertIn("explicit approval", proposal["approval_required"].lower())

    def test_live_schema_evidence_compiles_repair_when_model_wording_is_unhelpful(self):
        unhelpful_report = {
            "summary": "The affected output changed unexpectedly.",
            "suspects": [{
                "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.customers,PROD)",
                "why": "The evidence points to the customer source.",
            }],
        }
        live_evidence = [
            Node(
                "urn:li:dataset:(urn:li:dataPlatform:bigquery,prod.raw.customers,PROD)",
                ["customer_id", "full_name", "email", "email_address", "created_at"],
                {"crm_export_version": "v2 (effective 2026-07-11)"},
            ),
            Node(
                "urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.staging.stg_customers,PROD)",
                ["customer_id", "full_name", "email", "created_at"],
                {
                    "email_null_rate_current": "1.00",
                    "email_null_rate_prior": "0.02",
                },
            ),
        ]
        proposal = repair.propose_repair(
            FakeLLM({"applicable": False, "fixed_sql": None, "rationale": "No change."}),
            unhelpful_report,
            live_evidence,
        )
        self.assertEqual(proposal["state"], "approval_required")
        self.assertEqual(proposal["proposal_mode"], "evidence_compiled")
        self.assertIn("email_address as email", proposal["fixed_sql"])
        self.assertIn("null-rate", proposal["rationale"])

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

    def test_successful_rewrite_with_failed_rollback_is_not_verified(self):
        proposal = repair.propose_repair(
            None, schema_drift_report(), evidence(), fix_generator=fake_generator
        )
        dbt_results = [
            (True, "seed ok", 0),
            (True, "baseline ok", 0),
            (True, "fixed ok", 0),
            (False, "rollback failed", 1),
        ]
        with mock.patch.object(repair, "_dbt", side_effect=dbt_results), mock.patch.object(
            repair, "_email_fill_rate", side_effect=[(0, 8), (8, 8)]
        ):
            receipt = repair.execute_sandbox_trial(proposal, approval="unit-test")
        self.assertFalse(receipt["verified"], receipt)
        self.assertFalse(receipt["rollback_verified"], receipt)
        self.assertEqual(receipt["state"], "sandbox_failed")
        valid, reason = repair.verify_sandbox_receipt(receipt)
        self.assertFalse(valid)
        self.assertIn("verified state", reason)

    def test_default_sandbox_is_copied_per_run_and_removed(self):
        current = "select order_id from {{ ref('raw_orders') }}\n"
        fixed = "select coalesce(order_id, 0) as order_id from {{ ref('raw_orders') }}\n"
        proposal = repair.propose_repair(
            FakeLLM({"applicable": True, "fixed_sql": fixed, "rationale": "Null-safe key."}),
            {"summary": "Null order IDs.", "suspects": [{"urn": "urn:x", "why": "null IDs"}]},
            [Node("urn:x", ["order_id"])],
            target_artifact={"file_name": "orders.sql", "sql": current},
        )
        first = repair.execute_sandbox_trial(proposal, approval="first")
        second = repair.execute_sandbox_trial(proposal, approval="second")
        self.assertTrue(first["verified"], first)
        self.assertTrue(second["verified"], second)
        self.assertNotEqual(first["sandbox"], second["sandbox"])
        self.assertTrue(first["sandbox_removed"])
        self.assertTrue(second["sandbox_removed"])

    def test_concurrent_default_trials_do_not_share_writable_state(self):
        current = "select order_id from {{ ref('raw_orders') }}\n"
        fixed = "select coalesce(order_id, 0) as order_id from {{ ref('raw_orders') }}\n"
        proposal = repair.propose_repair(
            FakeLLM({"applicable": True, "fixed_sql": fixed, "rationale": "Null-safe key."}),
            {"summary": "Null order IDs.", "suspects": [{"urn": "urn:x", "why": "null IDs"}]},
            [Node("urn:x", ["order_id"])],
            target_artifact={"file_name": "orders.sql", "sql": current},
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(
                pool.map(
                    lambda index: repair.execute_sandbox_trial(
                        proposal, approval=f"concurrent-{index}"
                    ),
                    range(8),
                )
            )
        self.assertEqual(len({receipt["sandbox"] for receipt in receipts}), 8)
        self.assertTrue(all(receipt["verified"] for receipt in receipts), receipts)
        self.assertTrue(all(receipt["rollback_verified"] for receipt in receipts), receipts)
        self.assertTrue(all(receipt["sandbox_removed"] for receipt in receipts), receipts)

    def test_handoff_packet_requires_verified_receipt_and_preserves_exact_artifacts(self):
        with self.assertRaises(ValueError):
            repair.build_handoff_packet({"verified": False})
        receipt = verified_receipt("select 1 as repaired\n", "select 1\n")
        receipt["diff"] = "--- a/model.sql\n+++ b/model.sql\n+select 1\n"
        repair._seal_receipt(receipt)
        with zipfile.ZipFile(BytesIO(repair.build_handoff_packet(receipt))) as archive:
            self.assertEqual(set(archive.namelist()), {
                "README.md", "proposed-change.diff", "proposed-model.sql",
                "sandbox-verification-receipt.json",
            })
            self.assertIn("select 1", archive.read("proposed-change.diff").decode("utf-8"))
            self.assertIn(
                receipt["receipt_sha256"],
                archive.read("sandbox-verification-receipt.json").decode("utf-8"),
            )

    def test_unverified_or_unapproved_repair_cannot_be_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "model.sql"
            target.write_text("select 1\n", encoding="utf-8")
            missing_approval = repair.apply_verified_repair(
                {"verified": True, "state": "sandbox_verified"},
                target_file=target,
                approval=None,
            )
            unverified = repair.apply_verified_repair(
                {"verified": False, "state": "sandbox_failed"},
                target_file=target,
                approval="unit-test",
            )
        self.assertEqual(missing_approval["state"], "apply_approval_required")
        self.assertEqual(unverified["state"], "apply_rejected")

    def test_verified_repair_applies_exact_bytes_and_restores_original(self):
        original = b"select legacy_email as email\n"
        fixed = VALID_SQL
        receipt = verified_receipt(fixed, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            applied = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-apply-button",
            )
            self.assertTrue(applied["applied"], applied)
            self.assertEqual(applied["state"], "applied_verified")
            self.assertEqual(target.read_bytes(), fixed.encode("utf-8"))
            backup = Path(applied["backup_file"])
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(applied["after_sha256"], receipt["proposal_sha256"])

            restored = repair.restore_applied_repair(
                applied,
                approval="unit-test-restore-button",
            )
            self.assertTrue(restored["restored"], restored)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(backup.exists())

    def test_restore_refuses_to_overwrite_a_later_human_edit(self):
        original = b"select legacy_email as email\n"
        fixed = VALID_SQL
        receipt = verified_receipt(fixed, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            applied = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-apply-button",
            )
            target.write_text("select human_edit\n", encoding="utf-8")
            restored = repair.restore_applied_repair(
                applied,
                approval="unit-test-restore-button",
            )
            self.assertFalse(restored["restored"])
            self.assertEqual(restored["state"], "restore_rejected")
            self.assertEqual(target.read_text(encoding="utf-8"), "select human_edit\n")

    def test_apply_refuses_source_drift_after_proposal(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(b"select later_human_edit\n")
            result = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-apply-button",
            )
            self.assertFalse(result["applied"])
            self.assertEqual(result["state"], "apply_rejected")
            self.assertIn("changed after", result["error"])
            self.assertEqual(target.read_bytes(), b"select later_human_edit\n")

    def test_apply_rejects_target_outside_explicit_allowed_root(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as other:
            target = Path(other) / "stg_customers.sql"
            target.write_bytes(original)
            result = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="hosted-session-apply",
                allowed_root=allowed,
            )
            self.assertFalse(result["applied"])
            self.assertIn("allowed workspace", result["error"])
            self.assertEqual(target.read_bytes(), original)

    def test_crlf_source_hash_survives_text_decoding_and_can_apply(self):
        original = b"select legacy_email as email\r\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            applied = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-crlf-apply",
            )
            self.assertTrue(applied["applied"], applied)
            self.assertEqual(target.read_bytes(), VALID_SQL.encode("utf-8"))

    def test_two_writers_cannot_both_enter_the_same_apply_window(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        entered = Event()
        release = Event()
        real_atomic = repair._atomic_write

        def slow_atomic(path, data):
            entered.set()
            release.wait(timeout=5)
            return real_atomic(path, data)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            with mock.patch.object(repair, "_atomic_write", side_effect=slow_atomic):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        repair.apply_verified_repair,
                        receipt,
                        target_file=target,
                        approval="first",
                    )
                    self.assertTrue(entered.wait(timeout=3))
                    second = pool.submit(
                        repair.apply_verified_repair,
                        receipt,
                        target_file=target,
                        approval="second",
                    ).result(timeout=3)
                    self.assertEqual(second["state"], "apply_busy")
                    self.assertFalse(second["applied"])
                    release.set()
                    self.assertTrue(first.result(timeout=5)["applied"])

    def test_dead_process_lock_is_reclaimed_without_manual_cleanup(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            lock = target.with_name(f".{target.name}.lineage-detective.lock")
            lock.write_text(
                '{"created_unix": 1, "pid": 999999999, "token": "dead-owner"}',
                encoding="utf-8",
            )
            result = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="reclaim-dead-lock",
            )
            self.assertTrue(result["applied"], result)
            self.assertFalse(lock.exists())

    @unittest.skipUnless(os.name == "nt", "Windows-specific liveness probe")
    def test_windows_liveness_probe_does_not_call_os_kill(self):
        with mock.patch.object(
            repair.os,
            "kill",
            side_effect=AssertionError("os.kill(pid, 0) is destructive on Windows"),
        ):
            self.assertEqual(repair._process_state(os.getpid()), "alive")

    def test_unprobeable_live_process_lock_is_not_stolen(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            lock = target.with_name(f".{target.name}.lineage-detective.lock")
            lock.write_text(
                json.dumps({
                    "created_unix": time.time(),
                    "pid": os.getpid(),
                    "token": "unprobeable-owner",
                }),
                encoding="utf-8",
            )
            with mock.patch.object(repair, "_process_state", return_value="unknown"):
                result = repair.apply_verified_repair(
                    receipt,
                    target_file=target,
                    approval="must-not-steal",
                )
            self.assertEqual(result["state"], "apply_busy")
            self.assertFalse(result["applied"])
            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(lock.exists())

    def test_human_edit_after_backup_is_not_overwritten(self):
        original = b"select legacy_email as email\n"
        human = b"select human_edit\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            real_read = Path.read_bytes
            target_reads = 0

            def intercept_read(path):
                nonlocal target_reads
                if path == target:
                    target_reads += 1
                    if target_reads == 2:
                        path.write_bytes(human)
                return real_read(path)

            with mock.patch.object(Path, "read_bytes", intercept_read):
                result = repair.apply_verified_repair(
                    receipt,
                    target_file=target,
                    approval="human-race",
                )
            self.assertEqual(result["state"], "apply_rejected")
            self.assertIn("during implementation", result["error"])
            self.assertEqual(target.read_bytes(), human)

    def test_failed_apply_rolls_back_and_returns_a_receipt_instead_of_crashing(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            calls = 0

            def fail_once_then_restore(path, content):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("simulated apply write failure")
                path.write_bytes(content)

            with mock.patch.object(repair, "_atomic_write", side_effect=fail_once_then_restore):
                result = repair.apply_verified_repair(
                    receipt,
                    target_file=target,
                    approval="unit-test-apply-button",
                )
            self.assertEqual(result["state"], "apply_failed")
            self.assertTrue(result["rolled_back"], result)
            self.assertEqual(target.read_bytes(), original)
            self.assertIn("apply_receipt_sha256", result)

    def test_failed_restore_keeps_the_backup_and_returns_a_receipt(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            applied = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-apply-button",
            )
            backup = Path(applied["backup_file"])
            with mock.patch.object(repair, "_atomic_write", side_effect=OSError("simulated restore failure")):
                result = repair.restore_applied_repair(
                    applied,
                    approval="unit-test-restore-button",
                )
            self.assertEqual(result["state"], "restore_failed")
            self.assertFalse(result["restored"])
            self.assertTrue(backup.is_file())
            self.assertIn("restore_receipt_sha256", result)

    def test_restore_rejects_a_tampered_apply_receipt(self):
        original = b"select legacy_email as email\n"
        receipt = verified_receipt(VALID_SQL, original)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stg_customers.sql"
            target.write_bytes(original)
            applied = repair.apply_verified_repair(
                receipt,
                target_file=target,
                approval="unit-test-apply-button",
            )
            tampered = dict(applied)
            tampered["before_sha256"] = "0" * 64
            result = repair.restore_applied_repair(
                tampered,
                approval="unit-test-restore-button",
            )
            self.assertEqual(result["state"], "restore_rejected")
            self.assertIn("integrity", result["error"].lower())


if __name__ == "__main__":
    unittest.main()
