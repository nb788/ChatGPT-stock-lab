#!/usr/bin/env python3
"""Run a historical Stock-research command only after gate authorization.

Non-remediation activity requires a local copy of the authoritative runtime gate
and its expected SHA-256. The attempt is recorded before any command can run.
This wrapper cannot authorize orders or change the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "check_stock_research_resume.py"
SPEC = importlib.util.spec_from_file_location(
    "stock_data_resume_checker",
    CHECKER_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load the Stock research resume checker")
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)

DEFAULT_POINTER = ROOT / "PROJECT_RESEARCH_RESUME_GATE_POINTER.json"


class GuardedResearchError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def receipt(
    *,
    status: str,
    allowed: bool,
    activity: str,
    reasons: list[str],
    pointer_sha256: str,
    authoritative_sha256: str | None,
    authoritative_state: str | None,
    command: list[str],
    started_at_utc: str,
    completed_at_utc: str | None,
    command_exit_code: int | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "classification": "PROJECT_GOVERNANCE_RECEIPT",
        "production_impact": "NONE",
        "may_authorize_orders": False,
        "automatic_action_taken": False,
        "status": status,
        "allowed": allowed,
        "activity": activity,
        "project_id": "STOCK-STRATEGY-LAB-OVERARCHING-v2.7",
        "pointer_sha256": pointer_sha256,
        "authoritative_gate_sha256": authoritative_sha256,
        "authoritative_state": authoritative_state,
        "reasons": reasons,
        "command_fingerprint": {
            "argv_sha256": canonical_hash(command),
            "executable_basename": Path(command[0]).name if command else None,
            "argument_count": len(command),
        },
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "command_exit_code": command_exit_code,
        "runtime_context": {
            "repository": os.getenv("GITHUB_REPOSITORY"),
            "git_sha": os.getenv("GITHUB_SHA"),
            "workflow": os.getenv("GITHUB_WORKFLOW"),
            "run_id": os.getenv("GITHUB_RUN_ID"),
        },
    }
    return {**payload, "receipt_payload_sha256": canonical_hash(payload)}


def run(
    *,
    pointer_path: Path,
    activity: str,
    command: list[str],
    receipt_path: Path,
    authoritative_gate_path: Path | None = None,
    expected_authoritative_sha256: str | None = None,
) -> int:
    if not command:
        raise GuardedResearchError("A command is required after --")
    pointer, pointer_sha = checker.load_json_bytes(pointer_path)
    checker.validate_pointer(pointer)

    authoritative = None
    authoritative_sha = None
    if authoritative_gate_path is not None:
        authoritative, authoritative_sha = checker.load_json_bytes(
            authoritative_gate_path
        )
        checker.validate_authoritative_gate(authoritative)
        if not expected_authoritative_sha256:
            raise GuardedResearchError(
                "An expected authoritative SHA-256 is required"
            )
        if authoritative_sha != expected_authoritative_sha256:
            raise GuardedResearchError("Authoritative gate SHA-256 mismatch")
    elif activity.upper() not in {"REMEDIATION", "WEEKLY_ENGINEERING_REVIEW"}:
        # The checker also fails closed, but make the requirement explicit before
        # constructing an execution receipt.
        authoritative = None

    allowed, reasons, state = checker.decide(
        pointer,
        activity,
        authoritative,
    )
    started = now_utc()
    if not allowed:
        result = receipt(
            status="STOCK_RESEARCH_RESUME_HOLD",
            allowed=False,
            activity=activity.upper(),
            reasons=reasons,
            pointer_sha256=pointer_sha,
            authoritative_sha256=authoritative_sha,
            authoritative_state=state if authoritative is not None else None,
            command=command,
            started_at_utc=started,
            completed_at_utc=started,
            command_exit_code=None,
        )
        atomic_json(receipt_path, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 10

    environment = os.environ.copy()
    environment.update(
        {
            "STOCK_PROJECT_ACTIVITY": activity.upper(),
            "STOCK_PROJECT_GATE_STATE": state,
            "STOCK_PROJECT_GATE_SHA256": authoritative_sha or "REMEDIATION_WITHOUT_GATE_COPY",
            "STOCK_PROJECT_GATE_POINTER_SHA256": pointer_sha,
        }
    )
    process = subprocess.run(command, check=False, env=environment)
    result = receipt(
        status="COMMAND_COMPLETED" if process.returncode == 0 else "COMMAND_FAILED",
        allowed=True,
        activity=activity.upper(),
        reasons=reasons,
        pointer_sha256=pointer_sha,
        authoritative_sha256=authoritative_sha,
        authoritative_state=state,
        command=command,
        started_at_utc=started,
        completed_at_utc=now_utc(),
        command_exit_code=int(process.returncode),
    )
    atomic_json(receipt_path, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(process.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--authoritative-gate", type=Path)
    parser.add_argument("--expect-authoritative-sha256")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        code = run(
            pointer_path=args.pointer,
            activity=args.activity,
            command=command,
            receipt_path=args.receipt,
            authoritative_gate_path=args.authoritative_gate,
            expected_authoritative_sha256=args.expect_authoritative_sha256,
        )
    except (GuardedResearchError, checker.ResumeGateError, OSError, ValueError) as exc:
        result = {
            "schema_version": "1.0",
            "status": "GUARDED_STOCK_RESEARCH_INVALID",
            "allowed": False,
            "reason": str(exc),
            "may_authorize_orders": False,
            "automatic_action_taken": False,
        }
        atomic_json(args.receipt, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(10)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
