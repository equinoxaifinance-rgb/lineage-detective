from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.runtime_mode import (
    is_bundled_catalog_url,
    is_public_judge,
    is_self_hosted,
    runtime_mode,
)


class RuntimeModeTests(unittest.TestCase):
    def test_missing_mode_defaults_to_least_privileged_public_judge(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_mode(), "public_judge")
            self.assertTrue(is_public_judge())
            self.assertFalse(is_self_hosted())

    def test_sensitive_mode_requires_exact_explicit_value(self):
        with patch.dict(os.environ, {"LINEAGE_RUN_MODE": "self_hosted"}, clear=True):
            self.assertTrue(is_self_hosted())
            self.assertFalse(is_public_judge())

    def test_invalid_mode_fails_closed(self):
        for value in ("1", "hosted", "production", "SELF_HOSTED_BUSINESS"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"LINEAGE_RUN_MODE": value}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "must be"):
                    runtime_mode()

    def test_public_bundled_catalog_allows_only_exact_server_owned_loopback(self):
        environment = {
            "LINEAGE_RUN_MODE": "public_judge",
            "LINEAGE_BUNDLED_DATAHUB": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertTrue(is_bundled_catalog_url("http://127.0.0.1:8080"))
            self.assertTrue(is_bundled_catalog_url("http://localhost:8080/"))
            for blocked in (
                "http://127.0.0.1:8081",
                "https://127.0.0.1:8080",
                "http://10.0.0.4:8080",
                "http://127.0.0.1:8080/health",
                "http://user:pass@127.0.0.1:8080",
            ):
                with self.subTest(blocked=blocked):
                    self.assertFalse(is_bundled_catalog_url(blocked))

    def test_bundled_flag_does_not_relax_other_runtime_modes(self):
        with patch.dict(
            os.environ,
            {"LINEAGE_RUN_MODE": "public_judge", "LINEAGE_BUNDLED_DATAHUB": "0"},
            clear=True,
        ):
            self.assertFalse(is_bundled_catalog_url("http://127.0.0.1:8080"))
        with patch.dict(
            os.environ,
            {"LINEAGE_RUN_MODE": "self_hosted", "LINEAGE_BUNDLED_DATAHUB": "1"},
            clear=True,
        ):
            self.assertFalse(is_bundled_catalog_url("http://127.0.0.1:8080"))
