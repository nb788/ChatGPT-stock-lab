#!/usr/bin/env python3
"""Fail-closed cross-repository research gate for ChatGPT-stock-lab.

This repository may supply immutable public-data snapshots to the frozen
production process, but it may not become an alternate route around the
project-wide Stock Strategy research hold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"
GATE_ID = "STOCK-PROJECT-RESEARCH-RESUMPTION-v1"
TARGET_REPOSITORY = "nb788/ChatGPT-stock-lab"
READY = "READY_FOR_CONTROLLED_RESEARCH_RESUMPTION"
BLOCKED = "REMEDIATION_ONLY"
HEX64 = set("0123456789abcdef")

GATE_EXEMPT_PATHS = {
    "PROJECT_RESEARCH_HOLD.md",
}
GATE_EXEMPT_PREFIXES = (
    "research_gate/",
    ".github/workflows/project_research_hold.yml",
)
FROZEN_PRODUCTION_PREFIXES = (
    "data/",
    "runs/",
    "snapshots/",
    "runtime_snapshot/",
)
RESEARCH_PREFIXES = (
    "analysis/",
    "backtests/",
    "challengers/",
    "experiments/",
    "models/",
    "notebooks/",
    "research/",
    "validation/",
    "holdouts/",
)
RESEARCH_TOKENS = {
    "analysis",
    "backtest",
    "benchmark_search",
    "challenger",
    "experiment",
    "feature_search",
    "fit_model",
    "holdout",
    "hyperparameter",
    "model_fit",
    "model_train",
    "optimization",
    "parameter_search",
    "research",
    "retune",
    "validation",
}


class RepoGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class RepoGateReport:
    schema_version: str
    gate_id: str
    repository: str
    status: str
    change_allowed: bool
    changed_paths: tuple[str, ...]
    exempt_paths: tuple[str, ...]
    production_refresh_paths: tuple[str, ...]
    research_paths: tuple[str, ...]
    unclassified_paths: tuple[str, ...]
    authorization_hash: str | None
    findings: tuple[Finding, ...]
    automatic_actions_taken: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "repository": self.repository,
            "status": self.status,
            "change_allowed": self.change_allowed,
            "changed_paths": list(self.changed_paths),
            "exempt_paths": list(self.exempt_paths),
            "production_refresh_paths": list(self.production_refresh_paths),
            "research_paths": list(self.research_paths),
            "unclassified_paths": list(self.unclassified_paths),
            "authorization_hash": self.authorization_hash,
            "findings": [asdict(item) for item in self.findings],
            "automatic_actions_taken": list(self.automatic_actions_taken),
        }


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def is_sha256(value: Any) -> bool:
    text = str(value).lower()
    return len(text) == 64 and set(text) <= HEX64


def require(value: Mapping[str, Any], fields: Iterable[str], label: str) -> None:
    missing = sorted(set(fields) - set(value))
    if missing:
        raise RepoGateError(f"{label} missing fields: {missing}")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RepoGateError(f"Timestamp lacks timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def normalize_path(value: str) -> str:
    text = str(value).strip().replace("\\", "/")
    if not text:
        raise RepoGateError("Changed-file path cannot be blank")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise RepoGateError(f"Unsafe changed-file path: {value!r}")
    return pure.as_posix()


def load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepoGateError(f"Repository-gate input is absent: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RepoGateError(f"Invalid JSON: {path}") from exc


def read_changed_files(path: Path) -> list[str]:
    try:
        rows = [normalize_path(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError as exc:
        raise RepoGateError(f"Changed-file list is absent: {path}") from exc
    if len(rows) != len(set(rows)):
        raise RepoGateError("Changed-file list contains duplicates")
    return sorted(rows)


def _tokens(path: str) -> set[str]:
    stem = path.lower().replace("-", "_").replace(".", "_").replace("/", "_")
    return {token for token in stem.split("_") if token}


def classify_path(path: str) -> str:
    if path in GATE_EXEMPT_PATHS or path.startswith(GATE_EXEMPT_PREFIXES):
        return "GATE_EXEMPT"
    if path.startswith(RESEARCH_PREFIXES):
        return "RESEARCH"
    lower = path.lower()
    if any(token in lower for token in RESEARCH_TOKENS):
        return "RESEARCH"
    if path.startswith(FROZEN_PRODUCTION_PREFIXES):
        return "FROZEN_PRODUCTION_REFRESH"
    return "UNCLASSIFIED"


def _path_allowed(path: str, allowed: Sequence[str]) -> bool:
    for rule in allowed:
        normalized = normalize_path(rule)
        if normalized.endswith("/**"):
            prefix = normalized[:-3]
            if path == prefix.rstrip("/") or path.startswith(prefix):
                return True
        elif path == normalized:
            return True
    return False


def validate_authorization(
    authorization: Mapping[str, Any],
    status: Mapping[str, Any],
    changed_paths: Sequence[str],
    now: datetime,
    expected_activity: str,
) -> tuple[list[Finding], str]:
    findings: list[Finding] = []
    require(
        authorization,
        {
            "schema_version",
            "gate_id",
            "target_repository",
            "activity_type",
            "status",
            "issued_at_utc",
            "expires_at_utc",
            "canonical_state_revision",
            "gate_report_sha256",
            "packet_set_sha256",
            "packet_sha256",
            "packet_id",
            "run_id",
            "maximum_conclusion",
            "allowed_paths",
            "holdout_exposures_created",
            "changes_signal_or_execution_or_exit_rules",
            "research_output_created",
            "authorization_payload_sha256",
        },
        "repository authorization",
    )
    if authorization["schema_version"] != SCHEMA_VERSION:
        findings.append(Finding(
            "AUTHORIZATION_SCHEMA_MISMATCH", "CRITICAL",
            "Authorization schema is unsupported.",
        ))
    if authorization["gate_id"] != GATE_ID or authorization["gate_id"] != status["gate_id"]:
        findings.append(Finding(
            "AUTHORIZATION_GATE_ID_MISMATCH", "CRITICAL",
            "Authorization belongs to a different project gate.",
        ))
    if authorization["target_repository"] != TARGET_REPOSITORY:
        findings.append(Finding(
            "AUTHORIZATION_REPOSITORY_MISMATCH", "CRITICAL",
            "Authorization targets a different repository.",
        ))
    if authorization["activity_type"] != expected_activity:
        findings.append(Finding(
            "AUTHORIZATION_ACTIVITY_MISMATCH", "CRITICAL",
            f"Expected activity {expected_activity!r}.",
        ))
    issued = parse_utc(str(authorization["issued_at_utc"]))
    expires = parse_utc(str(authorization["expires_at_utc"]))
    if issued > now or expires <= now or expires <= issued:
        findings.append(Finding(
            "AUTHORIZATION_TIME_INVALID", "CRITICAL",
            "Authorization is future-dated, expired, or has an invalid interval.",
        ))
    if int(authorization["canonical_state_revision"]) < 1:
        findings.append(Finding(
            "AUTHORIZATION_CANONICAL_REVISION_INVALID", "CRITICAL",
            "Authorization has no positive canonical-state revision.",
        ))
    for field in ("gate_report_sha256", "packet_set_sha256", "packet_sha256"):
        if not is_sha256(authorization[field]):
            findings.append(Finding(
                "AUTHORIZATION_HASH_INVALID", "CRITICAL",
                f"Authorization field {field} is not a SHA-256 digest.",
            ))
    if not isinstance(authorization["allowed_paths"], list) or not authorization["allowed_paths"]:
        findings.append(Finding(
            "AUTHORIZATION_ALLOWED_PATHS_MISSING", "CRITICAL",
            "Authorization has no allowed paths.",
        ))
    else:
        for path in changed_paths:
            if classify_path(path) == "GATE_EXEMPT":
                continue
            if not _path_allowed(path, authorization["allowed_paths"]):
                findings.append(Finding(
                    "CHANGED_PATH_OUTSIDE_AUTHORIZATION", "CRITICAL",
                    "Changed path is not authorized.", path,
                ))
    if int(authorization["holdout_exposures_created"]) != 0:
        findings.append(Finding(
            "AUTHORIZATION_EXPOSED_HOLDOUT", "CRITICAL",
            "Authorization records a new holdout exposure.",
        ))
    if authorization["changes_signal_or_execution_or_exit_rules"] is not False:
        findings.append(Finding(
            "AUTHORIZATION_ECONOMIC_CHANGE", "CRITICAL",
            "Repository authorization may not change trading economics.",
        ))
    if expected_activity == "FROZEN_PRODUCTION_DATA_REFRESH" and authorization["research_output_created"] is not False:
        findings.append(Finding(
            "PRODUCTION_REFRESH_CREATED_RESEARCH_OUTPUT", "CRITICAL",
            "A frozen production refresh may not create a research output.",
        ))
    if expected_activity == "CONTROLLED_RESEARCH_WORK_PACKET":
        if authorization["status"] != READY:
            findings.append(Finding(
                "RESEARCH_AUTHORIZATION_NOT_READY", "CRITICAL",
                "Controlled research authorization is not READY.",
            ))
        if not str(authorization["packet_id"]).startswith("WP-"):
            findings.append(Finding(
                "RESEARCH_AUTHORIZATION_PACKET_ID_INVALID", "CRITICAL",
                "Controlled research authorization lacks a frozen packet ID.",
            ))
    elif authorization["status"] not in {BLOCKED, READY}:
        findings.append(Finding(
            "PRODUCTION_REFRESH_GATE_STATUS_INVALID", "CRITICAL",
            "Frozen production refresh authorization has an invalid gate status.",
        ))
    payload = {key: value for key, value in authorization.items() if key != "authorization_payload_sha256"}
    digest = canonical_hash(payload)
    if authorization["authorization_payload_sha256"] != digest:
        findings.append(Finding(
            "AUTHORIZATION_PAYLOAD_HASH_MISMATCH", "CRITICAL",
            "Authorization payload hash is invalid.",
        ))
    return findings, digest


def evaluate_repository_gate(
    status: Mapping[str, Any],
    changed_paths: Sequence[str],
    authorization: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> RepoGateReport:
    require(
        status,
        {
            "schema_version",
            "gate_id",
            "classification",
            "production_impact",
            "status",
            "research_resumption_allowed",
            "waivers_permitted",
        },
        "repository gate status",
    )
    if status["schema_version"] != SCHEMA_VERSION or status["gate_id"] != GATE_ID:
        raise RepoGateError("Repository gate status is incompatible")
    if status["production_impact"] != "NONE" or status["waivers_permitted"] is not False:
        raise RepoGateError("Repository gate may not have production impact or waivers")
    normalized = tuple(sorted(normalize_path(path) for path in changed_paths))
    buckets = {
        "GATE_EXEMPT": [],
        "FROZEN_PRODUCTION_REFRESH": [],
        "RESEARCH": [],
        "UNCLASSIFIED": [],
    }
    for path in normalized:
        buckets[classify_path(path)].append(path)
    findings: list[Finding] = []
    authorization_hash: str | None = None
    current = now or datetime.now(timezone.utc)

    nonexempt = [path for path in normalized if classify_path(path) != "GATE_EXEMPT"]
    gate_state = str(status["status"])
    if not nonexempt:
        allowed = True
    elif gate_state == BLOCKED:
        if buckets["RESEARCH"]:
            for path in buckets["RESEARCH"]:
                findings.append(Finding(
                    "RESEARCH_CHANGE_BLOCKED", "CRITICAL",
                    "Research-like change is prohibited while the project is REMEDIATION_ONLY.", path,
                ))
        if buckets["UNCLASSIFIED"]:
            for path in buckets["UNCLASSIFIED"]:
                findings.append(Finding(
                    "UNCLASSIFIED_CHANGE_BLOCKED", "CRITICAL",
                    "Unclassified change fails closed while the project is REMEDIATION_ONLY.", path,
                ))
        if buckets["FROZEN_PRODUCTION_REFRESH"]:
            if authorization is None:
                findings.append(Finding(
                    "PRODUCTION_REFRESH_AUTHORIZATION_MISSING", "CRITICAL",
                    "Frozen production data changes require a narrow authorization manifest.",
                ))
            else:
                auth_findings, authorization_hash = validate_authorization(
                    authorization,
                    status,
                    buckets["FROZEN_PRODUCTION_REFRESH"],
                    current,
                    "FROZEN_PRODUCTION_DATA_REFRESH",
                )
                findings.extend(auth_findings)
        allowed = not any(item.severity == "CRITICAL" for item in findings)
    elif gate_state == READY:
        if authorization is None:
            findings.append(Finding(
                "CONTROLLED_RESEARCH_AUTHORIZATION_MISSING", "CRITICAL",
                "READY status does not permit unmanifested research changes.",
            ))
        else:
            auth_findings, authorization_hash = validate_authorization(
                authorization,
                status,
                nonexempt,
                current,
                "CONTROLLED_RESEARCH_WORK_PACKET",
            )
            findings.extend(auth_findings)
        allowed = not any(item.severity == "CRITICAL" for item in findings)
    else:
        findings.append(Finding(
            "UNKNOWN_PROJECT_GATE_STATUS", "CRITICAL",
            f"Unknown project gate status {gate_state!r}.",
        ))
        allowed = False

    findings.sort(key=lambda item: (
        {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}.get(item.severity, 4),
        item.code,
        item.path or "",
    ))
    return RepoGateReport(
        schema_version=SCHEMA_VERSION,
        gate_id=GATE_ID,
        repository=TARGET_REPOSITORY,
        status=gate_state,
        change_allowed=allowed,
        changed_paths=normalized,
        exempt_paths=tuple(buckets["GATE_EXEMPT"]),
        production_refresh_paths=tuple(buckets["FROZEN_PRODUCTION_REFRESH"]),
        research_paths=tuple(buckets["RESEARCH"]),
        unclassified_paths=tuple(buckets["UNCLASSIFIED"]),
        authorization_hash=authorization_hash,
        findings=tuple(findings),
        automatic_actions_taken=(),
    )


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--changed-files", required=True, type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_repository_gate(
        load_json(args.status),
        read_changed_files(args.changed_files),
        load_json(args.authorization) if args.authorization else None,
        parse_utc(args.as_of) if args.as_of else None,
    )
    if args.output:
        atomic_write_json(args.output, report.to_mapping())
    print(json.dumps({
        "status": report.status,
        "change_allowed": report.change_allowed,
        "research_paths": list(report.research_paths),
        "production_refresh_paths": list(report.production_refresh_paths),
        "unclassified_paths": list(report.unclassified_paths),
        "finding_count": len(report.findings),
        "automatic_actions_taken": [],
    }, sort_keys=True))
    if not report.change_allowed:
        raise SystemExit(10)


if __name__ == "__main__":
    try:
        main()
    except (RepoGateError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({
            "status": "REPOSITORY_RESEARCH_HOLD",
            "reason": str(exc),
        }, sort_keys=True))
        raise SystemExit(10)
