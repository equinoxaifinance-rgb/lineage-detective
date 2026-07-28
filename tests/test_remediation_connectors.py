from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.remediation_connectors import (
    AirflowConnector,
    DataHubAssertionConnector,
    DbtCloudConnector,
    FivetranConnector,
    GitHubPullRequestConnector,
    JsonTransport,
    SnowflakeSqlConnector,
    failure_receipt,
    run_project_validation,
)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.calls.append({
            "method": method, "url": url, "headers": headers or {},
            "body": body, "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class UniversalRemediationConnectorTests(unittest.TestCase):
    def test_hosted_transport_rejects_local_ssrf_targets(self):
        transport = JsonTransport()
        for url in ("http://127.0.0.1:8080/api", "https://127.0.0.1/api"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "HTTPS|private"):
                    transport._validate_url(url)

    def test_explicit_local_transport_allows_local_development(self):
        JsonTransport(allow_private=True)._validate_url("http://127.0.0.1:8080/api")

    def test_credential_bearing_transport_refuses_redirects(self):
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/should-not-follow")
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "unexpected redirect"):
                JsonTransport(allow_private=True).request(
                    "GET", f"http://127.0.0.1:{server.server_port}/redirect"
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_github_opens_and_reads_back_a_pull_request_for_exact_approved_bytes(self):
        original = "select 0\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": "\n".join(
                    [
                        __import__("base64").b64encode(original.encode()).decode()[:4],
                        __import__("base64").b64encode(original.encode()).decode()[4:],
                    ]
                ),
            }),
            (201, {"ref": "refs/heads/lineage-detective/fix-1"}),
            (200, {"commit": {"sha": "commit123"}}),
            (200, {
                "encoding": "base64",
                "content": __import__("base64").b64encode(b"select 1\n").decode(),
            }),
            (201, {"number": 7, "html_url": "https://github.test/pull/7"}),
            (200, {"state": "open", "head": {"sha": "commit123"}}),
        )
        content = "select 1\n"
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="models/example.sql", content=content, base_branch="main",
            branch="lineage-detective/fix-1", title="Repair model", body="Verified receipt",
            expected_before_sha256=hashlib.sha256(original.encode()).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        self.assertTrue(receipt["applied"])
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["pull_number"], 7)
        self.assertNotIn("secret", str(receipt))
        self.assertEqual(transport.calls[5]["method"], "POST")

    def test_github_validates_target_before_creating_a_branch(self):
        class MissingTargetTransport(FakeTransport):
            def request(self, method, url, **kwargs):
                self.calls.append({
                    "method": method, "url": url, "headers": kwargs.get("headers") or {},
                    "body": kwargs.get("body"), "timeout": kwargs.get("timeout", 30.0),
                })
                if len(self.calls) == 1:
                    return 200, {"object": {"sha": "base123"}}
                raise RuntimeError("target path was not found")

        transport = MissingTargetTransport()
        content = "select 1\n"
        with self.assertRaisesRegex(RuntimeError, "not found"):
            GitHubPullRequestConnector(
                "secret", "owner/repo", transport=transport, api_base="https://github.test"
            ).apply(
                path="missing.sql", content=content, base_branch="main", branch="fix",
                title="Repair model", body="Verified receipt",
                expected_before_sha256="0" * 64,
                expected_proposal_sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "GET"])

    def test_github_rejects_content_that_is_not_the_approved_repair(self):
        with self.assertRaisesRegex(ValueError, "hash"):
            GitHubPullRequestConnector("secret", "owner/repo", transport=FakeTransport()).apply(
                path="model.sql", content="select 2", base_branch="main", branch="fix",
                title="x", body="x", expected_before_sha256="0" * 64,
                expected_proposal_sha256="0" * 64,
            )

    def test_github_refuses_remote_source_drift_before_creating_branch(self):
        original = "select 0\n"
        remote_newer = "select 999\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(remote_newer.encode()).decode(),
            }),
        )
        with self.assertRaisesRegex(RuntimeError, "changed after review"):
            GitHubPullRequestConnector(
                "secret", "owner/repo", transport=transport, api_base="https://github.test"
            ).apply(
                path="models/example.sql",
                content="select 1\n",
                base_branch="main",
                branch="fix",
                title="Repair",
                body="Verified",
                expected_before_sha256=hashlib.sha256(original.encode()).hexdigest(),
                expected_proposal_sha256=hashlib.sha256(b"select 1\n").hexdigest(),
            )
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "GET"])

    def test_github_requires_commit_sha_before_claiming_remote_apply(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            (201, {"ref": "refs/heads/fix"}),
            (200, {"commit": {}}),
        )
        transport.responses.extend([
            (204, {}),
            RuntimeError("GET branch returned HTTP 404: not found"),
        ])
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql",
            content=proposal,
            base_branch="main",
            branch="fix",
            title="Repair",
            body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertFalse(receipt["applied"])
        self.assertTrue(receipt["cleanup_verified"])

    def test_github_requires_committed_byte_readback_before_opening_pr(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            (201, {"ref": "refs/heads/fix"}),
            (200, {"commit": {"sha": "commit123"}}),
            (200, {
                "encoding": "base64",
                "content": __import__("base64").b64encode(b"select 999\n").decode(),
            }),
        )
        transport.responses.extend([
            (204, {}),
            RuntimeError("GET branch returned HTTP 404: not found"),
        ])
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql",
            content=proposal,
            base_branch="main",
            branch="fix",
            title="Repair",
            body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertFalse(receipt["applied"])
        self.assertTrue(receipt["cleanup_verified"])
        self.assertEqual([call["method"] for call in transport.calls], [
            "GET", "GET", "POST", "PUT", "GET", "DELETE", "GET",
        ])

    def test_github_ambiguous_pr_create_does_not_delete_the_branch_or_claim_failure(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            (201, {"ref": "refs/heads/fix"}),
            (200, {"commit": {"sha": "commit123"}}),
            (200, {
                "encoding": "base64",
                "content": __import__("base64").b64encode(proposal.encode()).decode(),
            }),
            RuntimeError("pull request creation failed"),
            (200, []),
        )
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql", content=proposal, base_branch="main", branch="fix",
            title="Repair", body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertIsNone(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "outcome_unknown")
        self.assertNotIn("cleanup_verified", receipt)
        self.assertNotIn("DELETE", [call["method"] for call in transport.calls])

    def test_github_recovers_a_lost_pr_response_by_exact_head_lookup(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            (201, {"ref": "refs/heads/fix"}),
            (200, {"commit": {"sha": "commit123"}}),
            (200, {
                "encoding": "base64",
                "content": __import__("base64").b64encode(proposal.encode()).decode(),
            }),
            TimeoutError("response lost after create"),
            (200, [{
                "number": 7,
                "html_url": "https://github.test/pull/7",
                "state": "open",
                "head": {"ref": "fix", "sha": "commit123"},
            }]),
        )
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql", content=proposal, base_branch="main", branch="fix",
            title="Repair", body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertTrue(receipt["applied"])
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "recovered_by_head_lookup")
        self.assertEqual(receipt["pull_number"], 7)

    def test_github_branch_create_response_loss_is_not_mislabeled_not_applied(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            TimeoutError("response lost after branch create"),
        )
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql", content=proposal, base_branch="main", branch="fix",
            title="Repair", body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertIsNone(receipt["applied"])
        self.assertEqual(receipt["verification_state"], "outcome_unknown")
        self.assertEqual(receipt["external_id"], "fix")

    def test_github_cleanup_failure_preserves_partial_remote_state(self):
        original = b"select 0\n"
        proposal = "select 1\n"
        transport = FakeTransport(
            (200, {"object": {"sha": "base123"}}),
            (200, {
                "sha": "blob123",
                "encoding": "base64",
                "content": __import__("base64").b64encode(original).decode(),
            }),
            (201, {"ref": "refs/heads/fix"}),
            RuntimeError("commit failed"),
            RuntimeError("delete failed"),
        )
        receipt = GitHubPullRequestConnector(
            "secret", "owner/repo", transport=transport, api_base="https://github.test"
        ).apply(
            path="model.sql", content=proposal, base_branch="main", branch="fix",
            title="Repair", body="Verified",
            expected_before_sha256=hashlib.sha256(original).hexdigest(),
            expected_proposal_sha256=hashlib.sha256(proposal.encode()).hexdigest(),
        )
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "partial_remote_state")
        self.assertEqual(receipt["branch"], "fix")

    def test_dbt_cloud_triggers_and_reads_back_run_state(self):
        transport = FakeTransport(
            (201, {"data": {"id": 42}}),
            (200, {"data": {"status_humanized": "Queued"}}),
        )
        receipt = DbtCloudConnector(
            "secret", "1", "2", transport=transport, api_base="https://dbt.test"
        ).trigger(cause="Lineage Detective verified repair", steps_override=["dbt test"])
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["run_id"], 42)
        self.assertNotIn("secret", str(receipt))

    def test_dbt_cloud_preserves_run_id_when_readback_fails(self):
        transport = FakeTransport(
            (201, {"data": {"id": 42}}),
            RuntimeError("secret upstream readback failure"),
        )
        receipt = DbtCloudConnector(
            "secret", "1", "2", transport=transport, api_base="https://dbt.test"
        ).trigger(cause="Verified repair")
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["run_id"], 42)
        self.assertNotIn("secret upstream", str(receipt))

    def test_airflow_trigger_uses_unique_run_and_reads_state(self):
        transport = FakeTransport()
        connector = AirflowConnector("https://airflow.test", "secret", transport=transport)
        transport.responses = [
            (200, {"dag_run_id": "placeholder"}),
            (200, {"state": "queued"}),
        ]
        # Echo the generated run id from the request to model the real API.
        original = transport.request

        def request(method, url, **kwargs):
            if len(transport.calls) == 0:
                transport.responses[0] = (200, {"dag_run_id": kwargs["body"]["dag_run_id"]})
            return original(method, url, **kwargs)

        transport.request = request
        receipt = connector.trigger(dag_id="repair_customers", conf={"receipt": "abc"})
        self.assertTrue(receipt["applied"])
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["state"], "queued")

    def test_airflow_preserves_run_id_when_readback_fails(self):
        class AirflowPartialTransport(FakeTransport):
            def request(self, method, url, **kwargs):
                if method == "POST":
                    run_id = kwargs["body"]["dag_run_id"]
                    self.calls.append({"method": method, "url": url, **kwargs})
                    return 200, {"dag_run_id": run_id}
                self.calls.append({"method": method, "url": url, **kwargs})
                raise RuntimeError("readback secret")

        receipt = AirflowConnector(
            "https://airflow.test", "secret", transport=AirflowPartialTransport()
        ).trigger(dag_id="repair_customers", conf={})
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertTrue(receipt["run_id"].startswith("lineage-detective-"))
        self.assertNotIn("readback secret", str(receipt))

    def test_fivetran_pause_requires_readback_of_paused_state(self):
        transport = FakeTransport(
            (200, {"data": {"succeeded": True}}),
            (200, {"data": {"status": {"sync_state": "paused"}}}),
        )
        receipt = FivetranConnector(
            "key", "secret", "connection", transport=transport, api_base="https://fivetran.test"
        ).act("pause")
        self.assertTrue(receipt["verified"])
        self.assertNotIn("secret", str(receipt))

    def test_fivetran_preserves_action_when_readback_fails(self):
        transport = FakeTransport(
            (200, {"data": {"succeeded": True}}),
            RuntimeError("secret readback failure"),
        )
        receipt = FivetranConnector(
            "key", "secret", "connection", transport=transport,
            api_base="https://fivetran.test",
        ).act("pause")
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["action"], "pause")
        self.assertNotIn("secret readback", str(receipt))

    def test_snowflake_uses_idempotency_id_and_binds_receipt_to_sql(self):
        transport = FakeTransport(
            (200, {
                "code": "090001",
                "sqlState": "00000",
                "statementHandle": "handle-1",
            }),
        )
        receipt = SnowflakeSqlConnector(
            "https://acct.snowflake.test", "secret", transport=transport
        ).execute(statement="alter table X swap with X_REPAIRED", warehouse="REPAIR_WH")
        self.assertTrue(receipt["verified"])
        self.assertIn("requestId=", transport.calls[0]["url"])
        self.assertNotIn("secret", str(receipt))

    def test_snowflake_does_not_false_green_terminal_sql_failure(self):
        transport = FakeTransport(
            (200, {
                "code": "390100",
                "sqlState": "42000",
                "statementHandle": "handle-failed",
            }),
        )
        receipt = SnowflakeSqlConnector(
            "https://acct.snowflake.test", "secret", transport=transport
        ).execute(statement="alter table X swap with X_REPAIRED")
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "terminal_failure")

    def test_snowflake_preserves_running_handle_after_bounded_polling(self):
        running = (202, {"statementHandle": "handle-running"})
        transport = FakeTransport(*([running] * 7))
        receipt = SnowflakeSqlConnector(
            "https://acct.snowflake.test", "secret", transport=transport
        ).execute(statement="alter table X swap with X_REPAIRED")
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "still_running")
        self.assertEqual(receipt["statement_handle"], "handle-running")

    def test_snowflake_rejects_multiple_statements(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            SnowflakeSqlConnector(
                "https://acct.snowflake.test", "secret", transport=FakeTransport()
            ).execute(statement="delete from x; drop table x")

    def test_datahub_freshness_assertion_uses_official_graphql_mutation(self):
        transport = FakeTransport(
            (200, {"data": {
                "upsertDatasetFreshnessAssertionMonitor": {
                    "urn": "urn:li:assertion:123",
                }
            }}),
            (200, {"data": {
                "assertion": {"urn": "urn:li:assertion:123"},
            }}),
        )
        receipt = DataHubAssertionConnector(
            "https://datahub.test", "secret", transport=transport
        ).create_freshness(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.t,PROD)",
            hours=8,
        )
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "verified_readback")
        self.assertEqual(receipt["assertion_urn"], "urn:li:assertion:123")
        self.assertIn("upsertDatasetFreshnessAssertionMonitor", transport.calls[0]["body"]["query"])
        self.assertNotIn("secret", str(receipt))

    def test_datahub_volume_assertion_binds_a_real_row_count_range(self):
        transport = FakeTransport(
            (200, {"data": {
                "upsertDatasetVolumeAssertionMonitor": {"urn": "urn:li:assertion:volume"}
            }}),
            (200, {"data": {
                "assertion": {"urn": "urn:li:assertion:volume"},
            }}),
        )
        receipt = DataHubAssertionConnector(
            "https://datahub.test", "secret", transport=transport
        ).create_volume(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.t,PROD)",
            minimum=10, maximum=200,
        )
        self.assertTrue(receipt["verified"])
        payload = transport.calls[0]["body"]["variables"]["input"]
        self.assertEqual(payload["rowCountTotal"]["parameters"]["minValue"]["value"], "10")
        self.assertEqual(payload["rowCountTotal"]["parameters"]["maxValue"]["value"], "200")

    def test_datahub_sql_assertion_accepts_one_read_only_metric_query(self):
        transport = FakeTransport(
            (200, {"data": {
                "upsertDatasetSqlAssertionMonitor": {"urn": "urn:li:assertion:sql"}
            }}),
            (200, {"data": {
                "assertion": {"urn": "urn:li:assertion:sql"},
            }}),
        )
        receipt = DataHubAssertionConnector(
            "https://datahub.test", "secret", transport=transport
        ).create_sql_metric(
            dataset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.t,PROD)",
            statement="SELECT COUNT(*) FROM db.schema.t",
            minimum=1,
            description="Table must contain a row",
        )
        self.assertTrue(receipt["verified"])
        self.assertEqual(len(receipt["statement_sha256"]), 64)
        self.assertNotIn("SELECT COUNT", str(receipt))

    def test_datahub_assertion_preserves_urn_when_readback_is_unavailable(self):
        transport = FakeTransport(
            (200, {"data": {
                "upsertDatasetFreshnessAssertionMonitor": {
                    "urn": "urn:li:assertion:readback",
                }
            }}),
            TimeoutError("readback lost"),
        )
        receipt = DataHubAssertionConnector(
            "https://datahub.test", "secret", transport=transport
        ).create_freshness(dataset_urn="urn:li:dataset:test", hours=24)
        self.assertTrue(receipt["applied"])
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["verification_state"], "readback_unavailable")
        self.assertEqual(receipt["external_id"], "urn:li:assertion:readback")

    def test_datahub_sql_assertion_rejects_write_capable_or_multiple_sql(self):
        connector = DataHubAssertionConnector(
            "https://datahub.test", "secret", transport=FakeTransport()
        )
        for statement in (
            "DELETE FROM t",
            "SELECT 1; DROP TABLE t",
            "WITH removed AS (DELETE FROM t RETURNING *) SELECT * FROM removed",
        ):
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(ValueError, "read-only"):
                    connector.create_sql_metric(
                        dataset_urn="urn:li:dataset:test", statement=statement,
                        minimum=0, description="test",
                    )

    def test_initial_mutation_response_loss_is_outcome_unknown_across_connectors(self):
        cases = [
            (
                "dbt",
                lambda: DbtCloudConnector(
                    "secret", "1", "2",
                    transport=FakeTransport(TimeoutError("lost")),
                    api_base="https://dbt.test",
                ).trigger(cause="Verified repair"),
            ),
            (
                "airflow",
                lambda: AirflowConnector(
                    "https://airflow.test", "secret",
                    transport=FakeTransport(TimeoutError("lost")),
                ).trigger(dag_id="repair", conf={"approved": True}),
            ),
            (
                "fivetran",
                lambda: FivetranConnector(
                    "key", "secret", "connection",
                    transport=FakeTransport(TimeoutError("lost")),
                    api_base="https://fivetran.test",
                ).act("sync"),
            ),
            (
                "snowflake",
                lambda: SnowflakeSqlConnector(
                    "https://snowflake.test", "secret",
                    transport=FakeTransport(TimeoutError("lost")),
                ).execute(statement="select 1"),
            ),
            (
                "datahub",
                lambda: DataHubAssertionConnector(
                    "https://datahub.test", "secret",
                    transport=FakeTransport(TimeoutError("lost")),
                ).create_freshness(dataset_urn="urn:li:dataset:test", hours=24),
            ),
        ]
        for name, invoke in cases:
            with self.subTest(connector=name):
                receipt = invoke()
                self.assertIsNone(receipt["applied"])
                self.assertFalse(receipt["verified"])
                self.assertEqual(receipt["verification_state"], "outcome_unknown")
                self.assertIn("Do not retry blindly", receipt["recovery"])
                self.assertNotIn("secret", str(receipt))

    def test_customer_validation_command_is_shell_free_and_receipted(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = run_project_validation(
                [sys.executable, "-c", "print('PROJECT_TEST_OK')"], cwd=directory,
            )
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["exit_code"], 0)
        self.assertNotIn("PROJECT_TEST_OK", str(receipt))
        self.assertEqual(len(receipt["command_sha256"]), 64)
        self.assertEqual(len(receipt["output_sha256"]), 64)
        self.assertEqual(len(receipt["receipt_sha256"]), 64)

    def test_customer_validation_failure_stays_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = run_project_validation(
                [sys.executable, "-c", "raise SystemExit(9)"], cwd=directory,
            )
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["exit_code"], 9)

    def test_connector_failure_is_hash_bound_and_secret_free(self):
        receipt = failure_receipt("github", ValueError("path was invalid"))
        self.assertFalse(receipt["verified"])
        self.assertEqual(receipt["error_type"], "ValueError")
        self.assertNotIn("path was invalid", str(receipt))
        self.assertEqual(len(receipt["receipt_sha256"]), 64)

    def test_validation_receipt_never_contains_command_or_output_secrets(self):
        marker = "LOCAL_DEPLOY_SECRET_VALUE"
        with tempfile.TemporaryDirectory() as directory:
            receipt = run_project_validation(
                [
                    sys.executable,
                    "-c",
                    "import sys; print(sys.argv[1]); print(sys.argv[1], file=sys.stderr)",
                    marker,
                ],
                cwd=directory,
            )
        serialized = str(receipt)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("-c", serialized)
        self.assertEqual(len(receipt["command_sha256"]), 64)
        self.assertEqual(len(receipt["output_sha256"]), 64)

    def test_failure_receipt_never_copies_upstream_secret_echo(self):
        marker = "Bearer SECRET-FROM-UPSTREAM"
        receipt = failure_receipt("github", RuntimeError(marker))
        self.assertNotIn(marker, str(receipt))


if __name__ == "__main__":
    unittest.main()
