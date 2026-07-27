"""One-approval orchestration for Lineage Detective's verified repair path.

The caller chooses the scope before execution.  This module does not invent a target,
merge a pull request, or bypass verification: it runs the proposed change in the sandbox,
requires a verified receipt, optionally applies those exact bytes to the selected target,
optionally deploys and reads back the live result, and prepares the same human-readable handoff.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from .deployment_workflow import run_verified_deployment
    from .repair import (
        apply_verified_repair,
        build_handoff_packet,
        execute_sandbox_trial,
        verify_sandbox_receipt,
    )
except ImportError:  # App adds src/ to sys.path and imports this module directly.
    from deployment_workflow import run_verified_deployment
    from repair import (
        apply_verified_repair,
        build_handoff_packet,
        execute_sandbox_trial,
        verify_sandbox_receipt,
    )


def run_approved_workflow(
    report: dict[str, Any],
    *,
    approval: str,
    apply_target: str | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    sandbox_runner: Callable[..., dict[str, Any]] | None = None,
    handoff_builder: Callable[[dict[str, Any]], bytes] | None = None,
    applier: Callable[..., dict[str, Any]] | None = None,
    deployment_profile: dict[str, Any] | None = None,
    deployment_runner: Callable[..., dict[str, Any]] | None = None,
    allow_local_deployment: bool = False,
) -> dict[str, Any]:
    """Run sandbox -> optional exact-byte apply -> optional verified deploy -> handoff."""
    if not approval or not approval.strip():
        raise ValueError("An explicit workflow approval is required")
    repair = report.get("repair") or {}
    if repair.get("state") != "approval_required":
        return {
            "state": "no_verified_repair_available",
            "verified": False,
            "repair_receipt": None,
            "apply_receipt": None,
            "deployment_receipt": None,
            "handoff_packet": None,
        }

    run_sandbox = sandbox_runner or execute_sandbox_trial
    make_handoff = handoff_builder or build_handoff_packet
    apply_repair = applier or apply_verified_repair

    receipt = run_sandbox(repair, approval=approval, on_progress=on_progress)
    receipt_valid, receipt_reason = verify_sandbox_receipt(receipt)
    if not receipt_valid:
        return {
            "state": "sandbox_not_verified",
            "verified": False,
            "repair_receipt": receipt,
            "apply_receipt": None,
            "deployment_receipt": None,
            "handoff_packet": None,
            "error": receipt_reason,
        }

    # Build the recovery/handoff artifact before any target file is touched. If packaging fails,
    # the workflow stops with zero implementation side effects.
    handoff = make_handoff(receipt)
    apply_receipt = None
    deployment_receipt = None
    if apply_target:
        apply_receipt = apply_repair(
            receipt,
            target_file=apply_target,
            approval=approval,
        )
        if not apply_receipt.get("applied"):
            return {
                "state": "apply_not_verified",
                "verified": False,
                "repair_receipt": receipt,
                "apply_receipt": apply_receipt,
                "deployment_receipt": None,
                "handoff_packet": handoff,
            }
    if deployment_profile:
        if not apply_receipt:
            return {
                "state": "deployment_requires_applied_repair",
                "verified": False,
                "repair_receipt": receipt,
                "apply_receipt": None,
                "deployment_receipt": None,
                "handoff_packet": handoff,
            }
        deploy = deployment_runner or run_verified_deployment
        deployment_receipt = deploy(
            apply_receipt,
            profile=deployment_profile,
            approval=approval,
            allow_local_execution=allow_local_deployment,
            on_progress=on_progress,
        )
        if deployment_receipt.get("verified") is not True:
            return {
                "state": "deployment_not_verified",
                "verified": False,
                "repair_receipt": receipt,
                "apply_receipt": apply_receipt,
                "deployment_receipt": deployment_receipt,
                "handoff_packet": handoff,
            }

    return {
        "state": "verified_workflow_complete",
        "verified": True,
        "repair_receipt": receipt,
        "apply_receipt": apply_receipt,
        "deployment_receipt": deployment_receipt,
        "handoff_packet": handoff,
    }
