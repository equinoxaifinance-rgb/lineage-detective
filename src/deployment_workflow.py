"""Verified self-hosted deployment for an already-proven Lineage Detective repair.

The customer supplies the environment-specific address once: a working directory and four
shell-free commands for deploy, live verification, rollback, and rollback verification. This
module supplies the reusable control logic: validate the exact applied bytes, deploy, read the
real downstream state, and automatically restore the file plus run the rollback path on failure.

This is deliberately unavailable as an arbitrary-command feature in the public hosted app. It is
for a customer-controlled Lineage Detective process running inside the customer's own environment,
where their existing credential manager supplies any provider credentials to child processes.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from .remediation_connectors import run_project_validation
    from .repair import restore_applied_repair
except ImportError:  # Streamlit adds src/ directly to sys.path.
    from remediation_connectors import run_project_validation
    from repair import restore_applied_repair


CommandRunner = Callable[..., dict[str, Any]]
ProgressCallback = Callable[[str, str], None]
_REQUIRED_COMMANDS = (
    "deploy_command",
    "verify_command",
    "rollback_command",
    "rollback_verify_command",
)


def _hash_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _valid_apply_receipt(receipt: dict[str, Any]) -> tuple[bool, str]:
    if receipt.get("state") != "applied_verified" or receipt.get("applied") is not True:
        return False, "A verified exact-byte implementation receipt is required before deployment."
    unsigned = dict(receipt)
    supplied = str(unsigned.pop("apply_receipt_sha256", ""))
    if not supplied or supplied != _hash_json(unsigned):
        return False, "Implementation receipt integrity verification failed."
    target_text = str(receipt.get("target_file") or "")
    if not target_text:
        return False, "The implementation receipt does not identify its target file."
    target = Path(target_text)
    if not target.is_file() or target.is_symlink():
        return False, "The implemented target file is unavailable or is a symbolic link."
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != str(receipt.get("after_sha256") or ""):
        return False, "The implemented file changed after verification; deployment was refused."
    return True, "verified"


def _validate_profile(
    profile: dict[str, Any], apply_receipt: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    if str(profile.get("kind") or "") != "self_hosted_commands":
        return None, "Choose a supported self-hosted deployment profile."
    try:
        root = Path(str(profile.get("cwd") or "")).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, f"Deployment working directory is unavailable: {type(exc).__name__}."
    if not root.is_dir() or root.is_symlink():
        return None, "Deployment working directory must be a real directory."

    target = Path(str(apply_receipt["target_file"])).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError:
        return None, "The repaired file must be inside the deployment working directory."

    try:
        timeout_seconds = min(
            max(float(profile.get("timeout_seconds") or 300), 1), 1800
        )
    except (TypeError, ValueError):
        return None, "Deployment timeout must be a number from 1 to 1800 seconds."
    normalized: dict[str, Any] = {
        "kind": "self_hosted_commands",
        "name": str(profile.get("name") or "Customer deployment").strip()[:120],
        "cwd": str(root),
        "timeout_seconds": timeout_seconds,
    }
    for key in _REQUIRED_COMMANDS:
        value = profile.get(key)
        if isinstance(value, str):
            value = value.strip()
        elif isinstance(value, (list, tuple)):
            value = [str(part) for part in value if str(part)]
        if not value:
            return None, f"{key.replace('_', ' ').capitalize()} is required."
        normalized[key] = value
    return normalized, None


def _command_evidence(
    receipt: dict[str, Any] | None, command: str | list[str]
) -> dict[str, Any]:
    """Keep command output and possible command-line secrets out of the deployment receipt."""
    source = receipt or {}
    fingerprint = command if isinstance(command, str) else list(command)
    return {
        "attempted": receipt is not None,
        "verified": source.get("verified") is True,
        "exit_code": source.get("exit_code"),
        "command_sha256": hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "output_sha256": source.get("output_sha256"),
    }


def run_verified_deployment(
    apply_receipt: dict[str, Any],
    *,
    profile: dict[str, Any],
    approval: str | None,
    allow_local_execution: bool = False,
    on_progress: ProgressCallback | None = None,
    command_runner: CommandRunner | None = None,
    restore_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deploy, independently verify, and automatically roll back an unverified release."""
    result: dict[str, Any] = {
        "state": "deployment_rejected",
        "deployed": False,
        "verified": False,
        "rollback_attempted": False,
        "rollback_verified": False,
        "apply_receipt_sha256": apply_receipt.get("apply_receipt_sha256"),
    }
    if not approval or not str(approval).strip():
        result["error"] = "Deployment requires the user's explicit approval."
        result["deployment_receipt_sha256"] = _hash_json(result)
        return result
    if not allow_local_execution:
        result["error"] = (
            "Self-hosted command deployment is disabled in this process. "
            "Run Lineage Detective inside the customer's controlled environment."
        )
        result["deployment_receipt_sha256"] = _hash_json(result)
        return result

    apply_valid, apply_reason = _valid_apply_receipt(apply_receipt)
    if not apply_valid:
        result["error"] = apply_reason
        result["deployment_receipt_sha256"] = _hash_json(result)
        return result
    normalized, profile_error = _validate_profile(profile, apply_receipt)
    if profile_error or normalized is None:
        result["error"] = profile_error
        result["deployment_receipt_sha256"] = _hash_json(result)
        return result

    runner = command_runner or run_project_validation
    restore = restore_runner or restore_applied_repair
    progress = on_progress or (lambda _phase, _detail: None)
    result.update(
        state="deployment_started",
        profile_name=normalized["name"],
        profile_sha256=_hash_json({
            key: (
                hashlib.sha256(
                    json.dumps(normalized[key], sort_keys=True).encode("utf-8")
                ).hexdigest()
                if key in _REQUIRED_COMMANDS else normalized[key]
            )
            for key in normalized
        }),
        target_file=str(Path(str(apply_receipt["target_file"])).resolve()),
    )

    deploy_receipt = verify_receipt = None
    rollback_receipt = rollback_verify_receipt = None
    restore_receipt = None
    failure: str | None = None
    try:
        progress("deploying", "Trace is deploying the exact hash-verified repair.")
        deploy_receipt = runner(
            normalized["deploy_command"], cwd=normalized["cwd"],
            timeout=normalized["timeout_seconds"],
        )
        if deploy_receipt.get("verified") is not True:
            failure = "The deployment command did not complete successfully."
        else:
            progress(
                "verifying_live",
                "Trace is checking the real downstream system, not the command response.",
            )
            verify_receipt = runner(
                normalized["verify_command"], cwd=normalized["cwd"],
                timeout=normalized["timeout_seconds"],
            )
            if verify_receipt.get("verified") is not True:
                failure = "The deployment command passed, but the live health check did not."
    except Exception as exc:
        # Exception strings can echo command-line arguments. Keep only the class in the receipt.
        failure = f"Deployment execution failed: {type(exc).__name__}."

    if failure is None:
        result.update(
            state="deployed_verified",
            deployed=True,
            verified=True,
            deploy=_command_evidence(deploy_receipt, normalized["deploy_command"]),
            live_verification=_command_evidence(
                verify_receipt, normalized["verify_command"]
            ),
        )
        result["deployment_receipt_sha256"] = _hash_json(result)
        try:
            # A terminal UI refresh failure must not erase a fully verified external outcome.
            progress(
                "deployment_complete",
                "The deployment and independent live readback both passed.",
            )
        except Exception:
            pass
        return result

    try:
        # Rollback is a recovery obligation. A repeated UI cancellation or rendering error cannot
        # be allowed to interrupt it after a deploy was attempted.
        progress(
            "rolling_back",
            "Live proof did not pass. Trace is restoring the prior bytes and rollback path.",
        )
    except Exception:
        pass
    rollback_error: str | None = None
    try:
        restore_receipt = restore(
            apply_receipt,
            approval=f"{str(approval).strip()} / automatic deployment rollback",
        )
        if restore_receipt.get("restored") is not True:
            rollback_error = "The local source backup could not be restored."
        else:
            rollback_receipt = runner(
                normalized["rollback_command"], cwd=normalized["cwd"],
                timeout=normalized["timeout_seconds"],
            )
            if rollback_receipt.get("verified") is not True:
                rollback_error = "The rollback command did not complete successfully."
            else:
                rollback_verify_receipt = runner(
                    normalized["rollback_verify_command"], cwd=normalized["cwd"],
                    timeout=normalized["timeout_seconds"],
                )
                if rollback_verify_receipt.get("verified") is not True:
                    rollback_error = "The rollback command passed, but rollback readback did not."
    except Exception as exc:
        rollback_error = f"Rollback execution failed: {type(exc).__name__}."

    rollback_verified = rollback_error is None
    result.update(
        state=(
            "deployment_failed_rollback_verified"
            if rollback_verified else "deployment_failed_rollback_unverified"
        ),
        error=failure,
        rollback_attempted=True,
        rollback_verified=rollback_verified,
        rollback_error=rollback_error,
        deploy=_command_evidence(deploy_receipt, normalized["deploy_command"]),
        live_verification=_command_evidence(
            verify_receipt, normalized["verify_command"]
        ),
        local_restore={
            "attempted": restore_receipt is not None,
            "restored": (restore_receipt or {}).get("restored") is True,
            "restore_receipt_sha256": (restore_receipt or {}).get(
                "restore_receipt_sha256"
            ),
        },
        rollback=_command_evidence(
            rollback_receipt, normalized["rollback_command"]
        ),
        rollback_verification=_command_evidence(
            rollback_verify_receipt, normalized["rollback_verify_command"]
        ),
    )
    result["deployment_receipt_sha256"] = _hash_json(result)
    try:
        progress(
            "rollback_complete" if rollback_verified else "error",
            (
                "The failed release was rolled back and the prior state was verified."
                if rollback_verified
                else "Deployment proof failed and the rollback could not be fully verified."
            ),
        )
    except Exception:
        pass
    return result
