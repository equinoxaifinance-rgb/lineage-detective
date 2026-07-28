import os
import unittest
from unittest.mock import patch

from src import setup_vocab


class VocabularySetupTests(unittest.TestCase):
    def test_public_bundled_catalog_can_verify_vocabulary_without_a_browser_token(self):
        with (
            patch.dict(
                os.environ,
                {
                    "LINEAGE_RUN_MODE": "public_judge",
                    "LINEAGE_BUNDLED_DATAHUB": "1",
                },
                clear=True,
            ),
            patch.object(setup_vocab.os.path, "exists", return_value=False),
            patch.object(
                setup_vocab,
                "_ensure_via_graphql",
                return_value=["QUARANTINE_INCIDENT", "IMPACTED_BY_INCIDENT"],
            ) as graphql,
        ):
            names = setup_vocab.ensure_incident_vocabulary(
                "http://127.0.0.1:8080"
            )
        self.assertEqual(
            names,
            ["QUARANTINE_INCIDENT", "IMPACTED_BY_INCIDENT"],
        )
        graphql.assert_called_once_with("http://127.0.0.1:8080", None)

    def test_graphql_fallback_reads_existing_tags_without_mutating(self):
        calls = []

        def fake_graphql(server, token, query, variables):
            calls.append((server, token, query, variables))
            return {"data": {"tag": {"urn": variables["urn"]}}}

        with patch.object(setup_vocab, "_graphql", side_effect=fake_graphql):
            names = setup_vocab._ensure_via_graphql("https://tenant.acryl.io", "secret")

        self.assertEqual(names, [name for name, _ in setup_vocab.INCIDENT_VOCABULARY])
        self.assertEqual(len(calls), 4)
        self.assertFalse(any("CreateTag" in call[2] for call in calls))

    def test_graphql_fallback_creates_missing_tags_and_requires_readback(self):
        seen = {}

        def fake_graphql(_server, _token, query, variables):
            if "CreateTag" in query:
                urn = f"urn:li:tag:{variables['input']['id']}"
                seen[urn] = True
                return {"data": {"createTag": urn}}
            urn = variables["urn"]
            return {"data": {"tag": {"urn": urn} if seen.get(urn) else None}}

        with patch.object(setup_vocab, "_graphql", side_effect=fake_graphql):
            names = setup_vocab._ensure_via_graphql("https://tenant.acryl.io", "secret")

        self.assertEqual(names, [name for name, _ in setup_vocab.INCIDENT_VOCABULARY])
        self.assertEqual(len(seen), 2)

    def test_graphql_fallback_never_claims_success_without_readback(self):
        def fake_graphql(_server, _token, query, variables):
            if "CreateTag" in query:
                return {"data": {"createTag": f"urn:li:tag:{variables['input']['id']}"}}
            return {"data": {"tag": None}}

        with patch.object(setup_vocab, "_graphql", side_effect=fake_graphql):
            with self.assertRaisesRegex(RuntimeError, "did not read back"):
                setup_vocab._ensure_via_graphql("https://tenant.acryl.io", "secret")


if __name__ == "__main__":
    unittest.main()
