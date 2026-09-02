from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.check_research_resume_gate import evaluate

ROOT = Path(__file__).resolve().parents[1]
STATE = json.loads(
    (ROOT / "data" / "research_resume_gate_status.json").read_text()
)


class ResearchResumeGateMirrorTests(unittest.TestCase):
    def test_bridge_maintenance_remains_allowed(self):
        report = evaluate(STATE, "BRIDGE_MAINTENANCE")
        self.assertTrue(report.action_allowed)
        self.assertFalse(report.may_authorize_orders)

    def test_research_is_blocked_until_runtime_gate_opens(self):
        report = evaluate(STATE, "HISTORICAL_RESEARCH")
        self.assertFalse(report.action_allowed)
        self.assertEqual(report.gate_status, "BLOCKED_PREWORK")

    def test_no_order_authority_is_hard_boundary(self):
        changed = dict(STATE)
        changed["no_order_authority"] = False
        report = evaluate(changed, "BRIDGE_MAINTENANCE")
        self.assertFalse(report.action_allowed)
        self.assertIn("ORDER_AUTHORITY_BOUNDARY_INVALID", report.findings)

    def test_architecture_and_authoritative_repository_are_pinned(self):
        self.assertEqual(
            STATE["architecture_id"],
            "STOCK-STRATEGY-LAB-OVERARCHING-v2.7",
        )
        self.assertEqual(
            STATE["authoritative_runtime_repository"],
            "nb788/stock-lab-runtime",
        )


if __name__ == "__main__":
    unittest.main()
