# Stock Strategy Project — Current Research-Resume Gate

**Architecture:** `STOCK-STRATEGY-LAB-OVERARCHING-v2.7`  
**Gate:** `STOCK-PROJECT-PREWORK-GATE-v1`  
**Current state:** `BLOCKED_PREWORK`  
**Effective across:** every stock-project chat, backup chat, Work session, historical-research process, data-acquisition process, challenger workflow, holdout decision, and promotion decision.

## Mandatory project-wide rule

No stock-project chat or Work session may resume historical research, acquire research data, run a new backtest, search indicators, tune a challenger, start a prospective challenger, open a holdout, or recommend model promotion until the authoritative private gate reports `OPEN`.

While the gate is blocked, work is limited to remediation, testing, canonical-state import, broker reconciliation, orchestration reconciliation, documentation, and gate maintenance.

The return of Work data does **not** itself open the gate. The first action after access returns is to record the available Work allowance, source coverage, provider quotas, and recovery reserve; then rerun the complete prework gate. Only an `OPEN` result permits the first frozen Work packet to begin.

## Exact scheduled architecture

The project retains exactly three scheduled components:

1. `OPENING_RUN`
2. `CLOSING_RUN`
3. `WEEKLY_ENGINEERING_REVIEW`

The learning and structured-assurance review belongs inside Weekly Engineering Review or its approved CI invocation. It is not a fourth scheduled task.

## Current evidence update

A GET-only paper-account reconciliation completed on **September 2, 2026 at 23:02:30 UTC** after the complete repository suite passed 140 tests. The sanitized report found:

- zero managed entries;
- zero managed exits;
- zero open orders;
- zero positions;
- no findings;
- no order, cancellation, modification, or automatic-action authority.

This clears the broker-state evidence prerequisite. It does **not** activate the corrected execution contract or open the research gate.

Evidence identifiers:

- workflow run: `33693193940`;
- report payload SHA-256: `d7b7599723933a74ce3c6608a5a87eb36468ae171237a77e3df124df00af98d3`;
- report file SHA-256: `30b41d50fbc8f4e70fdca079892dd7656cb18b15b5e49b1aacc5de5bd4230c20`.

## Prerequisite state

Passed:

- fail-closed execution-contract transition installed;
- research learning and structured-assurance controls merged;
- broker state reconciled through read-only evidence;
- Work-data-return packets frozen;
- project-wide bridge directive published.

Still required before research resumes:

- latest canonical project state and append-only ledgers imported and hash-validated;
- real source-to-claim dependency graph populated;
- independent external learning-ledger witness configured;
- exact identities, schedules, destinations, active states, and authority boundaries pinned for the three scheduled tasks;
- strict assurance invocation bound to the existing Weekly Engineering Review;
- remaining combined regression, deterministic replay, and required fault evidence completed;
- seed registries imported through governed ledger writes after source-reference resolution;
- restored Work-data and provider quotas recorded.

## Authority boundary

Opening the research gate will not open a holdout, promote a model, alter the frozen `v1.0-STMM` control, activate a paper-execution transition, or authorize an order. Each of those remains separately governed.

## Source of truth

The authoritative machine-readable gate remains:

`nb788/stock-lab-runtime/research_only/project_resume_gate_v1.json`

This public file is a shared cross-chat mirror. Any mismatch must be resolved in favor of the authoritative private gate, and the mirror must then be updated.