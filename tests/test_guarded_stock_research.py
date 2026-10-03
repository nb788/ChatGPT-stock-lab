from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_guarded_stock_research",
    ROOT / "scripts" / "run_guarded_stock_research.py",
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def held_gate() -> dict:
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


def ready_gate(state: str = "READY_FOR_WORK_DATA") -> dict:
    gate = held_gate()
    gate["state"] = state
    for item in gate["prerequisites"]:
        item["status"] = "PASS"
    gate["unlock_contract"]["unlock_record"] = {"record_sha256": "a" * 64}
    return gate


class GuardedStockResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pointer = ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json"

    def write_gate(self, directory: Path, gate: dict) -> tuple[Path, str]:
        path = directory / "authoritative-gate.json"
        path.write_text(json.dumps(gate, sort_keys=True), encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_held_historical_command_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            gate_path, digest = self.write_gate(directory, held_gate())
            marker = directory / "must-not-exist.txt"
            receipt_path = directory / "receipt.json"
            code = mod.run(
                pointer_path=self.pointer,
                activity="HISTORICAL_RESEARCH_OR_BACKTESTING",
                command=[
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
                ],
                receipt_path=receipt_path,
                authoritative_gate_path=gate_path,
                expected_authoritative_sha256=digest,
            )
            self.assertEqual(code, 10)
            self.assertFalse(marker.exists())
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "STOCK_RESEARCH_RESUME_HOLD")
            self.assertFalse(receipt["allowed"])
            self.assertEqual(receipt["authoritative_gate_sha256"], digest)
            self.assertFalse(receipt["may_authorize_orders"])

    def test_research_without_authoritative_copy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            marker = directory / "must-not-exist.txt"
            receipt_path = directory / "receipt.json"
            code = mod.run(
                pointer_path=self.pointer,
                activity="WORK_DATA_ACQUISITION_OR_COMPUTE",
                command=[
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
                ],
                receipt_path=receipt_path,
            )
            self.assertEqual(code, 10)
            self.assertFalse(marker.exists())
            receipt = json.loads(receipt_path.read_text())
            self.assertIsNone(receipt["authoritative_gate_sha256"])

    def test_wrong_authoritative_hash_blocks_before_execution(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            gate_path, _ = self.write_gate(directory, ready_gate())
            marker = directory / "must-not-exist.txt"
            with self.assertRaises(mod.GuardedResearchError):
                mod.run(
                    pointer_path=self.pointer,
                    activity="HISTORICAL_RESEARCH_OR_BACKTESTING",
                    command=[
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
                    ],
                    receipt_path=directory / "receipt.json",
                    authoritative_gate_path=gate_path,
                    expected_authoritative_sha256="0" * 64,
                )
            self.assertFalse(marker.exists())

    def test_ready_for_work_data_launches_research_with_hashed_receipt(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            gate_path, digest = self.write_gate(directory, ready_gate())
            marker = directory / "created.txt"
            receipt_path = directory / "receipt.json"
            code = mod.run(
                pointer_path=self.pointer,
                activity="HISTORICAL_RESEARCH_OR_BACKTESTING",
                command=[
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
                ],
                receipt_path=receipt_path,
                authoritative_gate_path=gate_path,
                expected_authoritative_sha256=digest,
            )
            self.assertEqual(code, 0)
            self.assertEqual(marker.read_text(), "ok")
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "COMMAND_COMPLETED")
            self.assertTrue(receipt["allowed"])
            self.assertEqual(receipt["authoritative_state"], "READY_FOR_WORK_DATA")
            self.assertEqual(receipt["authoritative_gate_sha256"], digest)
            payload = {
                key: value
                for key, value in receipt.items()
                if key != "receipt_payload_sha256"
            }
            self.assertEqual(
                receipt["receipt_payload_sha256"],
                mod.canonical_hash(payload),
            )

    def test_ready_for_work_data_does_not_launch_validation(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            gate_path, digest = self.write_gate(directory, ready_gate())
            marker = directory / "must-not-exist.txt"
            code = mod.run(
                pointer_path=self.pointer,
                activity="VALIDATION_OR_HOLDOUT_ACCESS",
                command=[
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
                ],
                receipt_path=directory / "receipt.json",
                authoritative_gate_path=gate_path,
                expected_authoritative_sha256=digest,
            )
            self.assertEqual(code, 10)
            self.assertFalse(marker.exists())

    def test_remediation_can_run_while_held_without_gate_copy(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            marker = directory / "created.txt"
            receipt_path = directory / "receipt.json"
            code = mod.run(
                pointer_path=self.pointer,
                activity="REMEDIATION",
                command=[
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
                ],
                receipt_path=receipt_path,
            )
            self.assertEqual(code, 0)
            self.assertEqual(marker.read_text(), "ok")
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["activity"], "REMEDIATION")
            self.assertTrue(receipt["allowed"])

    def test_child_exit_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            receipt_path = directory / "receipt.json"
            code = mod.run(
                pointer_path=self.pointer,
                activity="REMEDIATION",
                command=[sys.executable, "-c", "raise SystemExit(7)"],
                receipt_path=receipt_path,
            )
            self.assertEqual(code, 7)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "COMMAND_FAILED")
            self.assertEqual(receipt["command_exit_code"], 7)


if __name__ == "__main__":
    unittest.main()
