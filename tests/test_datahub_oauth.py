import asyncio
import unittest

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from src.datahub_oauth import DATAHUB_GLOBAL_MCP, MemoryTokenStorage


class DataHubOAuthTests(unittest.TestCase):
    def test_memory_storage_retains_tokens_without_a_file_surface(self):
        storage = MemoryTokenStorage()
        token = OAuthToken(access_token="secret-access-token")
        asyncio.run(storage.set_tokens(token))
        self.assertIs(asyncio.run(storage.get_tokens()), token)
        self.assertFalse(hasattr(storage, "path"))

    def test_memory_storage_retains_dynamic_client_registration(self):
        storage = MemoryTokenStorage()
        client = OAuthClientInformationFull(
            client_id="lineage-detective-test",
            redirect_uris=["http://127.0.0.1:9999/callback"],
        )
        asyncio.run(storage.set_client_info(client))
        self.assertIs(asyncio.run(storage.get_client_info()), client)

    def test_official_global_mcp_endpoint_is_used(self):
        self.assertEqual(DATAHUB_GLOBAL_MCP, "https://mcp.datahub.com/mcp")


if __name__ == "__main__":
    unittest.main()
