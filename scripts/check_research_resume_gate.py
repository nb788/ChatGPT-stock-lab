#!/usr/bin/env python3
"""Validate the project-wide stock research-resume directive mirror.

This public bridge remains permitted to perform source maintenance and QA while
the project research gate is closed. The gate blocks downstream research and
analysis consumption, not public infrastructure repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

CLASSIFICATION = "INFRASTRUCTURE_ONLY"
PRODUCTION_IMPACT = "NONE"
MAY_AUTHORIZE_ORDERS = False
EXPECTED_ARCHITECTURE = "STOCK-STRATEGY-LAB-OVERARCHING-v2.7"
RESEARCH_ACTIONS = {
    "HISTORICAL_RESEARCH",
    "NEW_BACKTEST",
    "INDICATOR_SEARCH",
    "CHALLENGER_TUNING",
    "HOLDOUT_ACCESS",
    "MODEL_PROMOTION",
}
INFRASTRUCTURE_ACTIONS = {
    "BRIDGE_MAINTENANCE",
    "SOURCE_QA",
    "CANONICAL_EXPORT",
    "GATE_MIRROR_UPDATE",
}
ALL_ACTIONS = RESEARCH_ACTIONS | INFRASTRUCTURE_ACTIONS


class GateMirrorError(RuntimeError):
    pass


@dataclass(frozen=True)
class MirrorReport:
    status: str
    gate_status: str
    requested_action: str
    action_allowed: bool
    classification: str
    production_impact: str
    may_authorize_orders: bool
    state_sha256: str
    findings: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        result = asdict(self)
        result["findings"] = list(self.findings)
        return result


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateMirrorError(f"Cannot read gate mirror: {exc}") from exc
    if not isinstance(value, dict):
        raise GateMirrorError("Gate mirror must be a JSON object")
    return value


def evaluate(state: Mapping[str, Any], action: str) -> MirrorReport:
    action = str(action).upper()
    findings: list[str] = []
    required = {
        "schema_version",
        "architecture_id",
        "gate_id",
        "gate_status",
        "authoritative_runtime_repository",
        "authoritative_state_path",
        "runtime_commit_or_pr",
        "infrastructure_may_continue",
        "research_may_continue",
        "no_order_authority",
    }
    missing = sorted(required - set(state))
    if missing:
        findings.append(f"MISSING_FIELDS:{missing}")
    if state.get("architecture_id") != EXPECTED_ARCHITECTURE:
        findings.append("ARCHITECTURE_ID_MISMATCH")
    if state.get("authoritative_runtime_repository") != "nb788/stock-lab-runtime":
        findings.append("AUTHORITATIVE_REPOSITORY_MISMATCH")
    if state.get("no_order_authority") is not True:
        findings.append("ORDER_AUTHORITY_BOUNDARY_INVALID")
    gate_status = str(state.get("gate_status", "UNKNOWN"))
    if gate_status not in {"BLOCKED_PREWORK", "OPEN"}:
        findings.append("GATE_STATUS_INVALID")
    if action not in ALL_ACTIONS:
        findings.append("UNKNOWN_ACTION")
    if action in INFRASTRUCTURE_ACTIONS:
        allowed = state.get("infrastructure_may_continue") is True
    elif action in RESEARCH_ACTIONS:
        allowed = (
            gate_status == "OPEN"
            and state.get("research_may_continue") is True
        )
    else:
        allowed = False
    if findings:
        allowed = False
    status = "PASS" if allowed else "BLOCKED"
    return MirrorReport(
        status=status,
        gate_status=gate_status,
        requested_action=action,
        action_allowed=allowed,
        classification=CLASSIFICATION,
        production_impact=PRODUCTION_IMPACT,
        may_authorize_orders=MAY_AUTHORIZE_ORDERS,
        state_sha256=canonical_hash(state),
        findings=tuple(findings),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--action", choices=sorted(ALL_ACTIONS), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(load_state(args.state), args.action).to_mapping()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["action_allowed"]:
        raise SystemExit(10)


if __name__ == "__main__":
    try:
        main()
    except (GateMirrorError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({
            "status": "GATE_MIRROR_HOLD",
            "reason": str(exc),
            "classification": CLASSIFICATION,
            "production_impact": PRODUCTION_IMPACT,
            "may_authorize_orders": MAY_AUTHORIZE_ORDERS,
        }, sort_keys=True))
        raise SystemExit(10)
