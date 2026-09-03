from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_gate.check_repo_research_hold import (
    BLOCKED,
    READY,
    canonical_hash,
    classify_path,
    evaluate_repository_gate,
)

ROOT = Path(__file__).resolve().parents[2]
STATUS = json.loads((ROOT / "research_gate" / "status_v1.json").read_text())
NOW = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)


def authorization(activity, allowed_paths, *, status=BLOCKED):
    payload = {
        "schema_version": "1.0",
        "gate_id": STATUS["gate_id"],
        "target_repository": "nb788/ChatGPT-stock-lab",
        "activity_type": activity,
        "status": status,
        "issued_at_utc": "2026-09-02T19:00:00Z",
        "expires_at_utc": "2026-09-02T21:00:00Z",
        "canonical_state_revision": 27,
        "gate_report_sha256": "a" * 64,
        "packet_set_sha256": "b" * 64,
        "packet_sha256": "c" * 64,
        "packet_id": "WP-01-UNIVERSAL-POINT-IN-TIME-PANEL",
        "run_id": "RUN-001",
        "maximum_conclusion": "DISCOVERY_ONLY",
        "allowed_paths": allowed_paths,
        "holdout_exposures_created": 0,
        "changes_signal_or_execution_or_exit_rules": False,
        "research_output_created": False,
    }
    return {**payload, "authorization_payload_sha256": canonical_hash(payload)}


class RepositoryResearchHoldTests(unittest.TestCase):
    def test_gate_maintenance_files_are_exempt(self):
        report = evaluate_repository_gate(
            STATUS,
            [
                "PROJECT_RESEARCH_HOLD.md",
                "research_gate/status_v1.json",
                ".github/workflows/project_research_hold.yml",
            ],
            None,
            NOW,
        )
        self.assertTrue(report.change_allowed)
        self.assertEqual(report.status, BLOCKED)
        self.assertEqual(len(report.exempt_paths), 3)
        self.assertEqual(report.automatic_actions_taken, ())

    def test_research_path_is_blocked_while_remediation_only(self):
        report = evaluate_repository_gate(
            STATUS,
            ["research/new_backtest.py"],
            None,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "RESEARCH_CHANGE_BLOCKED",
            {item.code for item in report.findings},
        )

    def test_research_named_file_outside_research_directory_is_blocked(self):
        self.assertEqual(classify_path("scripts/run_backtest.py"), "RESEARCH")
        report = evaluate_repository_gate(
            STATUS,
            ["scripts/run_backtest.py"],
            None,
            NOW,
        )
        self.assertFalse(report.change_allowed)

    def test_unclassified_change_fails_closed(self):
        report = evaluate_repository_gate(
            STATUS,
            ["scripts/mystery_change.py"],
            None,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "UNCLASSIFIED_CHANGE_BLOCKED",
            {item.code for item in report.findings},
        )

    def test_production_data_change_requires_manifest(self):
        report = evaluate_repository_gate(
            STATUS,
            ["data/current_snapshot.json"],
            None,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "PRODUCTION_REFRESH_AUTHORIZATION_MISSING",
            {item.code for item in report.findings},
        )

    def test_narrow_frozen_production_refresh_can_pass_while_blocked(self):
        auth = authorization(
            "FROZEN_PRODUCTION_DATA_REFRESH",
            ["data/**"],
            status=BLOCKED,
        )
        report = evaluate_repository_gate(
            STATUS,
            ["data/current_snapshot.json"],
            auth,
            NOW,
        )
        self.assertTrue(report.change_allowed)
        self.assertEqual(report.production_refresh_paths, ("data/current_snapshot.json",))
        self.assertIsNotNone(report.authorization_hash)

    def test_production_refresh_cannot_create_research_output(self):
        auth = authorization(
            "FROZEN_PRODUCTION_DATA_REFRESH",
            ["data/**"],
            status=BLOCKED,
        )
        payload = {key: copy.deepcopy(value) for key, value in auth.items() if key != "authorization_payload_sha256"}
        payload["research_output_created"] = True
        auth = {**payload, "authorization_payload_sha256": canonical_hash(payload)}
        report = evaluate_repository_gate(
            STATUS,
            ["data/current_snapshot.json"],
            auth,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "PRODUCTION_REFRESH_CREATED_RESEARCH_OUTPUT",
            {item.code for item in report.findings},
        )

    def test_authorization_is_path_scoped(self):
        auth = authorization(
            "FROZEN_PRODUCTION_DATA_REFRESH",
            ["data/approved/**"],
            status=BLOCKED,
        )
        report = evaluate_repository_gate(
            STATUS,
            ["data/unapproved/snapshot.json"],
            auth,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "CHANGED_PATH_OUTSIDE_AUTHORIZATION",
            {item.code for item in report.findings},
        )

    def test_ready_status_still_requires_frozen_packet_authorization(self):
        ready = copy.deepcopy(STATUS)
        ready["status"] = READY
        ready["research_resumption_allowed"] = True
        report = evaluate_repository_gate(
            ready,
            ["research/WP-01/build_panel.py"],
            None,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "CONTROLLED_RESEARCH_AUTHORIZATION_MISSING",
            {item.code for item in report.findings},
        )

    def test_ready_research_authorization_can_be_path_scoped(self):
        ready = copy.deepcopy(STATUS)
        ready["status"] = READY
        ready["research_resumption_allowed"] = True
        auth = authorization(
            "CONTROLLED_RESEARCH_WORK_PACKET",
            ["research/WP-01/**"],
            status=READY,
        )
        report = evaluate_repository_gate(
            ready,
            ["research/WP-01/build_panel.py"],
            auth,
            NOW,
        )
        self.assertTrue(report.change_allowed)

    def test_expired_authorization_is_blocked(self):
        auth = authorization(
            "FROZEN_PRODUCTION_DATA_REFRESH",
            ["data/**"],
            status=BLOCKED,
        )
        payload = {key: copy.deepcopy(value) for key, value in auth.items() if key != "authorization_payload_sha256"}
        payload["expires_at_utc"] = "2026-09-02T19:30:00Z"
        auth = {**payload, "authorization_payload_sha256": canonical_hash(payload)}
        report = evaluate_repository_gate(
            STATUS,
            ["data/current_snapshot.json"],
            auth,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "AUTHORIZATION_TIME_INVALID",
            {item.code for item in report.findings},
        )

    def test_tampered_authorization_is_blocked(self):
        auth = authorization(
            "FROZEN_PRODUCTION_DATA_REFRESH",
            ["data/**"],
            status=BLOCKED,
        )
        auth["run_id"] = "ALTERED"
        report = evaluate_repository_gate(
            STATUS,
            ["data/current_snapshot.json"],
            auth,
            NOW,
        )
        self.assertFalse(report.change_allowed)
        self.assertIn(
            "AUTHORIZATION_PAYLOAD_HASH_MISMATCH",
            {item.code for item in report.findings},
        )

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(Exception):
            evaluate_repository_gate(STATUS, ["../research/backtest.py"], None, NOW)


if __name__ == "__main__":
    unittest.main()
