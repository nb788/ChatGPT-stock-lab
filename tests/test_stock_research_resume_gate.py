from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_stock_research_resume",
    ROOT / "scripts" / "check_stock_research_resume.py",
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
POINTER, POINTER_SHA = mod.load_json_bytes(
    ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json"
)


def held_gate():
    return {
        "schema_version": "1.0",
        "project_id": "STOCK-STRATEGY-LAB-OVERARCHING-v2.7",
        "state": "HOLD_REMEDIATION_ONLY",
        "automatic_unlock": False,
        "may_authorize_orders": False,
        "activity_rules": {
            "WORK_DATA_ACQUISITION_OR_COMPUTE": {
                "allowed_states": ["READY_FOR_WORK_DATA", "READY_FOR_VALIDATION"]
            },
            "HISTORICAL_RESEARCH_OR_BACKTESTING": {
                "allowed_states": ["READY_FOR_WORK_DATA", "READY_FOR_VALIDATION"]
            },
            "CHALLENGER_DEVELOPMENT": {
                "allowed_states": ["READY_FOR_WORK_DATA", "READY_FOR_VALIDATION"]
            },
            "VALIDATION_OR_HOLDOUT_ACCESS": {
                "allowed_states": ["READY_FOR_VALIDATION"]
            },
        },
        "prerequisites": [
            {"id": f"RG-{index:02d}", "status": "OPEN"}
            for index in range(1, 11)
        ],
        "unlock_contract": {"unlock_record": None},
    }


class StockResearchResumeGateTests(unittest.TestCase):
    def test_pointer_is_fail_closed_and_points_to_runtime_main(self):
        mod.validate_pointer(POINTER)
        self.assertEqual(POINTER["state"], "HOLD_REMEDIATION_ONLY")
        self.assertEqual(POINTER["fallback_behavior"], "HOLD")
        self.assertFalse(POINTER["automatic_unlock"])
        self.assertFalse(POINTER["may_authorize_orders"])
        self.assertEqual(
            POINTER["authoritative_gate"],
            {
                "repository": "nb788/stock-lab-runtime",
                "branch": "main",
                "path": "PROJECT_RESEARCH_RESUME_GATE.json",
            },
        )

    def test_research_is_blocked_without_authoritative_gate_copy(self):
        for activity in sorted(mod.RESEARCH_ACTIVITIES):
            allowed, reasons, state = mod.decide(POINTER, activity, None)
            self.assertFalse(allowed, activity)
            self.assertEqual(state, "HOLD_REMEDIATION_ONLY")
            self.assertTrue(any("No hash-verified" in reason for reason in reasons))

    def test_supplied_held_gate_still_blocks_research(self):
        gate = held_gate()
        mod.validate_authoritative_gate(gate)
        for activity in sorted(mod.RESEARCH_ACTIVITIES):
            allowed, _, state = mod.decide(POINTER, activity, gate)
            self.assertFalse(allowed, activity)
            self.assertEqual(state, "HOLD_REMEDIATION_ONLY")

    def test_remediation_and_weekly_review_are_allowed(self):
        for activity in ("REMEDIATION", "WEEKLY_ENGINEERING_REVIEW"):
            allowed, _, _ = mod.decide(POINTER, activity, None)
            self.assertTrue(allowed, activity)

    def test_ready_gate_cannot_skip_prerequisites(self):
        gate = held_gate()
        gate["state"] = "READY_FOR_WORK_DATA"
        with self.assertRaises(mod.ResumeGateError):
            mod.validate_authoritative_gate(gate)

    def test_ready_for_work_data_allows_research_but_not_validation(self):
        gate = held_gate()
        gate["state"] = "READY_FOR_WORK_DATA"
        for item in gate["prerequisites"]:
            item["status"] = "PASS"
        gate["unlock_contract"]["unlock_record"] = {"record_sha256": "a" * 64}
        mod.validate_authoritative_gate(gate)
        for activity in (
            "WORK_DATA_ACQUISITION_OR_COMPUTE",
            "HISTORICAL_RESEARCH_OR_BACKTESTING",
            "CHALLENGER_DEVELOPMENT",
        ):
            allowed, _, _ = mod.decide(POINTER, activity, gate)
            self.assertTrue(allowed, activity)
        allowed, _, _ = mod.decide(
            POINTER,
            "VALIDATION_OR_HOLDOUT_ACCESS",
            gate,
        )
        self.assertFalse(allowed)

    def test_ready_for_validation_is_separate(self):
        gate = held_gate()
        gate["state"] = "READY_FOR_VALIDATION"
        for item in gate["prerequisites"]:
            item["status"] = "PASS"
        gate["unlock_contract"]["unlock_record"] = {"record_sha256": "a" * 64}
        mod.validate_authoritative_gate(gate)
        allowed, _, _ = mod.decide(
            POINTER,
            "VALIDATION_OR_HOLDOUT_ACCESS",
            gate,
        )
        self.assertTrue(allowed)

    def test_pointer_hash_is_recordable(self):
        self.assertEqual(
            POINTER_SHA,
            hashlib.sha256(
                (ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json").read_bytes()
            ).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
