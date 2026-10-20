#!/usr/bin/env python3
"""Audit changed data-repository workflows for Stock project-gate usage."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MARKER = re.compile(
    r"(?m)^\s*#\s*stock-project-activity:\s*([A-Z0-9_]+)\s*$"
)
ALLOWED_ACTIVITIES = {
    "REMEDIATION",
    "WEEKLY_ENGINEERING_REVIEW",
    "PRODUCTION_CLOSE_AND_OUTCOME_CAPTURE",
    "WORK_DATA_ACQUISITION_OR_COMPUTE",
    "HISTORICAL_RESEARCH_OR_BACKTESTING",
    "CHALLENGER_DEVELOPMENT",
    "VALIDATION_OR_HOLDOUT_ACCESS",
}
RESEARCH_ACTIVITIES = {
    "WORK_DATA_ACQUISITION_OR_COMPUTE",
    "HISTORICAL_RESEARCH_OR_BACKTESTING",
    "CHALLENGER_DEVELOPMENT",
    "VALIDATION_OR_HOLDOUT_ACCESS",
}
GUARDED_ENTRYPOINT = "scripts/run_guarded_stock_research.py"
ORDER_RELATED_TOKENS = {
    "opening_loo_order.py",
    "ALLOW_PAPER_ORDER_SUBMISSION",
    "paper-api.alpaca.markets/v2/orders",
}


class WorkflowAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    path: str


def audit_workflow_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    markers = MARKER.findall(text)
    if len(markers) != 1:
        return [
            Finding(
                "WORKFLOW_ACTIVITY_MARKER_COUNT_INVALID",
                "CRITICAL",
                f"Workflow must declare exactly one activity marker; found {len(markers)}.",
                path,
            )
        ]
    activity = markers[0]
    if activity not in ALLOWED_ACTIVITIES:
        return [
            Finding(
                "WORKFLOW_ACTIVITY_UNKNOWN",
                "CRITICAL",
                f"Workflow declares unknown Stock-project activity {activity!r}.",
                path,
            )
        ]

    if activity in RESEARCH_ACTIVITIES:
        if GUARDED_ENTRYPOINT not in text:
            findings.append(
                Finding(
                    "DATA_RESEARCH_WORKFLOW_BYPASSES_GATE",
                    "CRITICAL",
                    f"{activity} workflow must invoke {GUARDED_ENTRYPOINT}.",
                    path,
                )
            )
        if f"--activity {activity}" not in text and f'--activity "{activity}"' not in text:
            findings.append(
                Finding(
                    "DATA_RESEARCH_ACTIVITY_ARGUMENT_MISMATCH",
                    "CRITICAL",
                    f"Guarded entrypoint must be called with --activity {activity}.",
                    path,
                )
            )
        if "--authoritative-gate" not in text or "--expect-authoritative-sha256" not in text:
            findings.append(
                Finding(
                    "AUTHORITATIVE_GATE_PINNING_MISSING",
                    "CRITICAL",
                    "Research workflow must supply the authoritative gate copy and expected SHA-256.",
                    path,
                )
            )
    if activity == "VALIDATION_OR_HOLDOUT_ACCESS" and "READY_FOR_VALIDATION" not in text:
        findings.append(
            Finding(
                "VALIDATION_READINESS_STATE_UNSTATED",
                "HIGH",
                "Validation workflow should explicitly document READY_FOR_VALIDATION.",
                path,
            )
        )

    for token in sorted(ORDER_RELATED_TOKENS):
        if token in text:
            findings.append(
                Finding(
                    "ORDER_PATH_PROHIBITED_IN_DATA_REPOSITORY",
                    "CRITICAL",
                    f"Data repository workflow contains prohibited order-related token: {token}.",
                    path,
                )
            )
    return findings


def changed_workflows(base: str, head: str, root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base}...{head}",
            "--",
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise WorkflowAuditError(
            "Cannot resolve changed workflows: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())


def audit_paths(paths: Iterable[str], root: Path = ROOT) -> dict:
    findings: list[Finding] = []
    audited: list[str] = []
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.exists():
            continue
        audited.append(relative)
        findings.extend(
            audit_workflow_text(relative, path.read_text(encoding="utf-8"))
        )
    findings.sort(key=lambda item: (item.path, item.code))
    return {
        "status": "PASS" if not findings else "WORKFLOW_RESEARCH_GATE_HOLD",
        "classification": "PROJECT_GOVERNANCE_AUDIT",
        "production_impact": "NONE",
        "may_authorize_orders": False,
        "automatic_action_taken": False,
        "audited_workflows": audited,
        "findings": [asdict(item) for item in findings],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = audit_paths(
            changed_workflows(args.base, args.head, args.root),
            args.root,
        )
    except (WorkflowAuditError, OSError, ValueError) as exc:
        report = {
            "status": "WORKFLOW_RESEARCH_GATE_HOLD",
            "classification": "PROJECT_GOVERNANCE_AUDIT",
            "production_impact": "NONE",
            "may_authorize_orders": False,
            "automatic_action_taken": False,
            "audited_workflows": [],
            "findings": [
                {
                    "code": "WORKFLOW_RESEARCH_GATE_AUDIT_INVALID",
                    "severity": "CRITICAL",
                    "message": str(exc),
                    "path": "",
                }
            ],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(10)


if __name__ == "__main__":
    main()
