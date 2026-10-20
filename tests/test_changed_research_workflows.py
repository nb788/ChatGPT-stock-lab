from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_changed_research_workflows",
    ROOT / "scripts" / "audit_changed_research_workflows.py",
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def codes(findings):
    return {item.code for item in findings}


class ChangedResearchWorkflowTests(unittest.TestCase):
    def test_marker_is_required(self):
        findings = mod.audit_workflow_text("x.yml", "name: x\n")
        self.assertIn("WORKFLOW_ACTIVITY_MARKER_COUNT_INVALID", codes(findings))

    def test_research_requires_guard_authoritative_copy_and_hash(self):
        text = (
            "# stock-project-activity: HISTORICAL_RESEARCH_OR_BACKTESTING\n"
            "name: research\n"
            "run: python scripts/backtest.py\n"
        )
        findings = mod.audit_workflow_text("research.yml", text)
        self.assertTrue(
            {
                "DATA_RESEARCH_WORKFLOW_BYPASSES_GATE",
                "DATA_RESEARCH_ACTIVITY_ARGUMENT_MISMATCH",
                "AUTHORITATIVE_GATE_PINNING_MISSING",
            }.issubset(codes(findings))
        )

    def test_guarded_research_passes(self):
        text = (
            "# stock-project-activity: HISTORICAL_RESEARCH_OR_BACKTESTING\n"
            "name: research\n"
            "run: python scripts/run_guarded_stock_research.py "
            "--activity HISTORICAL_RESEARCH_OR_BACKTESTING "
            "--authoritative-gate /tmp/gate.json "
            "--expect-authoritative-sha256 $GATE_SHA "
            "--receipt runs/receipt.json -- python scripts/backtest.py\n"
        )
        self.assertEqual(mod.audit_workflow_text("research.yml", text), [])

    def test_validation_requires_ready_for_validation_documentation(self):
        text = (
            "# stock-project-activity: VALIDATION_OR_HOLDOUT_ACCESS\n"
            "name: validation\n"
            "run: python scripts/run_guarded_stock_research.py "
            "--activity VALIDATION_OR_HOLDOUT_ACCESS "
            "--authoritative-gate /tmp/gate.json "
            "--expect-authoritative-sha256 $GATE_SHA "
            "--receipt runs/receipt.json -- python scripts/validate.py\n"
        )
        findings = mod.audit_workflow_text("validation.yml", text)
        self.assertIn("VALIDATION_READINESS_STATE_UNSTATED", codes(findings))
        self.assertEqual(
            mod.audit_workflow_text(
                "validation.yml",
                text + "# READY_FOR_VALIDATION required\n",
            ),
            [],
        )

    def test_order_paths_are_prohibited(self):
        text = (
            "# stock-project-activity: REMEDIATION\n"
            "name: unsafe\n"
            "run: python scripts/opening_loo_order.py --submit\n"
        )
        findings = mod.audit_workflow_text("unsafe.yml", text)
        self.assertIn("ORDER_PATH_PROHIBITED_IN_DATA_REPOSITORY", codes(findings))

    def test_production_close_classification_is_allowed(self):
        text = (
            "# stock-project-activity: PRODUCTION_CLOSE_AND_OUTCOME_CAPTURE\n"
            "name: production data bridge\n"
            "run: python scripts/refresh_close_inputs.py\n"
        )
        self.assertEqual(mod.audit_workflow_text("close.yml", text), [])

    def test_report_has_no_order_or_automatic_authority(self):
        report = mod.audit_paths([], ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["may_authorize_orders"])
        self.assertFalse(report["automatic_action_taken"])


if __name__ == "__main__":
    unittest.main()
