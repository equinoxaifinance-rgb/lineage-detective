from __future__ import annotations

import unittest

from src import repair as repair_module
from src.autonomous_workflow import run_approved_workflow


class AutonomousWorkflowTests(unittest.TestCase):
    @staticmethod
    def _receipt(repair_id: str) -> dict:
        fixed = "select 1 as repaired\n"
        return repair_module._seal_receipt({
            "repair_id": repair_id,
            "state": "sandbox_verified",
            "verified": True,
            "rollback_verified": True,
            "fixed_sql": fixed,
            "proposal_sha256": repair_module._sha256(fixed),
            "source_sha256": repair_module._sha256("select 0\n"),
        })

    def test_one_approval_runs_verified_sandbox_apply_and_handoff(self):
        calls = []

        def sandbox(repair, *, approval, on_progress=None):
            calls.append(("sandbox", repair["repair_id"], approval, bool(on_progress)))
            return self._receipt(repair["repair_id"])

        def apply(receipt, *, target_file, approval):
            calls.append(("apply", receipt["repair_id"], target_file, approval))
            return {"applied": True, "verified": True}

        def handoff(receipt):
            calls.append(("handoff", receipt["repair_id"]))
            return b"verified-packet"

        result = run_approved_workflow(
            {"repair": {"state": "approval_required", "repair_id": "repair-1"}},
            approval="one-click-user-approval",
            apply_target="C:/safe/demo.sql",
            on_progress=lambda _phase, _detail: None,
            sandbox_runner=sandbox,
            applier=apply,
            handoff_builder=handoff,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["state"], "verified_workflow_complete")
        self.assertEqual(result["handoff_packet"], b"verified-packet")
        self.assertEqual(calls[0], ("sandbox", "repair-1", "one-click-user-approval", True))
        self.assertEqual(calls[1], ("handoff", "repair-1"))
        self.assertEqual(calls[2], ("apply", "repair-1", "C:/safe/demo.sql", "one-click-user-approval"))

    def test_failed_sandbox_cannot_apply_or_build_handoff(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("downstream action must not run")

        result = run_approved_workflow(
            {"repair": {"state": "approval_required", "repair_id": "repair-2"}},
            approval="one-click-user-approval",
            sandbox_runner=lambda *_args, **_kwargs: {"verified": False, "error": "failed"},
            applier=forbidden,
            handoff_builder=forbidden,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["state"], "sandbox_not_verified")
        self.assertIsNone(result["apply_receipt"])
        self.assertIsNone(result["handoff_packet"])

    def test_missing_rollback_proof_blocks_apply_and_handoff(self):
        calls = []
        receipt = self._receipt("repair-rollback")
        receipt["rollback_verified"] = False
        repair_module._seal_receipt(receipt)
        result = run_approved_workflow(
            {"repair": {"state": "approval_required", "repair_id": "repair-rollback"}},
            approval="one-click-user-approval",
            apply_target="C:/safe/demo.sql",
            sandbox_runner=lambda *_args, **_kwargs: receipt,
            applier=lambda *_args, **_kwargs: calls.append("apply"),
            handoff_builder=lambda *_args, **_kwargs: calls.append("handoff"),
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["state"], "sandbox_not_verified")
        self.assertEqual(calls, [])

    def test_handoff_packaging_failure_happens_before_any_apply(self):
        calls = []

        def explode(_receipt):
            raise RuntimeError("zip failed")

        with self.assertRaisesRegex(RuntimeError, "zip failed"):
            run_approved_workflow(
                {"repair": {"state": "approval_required", "repair_id": "repair-4"}},
                approval="one-click-user-approval",
                apply_target="C:/safe/demo.sql",
                sandbox_runner=lambda *_args, **_kwargs: self._receipt("repair-4"),
                applier=lambda *_args, **_kwargs: calls.append("apply"),
                handoff_builder=explode,
            )
        self.assertEqual(calls, [])

    def test_missing_explicit_approval_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "explicit workflow approval"):
            run_approved_workflow(
                {"repair": {"state": "approval_required", "repair_id": "repair-3"}},
                approval="",
            )


if __name__ == "__main__":
    unittest.main()
