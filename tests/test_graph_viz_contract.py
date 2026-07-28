"""Truth-boundary checks for the lineage visual labels."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graph_viz import lineage_dot  # noqa: E402


ROOT_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.root,PROD)"
AFFECTED_URN = "urn:li:dataset:(urn:li:dataPlatform:looker,bi.dashboard,PROD)"
DOWNSTREAM_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.downstream,PROD)"


class FakeMcp:
    def get_lineage(self, urn, *, upstream, max_hops, max_results):
        if upstream and urn == AFFECTED_URN:
            return [{"urn": ROOT_URN}]
        if not upstream and urn == ROOT_URN:
            return [{"urn": DOWNSTREAM_URN}]
        return []


class GraphVizTruthTests(unittest.TestCase):
    def test_read_only_diagnosis_never_claims_quarantine(self):
        dot = lineage_dot(FakeMcp(), AFFECTED_URN, {"suspects": [{"urn": ROOT_URN}]})
        self.assertIn("TOP SUSPECT", dot)
        self.assertIn("DOWNSTREAM IMPACT", dot)
        self.assertIn("warehouse.root\\n(dbt)", dot)
        self.assertNotIn("warehouse.root\\\\n(dbt)", dot)
        self.assertNotIn("QUARANTINE", dot)

    def test_confirmed_write_is_the_only_case_labeled_quarantine(self):
        dot = lineage_dot(FakeMcp(), AFFECTED_URN, {
            "suspects": [{"urn": ROOT_URN}], "action": {"urn": ROOT_URN, "applied": True},
        })
        self.assertIn("QUARANTINE", dot)
        self.assertIn("IMPACTED", dot)

    def test_hostile_catalog_values_cannot_inject_dot_statements(self):
        hostile = (
            'urn:li:dataset:(urn:li:dataPlatform:dbt,'
            'bad"; injected [label="OWNED"];//\\x\nnext,PROD)'
        )

        class HostileMcp:
            def get_lineage(self, urn, *, upstream, max_hops, max_results):
                return [{"urn": hostile}] if upstream and urn == AFFECTED_URN else []

        dot = lineage_dot(
            HostileMcp(), AFFECTED_URN, {"suspects": [{"urn": hostile}]}
        )
        self.assertIsNotNone(dot)
        self.assertIn('\\"', dot)
        self.assertIn("\\\\x\\nnext", dot)
        self.assertNotIn("\n  injected [", dot)


if __name__ == "__main__":
    unittest.main()
