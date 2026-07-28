"""Production remediation adapters used after an evidence-bound repair is verified.

DataHub is the control plane for discovery and containment.  These adapters reach the
system that can actually implement or validate a repair.  Every adapter returns a
hash-bound receipt and keeps credentials out of that receipt.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .network_policy import validate_network_url, validate_resolution
except ImportError:
    from network_policy import validate_network_url, validate_resolution


_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|replace|truncate|grant|revoke|"
    r"call|execute|copy|put|remove|undrop)\b",
    re.IGNORECASE,
)


class Transport(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None, timeout: float = 30.0,
    ) -> tuple[int, dict[str, Any]]: ...


@dataclass
class JsonTransport:
    """Small injectable JSON transport with bounded network waits."""

    allow_private: bool = False

    def _validate_url(self, url: str) -> None:
        validate_network_url(
            url,
            allow_private=self.allow_private,
            label="Connector URL",
        )

    def request(
        self, method: str, url: str, *, headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None, timeout: float = 30.0,
    ) -> tuple[int, dict[str, Any]]:
        self._validate_url(url)
        validate_resolution(url, allow_private=self.allow_private, label="Connector URL")
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(url, data=payload, method=method.upper(), headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if payload is not None else {}),
            **(headers or {}),
        })
        try:
            # Authentication-bearing connector calls never follow redirects. This prevents a
            # provider or attacker from redirecting a secret-bearing request to another host.
            class _RejectRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    raise RuntimeError(
                        f"{method.upper()} {url} returned an unexpected redirect to {newurl}"
                    )

            with build_opener(_RejectRedirect).open(
                request, timeout=max(1.0, float(timeout))
            ) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else {})
        except HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"{method.upper()} {url} returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ConnectionError(f"{method.upper()} {url} failed: {exc.reason}") from exc


def _receipt(data: dict[str, Any]) -> dict[str, Any]:
    clean = {**data}
    clean["receipt_sha256"] = hashlib.sha256(
        json.dumps(clean, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return clean


def failure_receipt(connector: str, exc: Exception) -> dict[str, Any]:
    """Turn a connector exception into a hash-bound, secret-free failure receipt."""
    error_type = type(exc).__name__
    return _receipt({
        "connector": connector,
        "applied": False,
        "verified": False,
        "error_type": error_type,
        "error_code": "connector_execution_failed",
        "error_fingerprint_sha256": hashlib.sha256(error_type.encode("utf-8")).hexdigest(),
    })


def _partial_receipt(
    connector: str,
    *,
    target: str,
    external_id: str | int | None,
    exc: Exception,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an acknowledged remote action whose readback could not be completed."""
    return _receipt({
        "connector": connector,
        "applied": True,
        "verified": False,
        "verification_state": "readback_unavailable",
        "target": target,
        "external_id": external_id,
        "error_type": type(exc).__name__,
        "recovery": "Use the external ID to inspect the provider before retrying this action.",
        **(evidence or {}),
    })


def _outcome_unknown_receipt(
    connector: str,
    *,
    target: str,
    external_id: str | int | None,
    exc: Exception,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a mutation whose response was lost before acknowledgement.

    `applied` is deliberately null rather than false: the provider may have
    committed the request. Callers must inspect the named target or request ID
    before retrying.
    """
    return _receipt({
        "connector": connector,
        "applied": None,
        "verified": False,
        "verification_state": "outcome_unknown",
        "target": target,
        "external_id": external_id,
        "error_type": type(exc).__name__,
        "recovery": (
            "Do not retry blindly. Inspect the named provider target or "
            "request ID and reconcile the remote state first."
        ),
        **(evidence or {}),
    })


def _require(value: str | None, name: str) -> str:
    if not value or not str(value).strip():
        raise ValueError(f"{name} is required")
    return str(value).strip()


@dataclass
class GitHubPullRequestConnector:
    token: str
    repository: str
    transport: Transport = field(default_factory=JsonTransport)
    api_base: str = "https://api.github.com"

    def _cleanup_branch(
        self,
        *,
        root: str,
        branch: str,
        headers: dict[str, str],
    ) -> bool:
        """Delete and independently read back an orphan branch."""
        status, _body = self.transport.request(
            "DELETE",
            f"{root}/git/refs/heads/{quote(branch, safe='')}",
            headers=headers,
        )
        if status not in {200, 204}:
            return False
        try:
            self.transport.request(
                "GET",
                f"{root}/git/ref/heads/{quote(branch, safe='')}",
                headers=headers,
            )
        except RuntimeError as exc:
            return "404" in str(exc)
        return False

    def _find_open_pull_by_head(
        self,
        *,
        root: str,
        repository: str,
        branch: str,
        commit_sha: str,
        headers: dict[str, str],
    ) -> dict[str, Any] | None:
        """Reconcile an ambiguous pull-request create by its deterministic head."""
        owner = repository.split("/", 1)[0]
        _status, pulls = self.transport.request(
            "GET",
            f"{root}/pulls?{urlencode({'state': 'open', 'head': f'{owner}:{branch}'})}",
            headers=headers,
        )
        if not isinstance(pulls, list):
            return None
        for pull in pulls:
            if not isinstance(pull, dict):
                continue
            head = pull.get("head") or {}
            if (
                head.get("ref") == branch
                and str(head.get("sha") or "") == commit_sha
                and pull.get("number")
            ):
                return pull
        return None

    def apply(
        self, *, path: str, content: str, base_branch: str, branch: str,
        title: str, body: str, expected_before_sha256: str,
        expected_proposal_sha256: str,
    ) -> dict[str, Any]:
        token = _require(self.token, "GitHub token")
        repo = _require(self.repository, "GitHub repository")
        normalized_path = path.strip("/")
        if not normalized_path or ".." in normalized_path.split("/"):
            raise ValueError("GitHub path must stay inside the repository")
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual != expected_proposal_sha256:
            raise ValueError("GitHub content hash does not match the approved repair")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "Accept": "application/vnd.github+json",
        }
        root = f"{self.api_base.rstrip('/')}/repos/{repo}"
        _, base_ref = self.transport.request(
            "GET", f"{root}/git/ref/heads/{quote(base_branch, safe='')}", headers=headers
        )
        base_sha = str(((base_ref.get("object") or {}).get("sha") or ""))
        if not base_sha:
            raise RuntimeError("GitHub did not return the base branch SHA")
        _, current = self.transport.request(
            "GET",
            f"{root}/contents/{quote(normalized_path, safe='/')}?{urlencode({'ref': base_branch})}",
            headers=headers,
        )
        source_sha = current.get("sha")
        if current.get("encoding") != "base64" or not isinstance(current.get("content"), str):
            raise RuntimeError("GitHub did not return the current file bytes for drift verification")
        try:
            encoded_current = "".join(current["content"].split())
            current_bytes = base64.b64decode(encoded_current, validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("GitHub returned invalid base64 file content") from exc
        remote_before_sha256 = hashlib.sha256(current_bytes).hexdigest()
        if remote_before_sha256 != expected_before_sha256:
            raise RuntimeError(
                "The GitHub base-branch file changed after review; no branch was created."
            )
        # Validate the target on the base branch before creating a remote branch.  If the
        # path or repository is wrong, the connector must fail without leaving an orphan ref.
        try:
            self.transport.request("POST", f"{root}/git/refs", headers=headers, body={
                "ref": f"refs/heads/{branch}", "sha": base_sha,
            })
        except Exception as exc:
            return _outcome_unknown_receipt(
                "github_pull_request",
                target=f"{repo}:{normalized_path}",
                external_id=branch,
                exc=exc,
                evidence={
                    "branch": branch,
                    "base_branch": base_branch,
                    "base_sha": base_sha,
                    "before_sha256": remote_before_sha256,
                    "content_sha256": actual,
                },
            )
        commit_sha = ""
        number: int | str | None = None
        pull_url: str | None = None
        branch_content_sha256 = ""
        try:
            update: dict[str, Any] = {
                "message": title,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if source_sha:
                update["sha"] = source_sha
            _, commit = self.transport.request(
                "PUT", f"{root}/contents/{quote(normalized_path, safe='/')}",
                headers=headers, body=update,
            )
            commit_sha = str(((commit.get("commit") or {}).get("sha") or ""))
            if not commit_sha:
                raise RuntimeError("GitHub did not return the repair commit SHA")
            _, branch_file = self.transport.request(
                "GET",
                f"{root}/contents/{quote(normalized_path, safe='/')}?{urlencode({'ref': branch})}",
                headers=headers,
            )
            if branch_file.get("encoding") != "base64" or not isinstance(
                branch_file.get("content"), str
            ):
                raise RuntimeError("GitHub did not return the committed repair bytes")
            try:
                branch_bytes = base64.b64decode(
                    "".join(branch_file["content"].split()), validate=True
                )
            except (ValueError, TypeError) as exc:
                raise RuntimeError("GitHub returned invalid committed file content") from exc
            branch_content_sha256 = hashlib.sha256(branch_bytes).hexdigest()
            if branch_content_sha256 != expected_proposal_sha256:
                raise RuntimeError("GitHub committed bytes do not match the approved repair")
            try:
                _, pull = self.transport.request(
                    "POST",
                    f"{root}/pulls",
                    headers=headers,
                    body={
                        "title": title,
                        "body": body,
                        "head": branch,
                        "base": base_branch,
                        "draft": False,
                    },
                )
            except Exception as exc:
                try:
                    recovered = self._find_open_pull_by_head(
                        root=root,
                        repository=repo,
                        branch=branch,
                        commit_sha=commit_sha,
                        headers=headers,
                    )
                except Exception:
                    recovered = None
                if recovered:
                    return _receipt({
                        "connector": "github_pull_request",
                        "applied": True,
                        "verified": True,
                        "verification_state": "recovered_by_head_lookup",
                        "target": f"{repo}:{normalized_path}",
                        "branch": branch,
                        "base_branch": base_branch,
                        "base_sha": base_sha,
                        "commit_sha": commit_sha,
                        "pull_head_sha": str(
                            ((recovered.get("head") or {}).get("sha") or "")
                        ),
                        "pull_number": recovered.get("number"),
                        "pull_url": recovered.get("html_url"),
                        "content_sha256": actual,
                        "before_sha256": remote_before_sha256,
                        "readback_sha256": branch_content_sha256,
                    })
                return _outcome_unknown_receipt(
                    "github_pull_request",
                    target=f"{repo}:{normalized_path}",
                    external_id=branch,
                    exc=exc,
                    evidence={
                        "branch": branch,
                        "base_branch": base_branch,
                        "base_sha": base_sha,
                        "commit_sha": commit_sha,
                        "before_sha256": remote_before_sha256,
                        "content_sha256": actual,
                        "readback_sha256": branch_content_sha256,
                        "reconciliation": "No exact open pull request was confirmed by head lookup.",
                    },
                )
            number = pull.get("number")
            pull_url = pull.get("html_url")
            if not number:
                raise RuntimeError("GitHub did not return the pull-request number")
            _, verified = self.transport.request(
                "GET", f"{root}/pulls/{number}", headers=headers
            )
            is_open = verified.get("state") == "open"
            pull_head_sha = str(((verified.get("head") or {}).get("sha") or ""))
            exact_pull = bool(is_open and pull_head_sha == commit_sha)
        except Exception as exc:
            if number:
                return _partial_receipt(
                    "github_pull_request",
                    target=f"{repo}:{normalized_path}",
                    external_id=number,
                    exc=exc,
                    evidence={
                        "branch": branch,
                        "base_branch": base_branch,
                        "base_sha": base_sha,
                        "commit_sha": commit_sha or None,
                        "pull_number": number,
                        "pull_url": pull_url,
                        "before_sha256": remote_before_sha256,
                        "content_sha256": actual,
                    },
                )
            cleanup_verified = False
            cleanup_error_type: str | None = None
            try:
                cleanup_verified = self._cleanup_branch(
                    root=root, branch=branch, headers=headers
                )
            except Exception as cleanup_exc:
                cleanup_error_type = type(cleanup_exc).__name__
            return _receipt({
                "connector": "github_pull_request",
                "applied": not cleanup_verified,
                "verified": False,
                "verification_state": (
                    "rolled_back" if cleanup_verified else "partial_remote_state"
                ),
                "target": f"{repo}:{normalized_path}",
                "branch": branch,
                "base_branch": base_branch,
                "base_sha": base_sha,
                "commit_sha": commit_sha or None,
                "before_sha256": remote_before_sha256,
                "content_sha256": actual,
                "cleanup_attempted": True,
                "cleanup_verified": cleanup_verified,
                "error_type": type(exc).__name__,
                "cleanup_error_type": cleanup_error_type,
                "recovery": (
                    "No remote branch remains; the action can be retried."
                    if cleanup_verified
                    else "Inspect and remove the named branch before retrying."
                ),
            })
        return _receipt({
            "connector": "github_pull_request",
            "applied": bool(number),
            "verified": bool(number and exact_pull),
            "target": f"{repo}:{normalized_path}",
            "branch": branch,
            "base_branch": base_branch,
            "base_sha": base_sha,
            "commit_sha": commit_sha,
            "pull_head_sha": pull_head_sha,
            "pull_number": number,
            "pull_url": pull_url,
            "content_sha256": actual,
            "before_sha256": remote_before_sha256,
            "readback_sha256": branch_content_sha256,
        })


@dataclass
class DbtCloudConnector:
    token: str
    account_id: str
    job_id: str
    transport: Transport = field(default_factory=JsonTransport)
    api_base: str = "https://cloud.getdbt.com"

    def trigger(self, *, cause: str, steps_override: list[str] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Token {_require(self.token, 'dbt Cloud token')}"}
        url = (
            f"{self.api_base.rstrip('/')}/api/v2/accounts/"
            f"{quote(_require(self.account_id, 'dbt account ID'))}/jobs/"
            f"{quote(_require(self.job_id, 'dbt job ID'))}/run/"
        )
        body: dict[str, Any] = {"cause": cause}
        if steps_override:
            body["steps_override"] = list(steps_override)
        try:
            _, created = self.transport.request("POST", url, headers=headers, body=body)
        except Exception as exc:
            return _outcome_unknown_receipt(
                "dbt_cloud",
                target=f"account:{self.account_id}/job:{self.job_id}",
                external_id=None,
                exc=exc,
                evidence={
                    "cause_sha256": hashlib.sha256(cause.encode("utf-8")).hexdigest(),
                },
            )
        run = created.get("data") or created
        run_id = run.get("id")
        if not run_id:
            raise RuntimeError("dbt Cloud did not return a run ID")
        try:
            _, check = self.transport.request(
                "GET",
                f"{self.api_base.rstrip('/')}/api/v2/accounts/{quote(self.account_id)}/runs/{run_id}/",
                headers=headers,
            )
        except Exception as exc:
            return _partial_receipt(
                "dbt_cloud",
                target=f"account:{self.account_id}/job:{self.job_id}",
                external_id=run_id,
                exc=exc,
                evidence={"run_id": run_id},
            )
        state = (check.get("data") or check).get("status_humanized")
        return _receipt({
            "connector": "dbt_cloud",
            "applied": True,
            "verified": bool(state),
            "run_id": run_id,
            "state": state,
            "target": f"account:{self.account_id}/job:{self.job_id}",
        })


@dataclass
class AirflowConnector:
    base_url: str
    token: str
    transport: Transport = field(default_factory=JsonTransport)

    def trigger(self, *, dag_id: str, conf: dict[str, Any], logical_date: str | None = None) -> dict[str, Any]:
        dag = quote(_require(dag_id, "Airflow DAG ID"), safe="")
        run_id = f"lineage-detective-{uuid.uuid4().hex}"
        body: dict[str, Any] = {"dag_run_id": run_id, "conf": conf}
        if logical_date:
            body["logical_date"] = logical_date
        headers = {"Authorization": f"Bearer {_require(self.token, 'Airflow token')}"}
        url = f"{_require(self.base_url, 'Airflow URL').rstrip('/')}/api/v2/dags/{dag}/dagRuns"
        try:
            _, created = self.transport.request("POST", url, headers=headers, body=body)
        except Exception as exc:
            return _outcome_unknown_receipt(
                "airflow",
                target=dag_id,
                external_id=run_id,
                exc=exc,
                evidence={"run_id": run_id},
            )
        applied = created.get("dag_run_id") == run_id
        if not applied:
            raise RuntimeError("Airflow did not acknowledge the requested DAG run ID")
        try:
            _, check = self.transport.request(
                "GET", f"{url}/{quote(run_id, safe='')}", headers=headers
            )
        except Exception as exc:
            return _partial_receipt(
                "airflow",
                target=dag_id,
                external_id=run_id,
                exc=exc,
                evidence={"run_id": run_id},
            )
        return _receipt({
            "connector": "airflow",
            "applied": applied,
            "verified": bool(check.get("state")),
            "run_id": run_id,
            "state": check.get("state"),
            "target": dag_id,
        })


@dataclass
class FivetranConnector:
    api_key: str
    api_secret: str
    connection_id: str
    transport: Transport = field(default_factory=JsonTransport)
    api_base: str = "https://api.fivetran.com"

    def _headers(self) -> dict[str, str]:
        raw = f"{_require(self.api_key, 'Fivetran API key')}:{_require(self.api_secret, 'Fivetran API secret')}"
        return {"Authorization": "Basic " + base64.b64encode(raw.encode()).decode()}

    def act(self, action: str) -> dict[str, Any]:
        connection = quote(_require(self.connection_id, "Fivetran connection ID"), safe="")
        root = f"{self.api_base.rstrip('/')}/v1/connections/{connection}"
        if action not in {"pause", "resume", "sync"}:
            raise ValueError("Fivetran action must be pause, resume, or sync")
        try:
            if action == "pause":
                _, result = self.transport.request(
                    "PATCH", root, headers=self._headers(), body={"paused": True}
                )
            elif action == "resume":
                _, result = self.transport.request(
                    "PATCH", root, headers=self._headers(), body={"paused": False}
                )
            else:
                _, result = self.transport.request(
                    "POST", f"{root}/sync", headers=self._headers(), body={}
                )
        except Exception as exc:
            return _outcome_unknown_receipt(
                "fivetran",
                target=self.connection_id,
                external_id=self.connection_id,
                exc=exc,
                evidence={"action": action},
            )
        applied = bool(result)
        if not applied:
            raise RuntimeError("Fivetran did not acknowledge the requested action")
        try:
            _, check = self.transport.request("GET", root, headers=self._headers())
        except Exception as exc:
            return _partial_receipt(
                "fivetran",
                target=self.connection_id,
                external_id=self.connection_id,
                exc=exc,
                evidence={"action": action},
            )
        data = check.get("data") or check
        sync_state = (data.get("status") or {}).get("sync_state")
        verified = (
            (action == "pause" and sync_state == "paused")
            or (action == "resume" and sync_state in {"scheduled", "syncing", "rescheduled"})
            or (action == "sync" and sync_state in {"scheduled", "syncing", "rescheduled"})
        )
        return _receipt({
            "connector": "fivetran",
            "action": action,
            "applied": applied,
            "verified": verified,
            "state": sync_state,
            "target": self.connection_id,
        })


@dataclass
class SnowflakeSqlConnector:
    account_url: str
    token: str
    token_type: str = "OAUTH"
    transport: Transport = field(default_factory=JsonTransport)

    def execute(
        self, *, statement: str, warehouse: str | None = None,
        database: str | None = None, schema: str | None = None, role: str | None = None,
    ) -> dict[str, Any]:
        sql = statement.strip()
        if not sql or sql.count(";") > (1 if sql.endswith(";") else 0):
            raise ValueError("Snowflake remediation must be exactly one SQL statement")
        request_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {_require(self.token, 'Snowflake token')}",
            "X-Snowflake-Authorization-Token-Type": self.token_type,
        }
        body = {"statement": sql, "timeout": 60}
        for key, value in {
            "warehouse": warehouse, "database": database, "schema": schema, "role": role
        }.items():
            if value:
                body[key] = value
        url = (
            f"{_require(self.account_url, 'Snowflake account URL').rstrip('/')}"
            f"/api/v2/statements?{urlencode({'requestId': request_id})}"
        )
        try:
            status, result = self.transport.request(
                "POST", url, headers=headers, body=body, timeout=70
            )
        except Exception as exc:
            return _outcome_unknown_receipt(
                "snowflake_sql",
                target=self.account_url,
                external_id=request_id,
                exc=exc,
                evidence={
                    "request_id": request_id,
                    "statement_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                },
            )
        handle = result.get("statementHandle")
        if status == 202 and handle:
            status_url = (
                f"{self.account_url.rstrip('/')}/api/v2/statements/{quote(str(handle))}"
            )
            try:
                for _attempt in range(6):
                    status, result = self.transport.request(
                        "GET", status_url, headers=headers,
                    )
                    if status != 202:
                        break
            except Exception as exc:
                return _partial_receipt(
                    "snowflake_sql",
                    target=self.account_url,
                    external_id=handle,
                    exc=exc,
                    evidence={
                        "statement_handle": handle,
                        "request_id": request_id,
                        "statement_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                    },
                )
        final_handle = result.get("statementHandle") or handle
        success = (
            status == 200
            and str(result.get("sqlState") or "") == "00000"
            and bool(final_handle)
        )
        acknowledged = bool(final_handle)
        return _receipt({
            "connector": "snowflake_sql",
            "applied": acknowledged,
            "verified": success,
            "verification_state": "terminal_success" if success else (
                "still_running" if status == 202 else "terminal_failure"
            ),
            "statement_handle": final_handle,
            "request_id": request_id,
            "statement_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "target": self.account_url,
        })


@dataclass
class DataHubAssertionConnector:
    server: str
    token: str
    transport: Transport = field(default_factory=JsonTransport)

    def _create(
        self, *, mutation_name: str, input_type: str, variables: dict[str, Any],
        action: str, target: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        graphql_url = f"{_require(self.server, 'DataHub server').rstrip('/')}/api/graphql"
        headers = {"Authorization": f"Bearer {_require(self.token, 'DataHub token')}"}
        mutation = f"""
        mutation CreateMonitor($input: {input_type}!) {{
          {mutation_name}(input: $input) {{ urn }}
        }}
        """
        try:
            _, result = self.transport.request(
                "POST", graphql_url,
                headers=headers,
                body={"query": mutation, "variables": variables},
            )
        except Exception as exc:
            return _outcome_unknown_receipt(
                "datahub_assertion",
                target=target,
                external_id=None,
                exc=exc,
                evidence={"action": action, **evidence},
            )
        errors = result.get("errors")
        assertion = ((result.get("data") or {}).get(mutation_name) or {})
        urn = assertion.get("urn")
        if not urn or errors:
            return _receipt({
                "connector": "datahub_assertion",
                "action": action,
                "applied": False,
                "verified": False,
                "verification_state": "mutation_rejected",
                "assertion_urn": urn,
                "target": target,
                "errors": errors,
                **evidence,
            })
        readback_query = """
        query VerifyAssertion($urn: String!) {
          assertion(urn: $urn) { urn }
        }
        """
        try:
            _, readback = self.transport.request(
                "POST",
                graphql_url,
                headers=headers,
                body={"query": readback_query, "variables": {"urn": urn}},
            )
        except Exception as exc:
            return _partial_receipt(
                "datahub_assertion",
                target=target,
                external_id=urn,
                exc=exc,
                evidence={"action": action, "assertion_urn": urn, **evidence},
            )
        readback_errors = readback.get("errors")
        readback_urn = ((readback.get("data") or {}).get("assertion") or {}).get("urn")
        verified = bool(not readback_errors and readback_urn == urn)
        return _receipt({
            "connector": "datahub_assertion",
            "action": action,
            "applied": True,
            "verified": verified,
            "verification_state": (
                "verified_readback" if verified else "readback_mismatch"
            ),
            "assertion_urn": urn,
            "readback_urn": readback_urn,
            "target": target,
            "errors": readback_errors,
            **evidence,
        })

    def create_freshness(
        self, *, dataset_urn: str, hours: int, cron: str = "0 */2 * * *",
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        if hours < 1 or hours > 720:
            raise ValueError("Freshness lookback must be between 1 and 720 hours")
        variables = {"input": {
            "entityUrn": _require(dataset_urn, "dataset URN"),
            "schedule": {"type": "FIXED_INTERVAL", "fixedInterval": {
                "unit": "HOUR", "multiple": hours,
            }},
            "evaluationSchedule": {"timezone": timezone, "cron": cron},
            "evaluationParameters": {"sourceType": "INFORMATION_SCHEMA"},
            "mode": "ACTIVE",
        }}
        return self._create(
            mutation_name="upsertDatasetFreshnessAssertionMonitor",
            input_type="UpsertDatasetFreshnessAssertionMonitorInput",
            variables=variables,
            action="create_freshness",
            target=dataset_urn,
            evidence={"lookback_hours": hours, "schedule": cron},
        )

    def create_volume(
        self, *, dataset_urn: str, minimum: int, maximum: int,
        cron: str = "0 */4 * * *", timezone: str = "UTC",
    ) -> dict[str, Any]:
        if minimum < 0 or maximum < minimum:
            raise ValueError("Volume range must satisfy 0 <= minimum <= maximum")
        variables = {"input": {
            "entityUrn": _require(dataset_urn, "dataset URN"),
            "type": "ROW_COUNT_TOTAL",
            "rowCountTotal": {
                "operator": "BETWEEN",
                "parameters": {
                    "minValue": {"value": str(minimum), "type": "NUMBER"},
                    "maxValue": {"value": str(maximum), "type": "NUMBER"},
                },
            },
            "evaluationSchedule": {"timezone": timezone, "cron": cron},
            "evaluationParameters": {"sourceType": "INFORMATION_SCHEMA"},
            "mode": "ACTIVE",
        }}
        return self._create(
            mutation_name="upsertDatasetVolumeAssertionMonitor",
            input_type="UpsertDatasetVolumeAssertionMonitorInput",
            variables=variables,
            action="create_volume",
            target=dataset_urn,
            evidence={"minimum_rows": minimum, "maximum_rows": maximum, "schedule": cron},
        )

    def create_sql_metric(
        self, *, dataset_urn: str, statement: str, minimum: float,
        description: str, cron: str = "0 */6 * * *", timezone: str = "UTC",
    ) -> dict[str, Any]:
        sql = statement.strip()
        normalized = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL)
        if not normalized.lstrip().lower().startswith(("select ", "with ")) or sql.count(";") > (
            1 if sql.endswith(";") else 0
        ) or _WRITE_SQL.search(normalized):
            raise ValueError("DataHub SQL assertion must be exactly one read-only SELECT query")
        variables = {"input": {
            "entityUrn": _require(dataset_urn, "dataset URN"),
            "type": "METRIC",
            "description": _require(description, "assertion description"),
            "statement": sql,
            "operator": "GREATER_THAN_OR_EQUAL_TO",
            "parameters": {"value": {"value": str(minimum), "type": "NUMBER"}},
            "evaluationSchedule": {"timezone": timezone, "cron": cron},
            "mode": "ACTIVE",
        }}
        return self._create(
            mutation_name="upsertDatasetSqlAssertionMonitor",
            input_type="UpsertDatasetSqlAssertionMonitorInput",
            variables=variables,
            action="create_sql_metric",
            target=dataset_urn,
            evidence={
                "minimum_value": minimum,
                "schedule": cron,
                "statement_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            },
        )


def run_project_validation(
    command: str | list[str], *, cwd: str | os.PathLike[str], timeout: float = 300.0,
) -> dict[str, Any]:
    """Run a customer-supplied test command without a shell and bind its output to a receipt."""
    root = Path(cwd).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Validation working directory must be a directory")
    argv = shlex.split(command, posix=os.name != "nt") if isinstance(command, str) else list(command)
    if not argv:
        raise ValueError("Validation command is empty")
    completed = subprocess.run(
        argv, cwd=root, shell=False, capture_output=True, text=True,
        timeout=max(1.0, float(timeout)), encoding="utf-8", errors="replace",
    )
    stdout = completed.stdout[-12000:]
    stderr = completed.stderr[-12000:]
    command_sha256 = hashlib.sha256(
        json.dumps(argv, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return _receipt({
        "connector": "local_project_validation",
        "applied": True,
        "verified": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command_sha256": command_sha256,
        "working_directory_sha256": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
        "output_sha256": hashlib.sha256((stdout + "\n" + stderr).encode()).hexdigest(),
    })
