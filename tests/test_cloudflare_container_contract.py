from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = (ROOT / "cloudflare-container" / "src" / "index.js").read_text(
    encoding="utf-8"
)
WRANGLER = json.loads(
    (ROOT / "cloudflare-container" / "wrangler.jsonc").read_text(encoding="utf-8")
)
FULLSTACK_DOCKERFILE = (
    ROOT / "cloudflare-fullstack" / "Dockerfile"
).read_text(encoding="utf-8")


class CloudflareContainerContractTests(unittest.TestCase):
    def test_judge_runtime_is_named_bounded_and_large_enough_for_datahub(self):
        container = WRANGLER["containers"][0]
        self.assertEqual(container["max_instances"], 2)
        self.assertEqual(container["instance_type"], "standard-4")
        self.assertEqual(container["rollout_step_percentage"], 100)
        self.assertIn('getByName("judge")', WORKER)

    def test_bundled_catalog_boundary_is_enabled_only_server_side(self):
        self.assertIn('LINEAGE_BUNDLED_DATAHUB: "1"', WORKER)
        self.assertIn('DATAHUB_SERVER: "http://127.0.0.1:8080"', WORKER)
        self.assertIn(
            'DATAHUB_MCP_EXECUTABLE: "/opt/datahub-sidecar/bin/mcp-server-datahub"',
            WORKER,
        )

    def test_fullstack_image_declares_its_own_bundled_catalog_boundary(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'export LINEAGE_BUNDLED_DATAHUB="${LINEAGE_BUNDLED_DATAHUB:-1}"',
            start_script,
        )

    def test_catalog_verification_retries_without_restarting_datahub(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        verifier = (
            ROOT / "tools" / "verify_judge_catalog.py"
        ).read_text(encoding="utf-8")
        mcp_client = (
            ROOT / "src" / "datahub_mcp.py"
        ).read_text(encoding="utf-8")
        self.assertIn("JUDGE_CATALOG_ATTEMPT=1", start_script)
        self.assertIn(
            'while [ "$JUDGE_CATALOG_ATTEMPT" -le 6 ]',
            start_script,
        )
        self.assertIn("Rechecking the official MCP path", start_script)
        self.assertIn("emit_private_diagnostic", start_script)
        self.assertIn("LINEAGE_MCP_DEBUG=0", start_script)
        self.assertIn("LINEAGE_CATALOG_FAILURE_RECEIPT=", verifier)
        self.assertIn("export DATAHUB_TELEMETRY_ENABLED=false", start_script)
        self.assertIn('args = [*args, "--debug"]', mcp_client)
        self.assertIn(
            'fatal_bootstrap 1 "official MCP catalog verification"',
            start_script,
        )
        self.assertIn('if [ "$VERIFY_EXIT" -ne 75 ]', start_script)
        self.assertIn(
            'os.environ.get("LINEAGE_RELEASE_MCP_STARTUP_TIMEOUT", "180")',
            verifier,
        )
        self.assertIn("raise SystemExit(75)", verifier)
        self.assertIn(
            "return 75 if eventual_state_pending and not missing_tools else 1",
            verifier,
        )

    def test_customer_360_release_path_is_six_real_lineage_edges(self):
        seed = (ROOT / "seed_demo.py").read_text(encoding="utf-8")
        verifier = (
            ROOT / "tools" / "verify_judge_catalog.py"
        ).read_text(encoding="utf-8")
        expected_nodes = (
            "prod.crm_exports.customers_v2",
            "prod.landing.crm_customers",
            "analytics.bronze.crm_customers",
            "prod.raw.customers",
            "analytics.staging.stg_customers",
            "analytics.marts.dim_customers",
            "bi.customer_360",
        )
        for node in expected_nodes:
            self.assertIn(node, seed)
            self.assertIn(node, verifier)
        self.assertIn(
            "chain(b_source, b_landing, b_bronze, b_raw, b_stg, b_dim, b_dash)",
            seed,
        )
        self.assertIn("max_hops=6", verifier)
        self.assertIn('"longest_chain_edges"', verifier)

    def test_judge_runtime_stays_warm_for_a_workday_then_scales_to_zero(self):
        self.assertIn('sleepAfter = "8h"', WORKER)
        self.assertEqual(WRANGLER["triggers"]["crons"], ["0 * * * *"])
        self.assertIn("async scheduled(controller, env)", WORKER)
        self.assertIn(
            'Date.parse("2026-09-16T00:00:00Z")',
            WORKER,
        )
        self.assertIn(
            'new Request("http://lineage-detective.internal/_stcore/health"',
            WORKER,
        )
        self.assertIn('body.trim() !== "ok"', WORKER)

    def test_worker_adds_browser_security_headers(self):
        for header in (
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Permissions-Policy",
            "Content-Security-Policy",
        ):
            self.assertIn(header, WORKER)

    def test_worker_and_container_logs_are_retained_for_release_diagnostics(self):
        observability = WRANGLER["observability"]
        self.assertTrue(observability["enabled"])
        self.assertEqual(observability["head_sampling_rate"], 1)

    def test_packaged_runtime_has_every_rootless_docker_prerequisite(self):
        for package in (
            "fuse-overlayfs",
            "uidmap",
        ):
            self.assertIn(package, FULLSTACK_DOCKERFILE)
        self.assertIn(
            "docker:29.6.2-dind-rootless@sha256:"
            "9ca5d2d7f364f7c48579ba57dcb218b37387f214943f6446f62a200935511278",
            FULLSTACK_DOCKERFILE,
        )
        for binary in (
            "containerd",
            "docker",
            "dockerd",
            "rootlesskit",
            "runc",
        ):
            self.assertIn(
                f"/usr/local/bin/{binary} /usr/local/bin/{binary}",
                FULLSTACK_DOCKERFILE,
            )
        self.assertNotIn("docker.io", FULLSTACK_DOCKERFILE)
        self.assertNotIn("docker-cli", FULLSTACK_DOCKERFILE)

    def test_entrypoint_prepares_dbt_semaphores_then_permanently_drops_privilege(self):
        entrypoint_path = ROOT / "cloudflare-fullstack" / "entrypoint.sh"
        start_path = ROOT / "cloudflare-fullstack" / "start.sh"
        entrypoint = entrypoint_path.read_text(encoding="utf-8")
        start_script = start_path.read_text(encoding="utf-8")
        self.assertNotIn(b"\r", entrypoint_path.read_bytes())
        self.assertNotIn(b"\r", start_path.read_bytes())
        self.assertIn("carriage returns in shell scripts", FULLSTACK_DOCKERFILE)
        self.assertIn("mkdir -p /dev/shm", entrypoint)
        self.assertIn("chmod 1777 /dev/shm", entrypoint)
        self.assertIn(
            "setpriv --reuid=lineage --regid=lineage --init-groups", entrypoint
        )
        self.assertNotIn("runuser", entrypoint)
        self.assertIn("USER root", FULLSTACK_DOCKERFILE)
        self.assertIn(
            'ENTRYPOINT ["/app/cloudflare-fullstack/entrypoint.sh"]',
            FULLSTACK_DOCKERFILE,
        )
        self.assertIn('multiprocessing.get_context("spawn").RLock()', start_script)
        self.assertIn('"dbt semaphore preflight"', start_script)
    def test_rootless_namespace_uses_platform_required_host_networking(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--net=host", start_script)
        self.assertNotIn("--net=slirp4netns", start_script)
        self.assertIn("--bridge=none", start_script)
        self.assertIn("--ip-forward=false", start_script)
        self.assertIn("--ip-masq=false", start_script)
        self.assertIn('DOCKER_STORAGE_DRIVER="overlay2"', start_script)
        self.assertIn('--storage-driver="$DOCKER_STORAGE_DRIVER"', start_script)
        self.assertIn("DOCKER_API_VERSION=1.54", FULLSTACK_DOCKERFILE)
        self.assertIn('GET /_ping HTTP/1.0', start_script)
        probe = re.search(r'sock\.sendall\((b"[^"]+")\)', start_script)
        self.assertIsNotNone(probe)
        self.assertEqual(
            ast.literal_eval(probe.group(1)),
            b"GET /_ping HTTP/1.0\r\n\r\n",
        )
        self.assertNotIn("until docker version", start_script)
        self.assertNotIn("-p 0.0.0.0:8080:8080/tcp", start_script)

    def test_bundled_datahub_services_use_latest_stable_v1_6_release(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "acryldata/datahub-gms:v1.6.0@sha256:"
            "672bceed7f36f751ab3302c30826c6ba124d1c0fd8d24c3724e725078b864018",
            start_script,
        )
        self.assertIn(
            '"Fetching six digest-pinned runtime images in parallel."',
            start_script,
        )
        self.assertIn("pull_image datahub-gms", start_script)
        self.assertIn("pull_image bridge", start_script)
        self.assertIn('while [ "$completed" -lt 6 ]', start_script)
        self.assertIn(
            "acryldata/datahub-upgrade:v1.6.0@sha256:"
            "6e6b9f09165007004c20e9387e6ca1a171d1425fd76ae807b217c5dc7883ff02",
            start_script,
        )

    def test_services_share_an_isolated_namespace_through_a_unix_bridge(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--name lineage-net --network none", start_script)
        self.assertIn("--network container:lineage-net", start_script)
        self.assertEqual(start_script.count("--network container:lineage-net"), 5)
        self.assertIn("cloudflare-fullstack/net_bridge.py", start_script)
        self.assertIn("/app/state/datahub-gms.sock", start_script)
        self.assertIn('"DataHub namespace bridge start"', start_script)
        self.assertIn('"DataHub namespace bridge socket"', start_script)
        self.assertNotIn(
            "docker run -d --name lineage-mysql --network host", start_script
        )
        self.assertNotIn(
            "docker run -d --name lineage-gms --network host", start_script
        )
        self.assertIn(
            "python:3.11-slim@sha256:"
            "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93",
            start_script,
        )
    def test_process_restart_clears_only_proven_stale_rootless_markers(self):
        start_script = (
            ROOT / "cloudflare-fullstack" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("if ! pgrep -x dockerd >/dev/null 2>&1; then", start_script)
        self.assertIn(
            'rm -f "$XDG_RUNTIME_DIR/docker.pid" "$XDG_RUNTIME_DIR/docker.sock"',
            start_script,
        )


if __name__ == "__main__":
    unittest.main()
