from __future__ import annotations

import os
import unittest
from unittest import mock

from src.network_policy import validate_network_url


def answer(address: str, port: int = 443):
    return [(2, 1, 6, "", (address, port))]


class NetworkPolicyTests(unittest.TestCase):
    def test_hosted_mode_accepts_public_https(self):
        with mock.patch("src.network_policy.socket.getaddrinfo", return_value=answer("93.184.216.34")):
            self.assertEqual(
                validate_network_url(
                    "https://example.com/api#ignored",
                    allow_private=False,
                    label="test",
                ),
                "https://example.com/api",
            )

    def test_hosted_mode_rejects_private_dns_answers(self):
        blocked = ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1")
        for address in blocked:
            with self.subTest(address=address), mock.patch(
                "src.network_policy.socket.getaddrinfo",
                return_value=answer(address),
            ):
                with self.assertRaisesRegex(ValueError, "private or local"):
                    validate_network_url(
                        "https://attacker.example/api",
                        allow_private=False,
                        label="test",
                    )

    def test_hosted_mode_rejects_http_nonstandard_ports_and_userinfo(self):
        with mock.patch(
            "src.network_policy.socket.getaddrinfo",
            return_value=answer("93.184.216.34"),
        ):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                validate_network_url("http://example.com", allow_private=False)
            with self.assertRaisesRegex(ValueError, "standard HTTPS port"):
                validate_network_url("https://example.com:8443", allow_private=False)
            with self.assertRaisesRegex(ValueError, "embedded credentials"):
                validate_network_url("https://token@example.com", allow_private=False)

    def test_local_mode_keeps_quickstart_available(self):
        with mock.patch(
            "src.network_policy.socket.getaddrinfo",
            return_value=answer("127.0.0.1", 8080),
        ):
            self.assertEqual(
                validate_network_url(
                    "http://localhost:8080",
                    allow_private=True,
                    label="DataHub",
                ),
                "http://localhost:8080",
            )

    def test_datahub_client_applies_hosted_policy_to_both_endpoints(self):
        from src.datahub_mcp import MCPDataHub

        with mock.patch.dict(os.environ, {"HOSTED_MODE": "1"}, clear=False), mock.patch(
            "src.network_policy.socket.getaddrinfo",
            return_value=answer("127.0.0.1"),
        ):
            with self.assertRaisesRegex(ValueError, "private or local"):
                MCPDataHub(
                    gms_url="https://catalog.example",
                    mcp_url="https://mcp.example/mcp",
                )

    def test_public_container_can_reach_only_its_explicit_bundled_gms(self):
        from src.datahub_mcp import MCPDataHub

        with mock.patch.dict(
            os.environ,
            {
                "LINEAGE_RUN_MODE": "public_judge",
                "LINEAGE_BUNDLED_DATAHUB": "1",
                "DATAHUB_MCP_URL": "",
            },
            clear=True,
        ):
            client = MCPDataHub(gms_url="http://127.0.0.1:8080")
            self.assertTrue(client.allow_private_network)
            self.assertEqual(client.gms_url, "http://127.0.0.1:8080")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                MCPDataHub(gms_url="http://10.0.0.4:8080")


if __name__ == "__main__":
    unittest.main()
