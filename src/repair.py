"""Approval-gated repair-and-verify for Lineage Detective.

This module deliberately has two separate phases:

* ``propose_repair`` can generate a narrowly scoped dbt-model diff after a schema-drift diagnosis.
  It changes nothing.
* ``execute_sandbox_trial`` runs that exact approved diff only in a disposable dbt + DuckDB
  sandbox, captures a receipt, verifies a real before/after assertion, and restores the broken
  sandbox model afterwards.

There is no production connector and no production apply path in this module.  A sandbox pass is
useful evidence, not a production guarantee.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
DEFAULT_SANDBOX = HERE.parent / "repair_sandbox"
MODEL_RELATIVE_PATH = Path("models") / "stg_customers.sql"
ASSERTION_THRESHOLD = 0.90
DBT_TIMEOUT_SECONDS = 90

BROKEN_SQL = """-- staging model: types + maps the CRM customer export into the analytics schema.
-- CRM export v2 exposes the populated contact address as `email_address`; this model still maps
-- the legacy `email` field, so downstream contactability data resolves NULL.
select
    customer_id,
    full_name,
    email as email,
    created_at
from {{ ref('raw_customers') }}
"""

REPRESENTATIVENESS = (
    "This result was verified only in an isolated dbt + DuckDB sandbox with representative demo "
    "data. It does not prove production safety: SQL dialect, data volume, permissions, scheduling, "
    "concurrency, and downstream contracts can differ. The proposed patch was not applied to "
    "production and must be reviewed, tested, and approved in the target environment."
)

BLOCKED_SQL_TOKENS = re.compile(
    r"\b(drop|delete|insert|update|merge|alter|create|attach|copy|install|load|pragma|call)\b", re.I
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dbt_executable() -> str:
    return shutil.which("dbt") or str(Path(sys.executable).parent / "Scripts" / "dbt.exe")


def _model_path(sandbox: Path) -> Path:
    return sandbox / MODEL_RELATIVE_PATH


def _write_model(sandbox: Path, sql: str) -> None:
    path = _model_path(sandbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sql.rstrip() + "\n", encoding="utf-8", newline="\n")


def _dbt(sandbox: Path, *args: str) -> tuple[bool, str, int | None]:
    """Run dbt in the sandbox and bound the wait so a judge never gets an infinite spinner."""
    command = [_dbt_executable(), *args, "--project-dir", str(sandbox), "--profiles-dir", str(sandbox), "--quiet"]
    try:
        result = subprocess.run(
            command,
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=DBT_TIMEOUT_SECONDS,
            env={**os.environ, "DBT_PROFILES_DIR": str(sandbox)},
        )
        output = (result.stdout + result.stderr)[-1600:]
        return result.returncode == 0, output, result.returncode
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or ""))[-1600:]
        return False, f"dbt timed out after {DBT_TIMEOUT_SECONDS}s\n{output}", None


def _email_fill_rate(sandbox: Path) -> tuple[int, int]:
    import duckdb

    con = duckdb.connect(str(sandbox / "sandbox.duckdb"), read_only=True)
    try:
        total = con.execute("select count(*) from stg_customers").fetchone()[0]
        filled = con.execute(
            "select count(*) from stg_customers where email is not null and email <> ''"
        ).fetchone()[0]
        return int(filled), int(total)
    finally:
        con.close()


def _assertion(filled: int, total: int) -> dict[str, Any]:
    rate = (filled / total) if total else 0.0
    return {
        "name": f"email_fill_rate >= {ASSERTION_THRESHOLD}",
        "filled": filled,
        "total": total,
        "rate": round(rate, 4),
        "passed": rate >= ASSERTION_THRESHOLD,
    }


def _safe_generated_sql(sql: str | None) -> tuple[bool, str]:
    """Only allow one read-only model query against the sandbox's declared raw input."""
    if not isinstance(sql, str) or not sql.strip():
        return False, "The proposed model SQL was empty."
    normalized = re.sub(r"--[^\n]*", "", sql).strip().lower()
    if not normalized.startswith("select"):
        return False, "The proposed model must be a single SELECT statement."
    if ";" in normalized.rstrip(";") or BLOCKED_SQL_TOKENS.search(normalized):
        return False, "The proposed model contains a non-read-only SQL operation."
    if "ref('raw_customers')" not in normalized and 'ref("raw_customers")' not in normalized:
        return False, "The proposed model must read only the sandbox raw_customers input."
    if "email_address" not in normalized or not re.search(r"email_address\s+as\s+email", normalized):
        return False, "The proposed model does not map email_address to the expected email output."
    return True, "ok"


def _schema_drift_context(report: dict, evidence: list[Any]) -> tuple[dict[str, Any] | None, str]:
    top = (report.get("suspects") or [{}])[0]
    why = " ".join((str(top.get("why", "")), str(report.get("summary", "")))).lower()
    if not any(term in why for term in ("schema", "rename", "column", "mapping", "email")):
        return None, "The top diagnosis is not a schema-mapping repair class."
    raw = next((n for n in evidence if "raw.customers" in str(getattr(n, "urn", ""))), None)
    staging = next((n for n in evidence if "stg_customers" in str(getattr(n, "urn", ""))), None)
    if not raw or not staging:
        return None, "The schema-drift repair needs both raw.customers and stg_customers evidence."
    return {
        "top_urn": str(top.get("urn", "")),
        "diagnosis": str(top.get("why", "")),
        "upstream_columns": list(getattr(raw, "schema_fields", []) or []),
        "downstream_columns": list(getattr(staging, "schema_fields", []) or []),
    }, "ok"


def _llm_generate_fix(llm: Any, context: dict[str, Any], *, model: str) -> tuple[bool, str | None, str]:
    prompt = (
        "You are a senior analytics engineer. Return strict JSON only: "
        '{"applicable": boolean, "fixed_sql": string|null, "rationale": string}. '
        "Generate one read-only dbt SELECT model for a schema mapping repair. Preserve "
        "{{ ref('raw_customers') }} and map email_address as email. Do not use DDL, DML, macros, "
        "or any external table.\n\n"
        f"Diagnosis: {context['diagnosis']}\n"
        f"Upstream columns: {context['upstream_columns']}\n"
        f"Downstream columns: {context['downstream_columns']}\n"
        f"Broken model:\n{BROKEN_SQL}"
    )
    response = llm.messages.create(
        model=model, max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(block, "text", "") for block in response.content
                   if getattr(block, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False, None, "The model did not return valid JSON for a repair proposal."
    return bool(parsed.get("applicable")), parsed.get("fixed_sql"), str(parsed.get("rationale", ""))


def propose_repair(
    llm: Any,
    report: dict,
    evidence: list[Any],
    *,
    model: str = "claude-sonnet-5",
    fix_generator: Callable[[dict[str, Any]], tuple[bool, str | None, str]] | None = None,
) -> dict | None:
    """Create a reviewable repair proposal. This function never writes or runs the sandbox."""
    context, reason = _schema_drift_context(report, evidence)
    if context is None:
        return None
    generator = fix_generator or (lambda c: _llm_generate_fix(llm, c, model=model))
    applicable, fixed_sql, rationale = generator(context)
    if not applicable or not fixed_sql:
        return {
            "state": "not_applicable",
            "attempted": False,
            "applicable": False,
            "reason": rationale or reason,
        }
    safe, safety_reason = _safe_generated_sql(fixed_sql)
    if not safe:
        return {
            "state": "proposal_rejected",
            "attempted": False,
            "applicable": True,
            "reason": f"Generated proposal rejected before execution: {safety_reason}",
        }
    diff = "".join(difflib.unified_diff(
        BROKEN_SQL.splitlines(True), fixed_sql.rstrip().splitlines(True),
        fromfile="a/models/stg_customers.sql", tofile="b/models/stg_customers.sql",
    ))
    return {
        "state": "approval_required",
        "attempted": False,
        "applicable": True,
        "repair_id": uuid.uuid4().hex,
        "action_type": "schema_mapping_dbt_model",
        "target": "analytics.staging.stg_customers",
        "rationale": rationale,
        "diff": diff,
        "fixed_sql": fixed_sql.rstrip() + "\n",
        "proposal_sha256": _sha256(fixed_sql.rstrip() + "\n"),
        "approval_required": "A human must approve this exact diff before a sandbox-only trial.",
        "production_apply": "Not available. This feature never applies changes to production.",
        "representativeness": REPRESENTATIVENESS,
    }


def execute_sandbox_trial(
    proposal: dict,
    *,
    approval: str | None,
    sandbox: Path | str = DEFAULT_SANDBOX,
) -> dict:
    """Execute exactly one approved proposal in the isolated sandbox and return a receipt.

    ``approval`` is intentionally explicit. A caller cannot accidentally execute a proposal merely
    by rendering it, and an unapproved proposal does not mutate even the sandbox.
    """
    if not approval or not str(approval).strip():
        return {**proposal, "state": "approval_required", "attempted": False,
                "error": "Sandbox execution requires an explicit human approval."}
    sandbox = Path(sandbox)
    fixed_sql = proposal.get("fixed_sql")
    safe, reason = _safe_generated_sql(fixed_sql)
    if proposal.get("state") != "approval_required" or not safe:
        return {**proposal, "state": "rejected", "attempted": False,
                "error": reason if not safe else "Only a current approval-required proposal may run."}
    if not (sandbox / "dbt_project.yml").is_file() or not (sandbox / "profiles.yml").is_file():
        return {**proposal, "state": "sandbox_unavailable", "attempted": True,
                "verified": False, "error": "The isolated dbt sandbox is incomplete."}

    started = time.time()
    receipt: dict[str, Any] = {
        **proposal,
        "state": "sandbox_running",
        "attempted": True,
        "approved_by": str(approval).strip(),
        "sandbox": str(sandbox),
        "production_apply": "Not available. No production system was contacted.",
        "representativeness": REPRESENTATIVENESS,
    }
    rollback_ok = False
    try:
        _write_model(sandbox, BROKEN_SQL)
        seed_ok, seed_log, seed_code = _dbt(sandbox, "seed", "--full-refresh")
        broken_ok, broken_log, broken_code = _dbt(sandbox, "run")
        receipt["seed"] = {"ok": seed_ok, "exit_code": seed_code, "log": seed_log}
        receipt["broken_build"] = {"ok": broken_ok, "exit_code": broken_code, "log": broken_log}
        if not (seed_ok and broken_ok):
            receipt.update(state="sandbox_failed", verified=False,
                           error="Could not construct the known-broken sandbox baseline.")
            return receipt
        receipt["before"] = _assertion(*_email_fill_rate(sandbox))

        _write_model(sandbox, str(fixed_sql))
        fixed_ok, fixed_log, fixed_code = _dbt(sandbox, "run")
        receipt["fixed_build"] = {"ok": fixed_ok, "exit_code": fixed_code, "log": fixed_log}
        if fixed_ok:
            receipt["after"] = _assertion(*_email_fill_rate(sandbox))
        else:
            receipt["after"] = None
        before = receipt["before"]
        after = receipt["after"] or {"passed": False}
        receipt["verified"] = bool((not before["passed"]) and fixed_ok and after["passed"])
        receipt["state"] = "sandbox_verified" if receipt["verified"] else "sandbox_failed"
        if not receipt["verified"]:
            receipt["error"] = "The exact approved proposal did not flip the sandbox assertion from FAIL to PASS."
        return receipt
    except Exception as exc:
        receipt.update(state="sandbox_failed", verified=False, error=f"{type(exc).__name__}: {exc}")
        return receipt
    finally:
        # Restore both the source model and the materialized table so future trials start broken.
        try:
            _write_model(sandbox, BROKEN_SQL)
            rollback_ok, rollback_log, rollback_code = _dbt(sandbox, "run")
            receipt["rollback"] = {"ok": rollback_ok, "exit_code": rollback_code, "log": rollback_log}
        except Exception as exc:
            receipt["rollback"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        receipt["rollback_verified"] = bool(rollback_ok)
        receipt["duration_seconds"] = round(time.time() - started, 3)
        receipt["receipt_sha256"] = _sha256(json.dumps(receipt, sort_keys=True, default=str))


def receipt_for_display(receipt: dict) -> str:
    """Stable, human-readable receipt for the UI and a downloadable JSON artifact."""
    return json.dumps(receipt, indent=2, sort_keys=True, default=str)


def build_handoff_packet(receipt: dict) -> bytes:
    """Create a human-implementation packet after, and only after, a verified sandbox trial.

    The packet is deliberately an offline handoff: it contains the exact reviewed diff and the
    verification receipt, but it has no production credential, connector, or apply command.
    """
    if not receipt.get("verified"):
        raise ValueError("A human handoff packet requires a verified sandbox receipt.")
    diff = str(receipt.get("diff") or "")
    sql = str(receipt.get("fixed_sql") or "")
    readme = (
        "# Lineage Detective — Human Implementation Handoff\n\n"
        "This package was produced after a verified isolated sandbox trial. It is not a production deployment.\n\n"
        "1. Review `proposed-change.diff` against the target repository.\n"
        "2. Re-run the target environment's tests, permissions checks, and rollout process.\n"
        "3. Apply only through your governed production change process.\n\n"
        "The attached receipt records the exact sandbox trial and its representativeness boundary.\n"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme)
        archive.writestr("proposed-change.diff", diff)
        archive.writestr("proposed-model.sql", sql)
        archive.writestr("sandbox-verification-receipt.json", receipt_for_display(receipt))
    return out.getvalue()
