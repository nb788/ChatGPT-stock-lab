#!/usr/bin/env python3
"""Fail-closed Stock research gate for the historical/data repository.

A restored data allowance does not authorize research. Non-remediation work
requires a locally supplied copy of the authoritative runtime-repository gate,
plus its expected SHA-256. The script has no order or production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POINTER = ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json"
ALLOWED_STATES = {
    "HOLD_REMEDIATION_ONLY",
    "READY_FOR_WORK_DATA",
    "READY_FOR_VALIDATION",
}
RESEARCH_ACTIVITIES = {
    "WORK_DATA_ACQUISITION_OR_COMPUTE",
    "HISTORICAL_RESEARCH_OR_BACKTESTING",
    "CHALLENGER_DEVELOPMENT",
    "VALIDATION_OR_HOLDOUT_ACCESS",
}


class ResumeGateError(RuntimeError):
    pass


def load_json_bytes(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResumeGateError(f"Cannot read gate file: {path}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResumeGateError(f"Invalid JSON gate file: {path}") from exc
    if not isinstance(value, dict):
        raise ResumeGateError("Gate file must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def require(mapping: Mapping[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - set(mapping))
    if missing:
        raise ResumeGateError(f"{label} missing fields: {missing}")


def validate_pointer(pointer: Mapping[str, Any]) -> None:
    require(
        pointer,
        {
            "schema_version",
            "project_id",
            "state",
            "classification",
            "production_impact",
            "automatic_unlock",
            "may_authorize_orders",
            "authoritative_gate",
            "fallback_behavior",
            "startup_protocol",
        },
        "gate pointer",
    )
    if pointer["project_id"] != "STOCK-STRATEGY-LAB-OVERARCHING-v2.7":
        raise ResumeGateError("Unexpected Stock project ID")
    if pointer["state"] not in ALLOWED_STATES:
        raise ResumeGateError("Unknown mirrored gate state")
    if pointer["automatic_unlock"] is not False:
        raise ResumeGateError("Automatic unlock is prohibited")
    if pointer["may_authorize_orders"] is not False:
        raise ResumeGateError("Data-repository gate may not authorize orders")
    if pointer["fallback_behavior"] != "HOLD":
        raise ResumeGateError("Unavailable authoritative gate must fail closed")
    authoritative = pointer["authoritative_gate"]
    require(authoritative, {"repository", "branch", "path"}, "authoritative pointer")
    if authoritative["repository"] != "nb788/stock-lab-runtime":
        raise ResumeGateError("Pointer targets the wrong authoritative repository")
    if authoritative["branch"] != "main":
        raise ResumeGateError("Pointer must target the authoritative main branch")
    if authoritative["path"] != "PROJECT_RESEARCH_RESUME_GATE.json":
        raise ResumeGateError("Pointer targets the wrong authoritative gate path")


def validate_authoritative_gate(gate: Mapping[str, Any]) -> None:
    require(
        gate,
        {
            "schema_version",
            "project_id",
            "state",
            "automatic_unlock",
            "may_authorize_orders",
            "activity_rules",
            "prerequisites",
            "unlock_contract",
        },
        "authoritative gate",
    )
    if gate["project_id"] != "STOCK-STRATEGY-LAB-OVERARCHING-v2.7":
        raise ResumeGateError("Authoritative gate has the wrong project ID")
    if gate["state"] not in ALLOWED_STATES:
        raise ResumeGateError("Authoritative gate has an unknown state")
    if gate["automatic_unlock"] is not False:
        raise ResumeGateError("Authoritative gate enables automatic unlock")
    if gate["may_authorize_orders"] is not False:
        raise ResumeGateError("Authoritative gate may not authorize orders")
    if not isinstance(gate["prerequisites"], list) or len(gate["prerequisites"]) != 10:
        raise ResumeGateError("Authoritative gate does not carry the ten prerequisites")
    if gate["state"] in {"READY_FOR_WORK_DATA", "READY_FOR_VALIDATION"}:
        failed = [
            str(item.get("id"))
            for item in gate["prerequisites"]
            if item.get("status") != "PASS"
        ]
        if failed:
            raise ResumeGateError(
                f"Authoritative gate claims readiness with non-PASS prerequisites: {failed}"
            )
        record = gate["unlock_contract"].get("unlock_record")
        if not isinstance(record, dict) or not record.get("record_sha256"):
            raise ResumeGateError("Ready authoritative gate lacks a hashed unlock record")


def decide(
    pointer: Mapping[str, Any],
    activity: str,
    authoritative_gate: Mapping[str, Any] | None,
) -> tuple[bool, list[str], str]:
    activity = activity.upper()
    reasons: list[str] = []
    if activity in {"REMEDIATION", "WEEKLY_ENGINEERING_REVIEW"}:
        return True, ["Remediation activity is allowed while the project is held"], str(pointer["state"])
    if activity not in RESEARCH_ACTIVITIES:
        return False, ["Activity is not registered in the data-repository gate"], str(pointer["state"])
    if authoritative_gate is None:
        return False, ["No hash-verified authoritative gate was supplied"], str(pointer["state"])
    state = str(authoritative_gate["state"])
    rule = authoritative_gate["activity_rules"].get(activity)
    if not isinstance(rule, dict) or not isinstance(rule.get("allowed_states"), list):
        return False, ["Authoritative gate has no valid activity rule"], state
    allowed = state in rule["allowed_states"]
    if not allowed:
        reasons.append(f"Activity is prohibited while authoritative state is {state}")
    if activity == "VALIDATION_OR_HOLDOUT_ACCESS" and state != "READY_FOR_VALIDATION":
        allowed = False
        reasons.append("Validation requires READY_FOR_VALIDATION")
    if allowed:
        reasons.append("Hash-verified authoritative gate permits the activity")
    return allowed, reasons, state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--authoritative-gate", type=Path)
    parser.add_argument("--expect-authoritative-sha256")
    args = parser.parse_args()

    try:
        pointer, pointer_sha = load_json_bytes(args.pointer)
        validate_pointer(pointer)
        authoritative_gate = None
        authoritative_sha = None
        if args.authoritative_gate is not None:
            authoritative_gate, authoritative_sha = load_json_bytes(args.authoritative_gate)
            validate_authoritative_gate(authoritative_gate)
            if not args.expect_authoritative_sha256:
                raise ResumeGateError(
                    "An expected authoritative SHA-256 is required when a gate copy is supplied"
                )
            if authoritative_sha != args.expect_authoritative_sha256:
                raise ResumeGateError("Authoritative gate SHA-256 mismatch")
        allowed, reasons, state = decide(pointer, args.activity, authoritative_gate)
        result = {
            "status": "STOCK_RESEARCH_RESUME_ALLOW" if allowed else "STOCK_RESEARCH_RESUME_HOLD",
            "allowed": allowed,
            "activity": args.activity.upper(),
            "project_id": pointer["project_id"],
            "mirrored_state": pointer["state"],
            "authoritative_state": state if authoritative_gate is not None else None,
            "pointer_sha256": pointer_sha,
            "authoritative_gate_sha256": authoritative_sha,
            "reasons": reasons,
            "may_authorize_orders": False,
            "automatic_action_taken": False,
        }
    except ResumeGateError as exc:
        result = {
            "status": "STOCK_RESEARCH_RESUME_INVALID",
            "allowed": False,
            "reason": str(exc),
            "may_authorize_orders": False,
            "automatic_action_taken": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["allowed"] is not True:
        raise SystemExit(10)


if __name__ == "__main__":
    main()
