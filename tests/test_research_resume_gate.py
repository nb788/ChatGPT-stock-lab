from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.check_research_resume_gate import evaluate

ROOT = Path(__file__).resolve().parents[1]
STATE = json.loads(
    (ROOT / "data" / "research_resume_gate_status.json").read_text()
)
POINTER = json.loads(
    (ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json").read_text()
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
        self.assertFalse(STATE["research_may_continue"])

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
        self.assertEqual(
            STATE["authoritative_state_path"],
            "research_only/project_resume_gate_v1.json",
        )

    def test_pointer_resolves_the_real_runtime_gate(self):
        authoritative = POINTER["authoritative_gate"]
        self.assertEqual(authoritative["repository"], "nb788/stock-lab-runtime")
        self.assertEqual(authoritative["branch"], "main")
        self.assertEqual(
            authoritative["path"],
            "research_only/project_resume_gate_v1.json",
        )
        self.assertEqual(
            authoritative["verified_commit"],
            "2b01a4d22e746ff71f5fa61a2cc5fa9dbbe88c04",
        )
        self.assertEqual(authoritative["gate_status"], "BLOCKED_PREWORK")
        self.assertFalse(POINTER["automatic_unlock"])
        self.assertFalse(POINTER["may_authorize_orders"])

    def test_broker_progress_does_not_open_research(self):
        self.assertIn(
            "PRE-03-BROKER-STATE-RECONCILED",
            STATE["passed_prerequisites"],
        )
        self.assertGreater(len(STATE["remaining_required_prerequisites"]), 0)
        self.assertFalse(POINTER["latest_verified_progress"]["research_gate_open"])
        self.assertEqual(
            POINTER["latest_verified_progress"]["positions"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
