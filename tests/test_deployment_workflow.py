from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from src.deployment_workflow import run_verified_deployment, verify_deployment_receipt


def _hash_json(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


class SequenceRunner:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, command, *, cwd, timeout):
        self.calls.append((command, cwd, timeout))
        outcome = self.outcomes.pop(0)
        return {
            "verified": outcome,
            "exit_code": 0 if outcome else 7,
            "output_sha256": hashlib.sha256(str(outcome).encode()).hexdigest(),
            # These must never be copied into the final deployment receipt.
            "stdout": "SECRET_OUTPUT",
            "stderr": "SECRET_ERROR",
        }


class VerifiedDeploymentTests(unittest.TestCase):
    def _applied(self, root: Path) -> tuple[dict, Path, bytes, bytes]:
        original = b"select 0 as broken\n"
        proposed = b"select 1 as repaired\n"
        target = root / "models" / "customer.sql"
        target.parent.mkdir()
        target.write_bytes(proposed)
        backup = target.with_name(
            f".{target.name}.lineage-detective-test.bak"
        )
        backup.write_bytes(original)
        receipt = {
            "state": "applied_verified",
            "applied": True,
            "target_file": str(target),
            "backup_file": str(backup),
            "before_sha256": hashlib.sha256(original).hexdigest(),
            "expected_after_sha256": hashlib.sha256(proposed).hexdigest(),
            "proposal_sha256": hashlib.sha256(proposed).hexdigest(),
            "approved_by": "test",
            "after_sha256": hashlib.sha256(proposed).hexdigest(),
            "backup_sha256": hashlib.sha256(original).hexdigest(),
            "duration_seconds": 0.1,
        }
        receipt["apply_receipt_sha256"] = _hash_json(receipt)
        return receipt, target, original, proposed

    @staticmethod
    def _profile(root: Path) -> dict:
        return {
            "kind": "self_hosted_commands",
            "name": "Production",
            "cwd": str(root),
            "deploy_command": ["deploy", "--current-source"],
            "verify_command": ["verify", "--healthy"],
            "rollback_command": ["deploy", "--restored-source"],
            "rollback_verify_command": ["verify", "--previous-healthy"],
            "timeout_seconds": 60,
        }

    def test_success_requires_deploy_and_separate_live_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, _original, proposed = self._applied(root)
            runner = SequenceRunner([True, True])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertTrue(receipt["verified"])
            self.assertTrue(receipt["deployed"])
            self.assertEqual(receipt["state"], "deployed_verified")
            self.assertEqual(target.read_bytes(), proposed)
            self.assertEqual(len(runner.calls), 2)
            self.assertNotIn("SECRET_OUTPUT", str(receipt))
            self.assertNotIn("SECRET_ERROR", str(receipt))
            self.assertEqual(len(receipt["deployment_receipt_sha256"]), 64)
            self.assertEqual(verify_deployment_receipt(receipt), (True, "verified"))

    def test_tampered_success_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, _target, _original, _proposed = self._applied(root)
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=SequenceRunner([True, True]),
            )
            receipt["profile_name"] = "tampered"
            valid, reason = verify_deployment_receipt(receipt)
            self.assertFalse(valid)
            self.assertIn("integrity", reason.lower())

    def test_failed_live_check_restores_source_and_verifies_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, original, _proposed = self._applied(root)
            runner = SequenceRunner([True, False, True, True])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertTrue(receipt["rollback_attempted"])
            self.assertTrue(receipt["rollback_verified"])
            self.assertEqual(receipt["state"], "deployment_failed_rollback_verified")
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(len(runner.calls), 4)

    def test_failed_deploy_also_enters_verified_rollback_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, original, _proposed = self._applied(root)
            runner = SequenceRunner([False, True, True])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertTrue(receipt["rollback_verified"])
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(len(runner.calls), 3)

    def test_unverified_rollback_is_never_reported_green(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, _target, _original, _proposed = self._applied(root)
            runner = SequenceRunner([True, False, False])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertFalse(receipt["rollback_verified"])
            self.assertEqual(receipt["state"], "deployment_failed_rollback_unverified")

    def test_cancel_after_deploy_cannot_interrupt_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, original, _proposed = self._applied(root)
            runner = SequenceRunner([True, True, True])

            def cancel_on_verify(phase, _detail):
                if phase in {"verifying_live", "rolling_back", "rollback_complete"}:
                    raise RuntimeError("cancel requested")

            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
                on_progress=cancel_on_verify,
            )
            self.assertFalse(receipt["verified"])
            self.assertTrue(receipt["rollback_verified"])
            self.assertEqual(target.read_bytes(), original)

    def test_cancel_before_deploy_restores_local_bytes_without_external_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, original, _proposed = self._applied(root)
            runner = SequenceRunner([])

            def cancel_before_deploy(phase, _detail):
                if phase == "deploying":
                    raise RuntimeError("cancel requested")

            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
                on_progress=cancel_before_deploy,
            )
            self.assertEqual(runner.calls, [])
            self.assertFalse(receipt["deploy_attempted"])
            self.assertFalse(receipt["rollback_attempted"])
            self.assertFalse(receipt["rollback_verified"])
            self.assertEqual(receipt["state"], "deployment_not_attempted_restore_verified")
            self.assertEqual(target.read_bytes(), original)

    def test_tampered_apply_receipt_stops_before_any_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, _target, _original, _proposed = self._applied(root)
            apply_receipt["after_sha256"] = "0" * 64
            runner = SequenceRunner([])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertIn("integrity", receipt["error"].lower())
            self.assertEqual(runner.calls, [])

    def test_target_outside_profile_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            root = Path(directory)
            apply_receipt, _target, _original, _proposed = self._applied(root)
            runner = SequenceRunner([])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(Path(other)),
                approval="approved",
                allow_local_execution=True,
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertIn("inside", receipt["error"].lower())
            self.assertEqual(runner.calls, [])

    def test_public_host_mode_default_refuses_arbitrary_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, _target, _original, _proposed = self._applied(root)
            runner = SequenceRunner([])
            receipt = run_verified_deployment(
                apply_receipt,
                profile=self._profile(root),
                approval="approved",
                command_runner=runner,
            )
            self.assertFalse(receipt["verified"])
            self.assertIn("disabled", receipt["error"].lower())
            self.assertEqual(runner.calls, [])

    def test_real_subprocess_path_deploys_and_reads_back_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, _target, _original, proposed = self._applied(root)
            live = root / "live.sql"
            profile = self._profile(root)
            copy_script = (
                "from pathlib import Path;"
                "Path('live.sql').write_bytes(Path('models/customer.sql').read_bytes())"
            )
            verify_script = (
                "from pathlib import Path;"
                f"raise SystemExit(0 if Path('live.sql').read_bytes()=={proposed!r} else 9)"
            )
            profile.update(
                deploy_command=[sys.executable, "-c", copy_script],
                verify_command=[sys.executable, "-c", verify_script],
                rollback_command=[sys.executable, "-c", copy_script],
                rollback_verify_command=[sys.executable, "-c", "raise SystemExit(0)"],
            )
            receipt = run_verified_deployment(
                apply_receipt,
                profile=profile,
                approval="approved",
                allow_local_execution=True,
            )
            self.assertTrue(receipt["verified"])
            self.assertEqual(live.read_bytes(), proposed)

    def test_real_subprocess_failure_restores_and_redeploys_previous_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_receipt, target, original, _proposed = self._applied(root)
            live = root / "live.sql"
            copy_script = (
                "from pathlib import Path;"
                "Path('live.sql').write_bytes(Path('models/customer.sql').read_bytes())"
            )
            rollback_verify = (
                "from pathlib import Path;"
                f"raise SystemExit(0 if Path('live.sql').read_bytes()=={original!r} else 9)"
            )
            profile = self._profile(root)
            profile.update(
                deploy_command=[sys.executable, "-c", copy_script],
                verify_command=[sys.executable, "-c", "raise SystemExit(8)"],
                rollback_command=[sys.executable, "-c", copy_script],
                rollback_verify_command=[sys.executable, "-c", rollback_verify],
            )
            receipt = run_verified_deployment(
                apply_receipt,
                profile=profile,
                approval="approved",
                allow_local_execution=True,
            )
            self.assertFalse(receipt["verified"])
            self.assertTrue(receipt["rollback_verified"])
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(live.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
