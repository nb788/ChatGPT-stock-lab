# Stock Strategy Project-Wide Prework Enforcement

**Architecture:** `STOCK-STRATEGY-LAB-OVERARCHING-v2.7`  
**Authoritative private gate:** `STOCK-PROJECT-PREWORK-GATE-v1`  
**Current public mirror state:** `BLOCKED_PREWORK`  
**Applies to:** every chat, backup chat, Work session, historical-research process, data-acquisition process, challenger process, and AI or human acting within the Stock Strategy project.

## Mandatory start-of-work rule

Before any stock-project process acquires research data, runs or extends a backtest, searches indicators, tunes a challenger, opens a holdout, interprets new historical outcomes, or advances a model, it must:

1. Read the authoritative private gate when available and this conservative public mirror otherwise.
2. Confirm the architecture ID and gate ID.
3. Confirm the gate result is exactly `OPEN` and supported by current evidence.
4. Confirm restored Work-data allowance and provider quotas were recorded.
5. Confirm the requested action is not separately blocked by holdout, production, execution, or paper-trading governance.

A missing, stale, contradictory, unreadable, or non-`OPEN` result means **stop**. It may not be treated as implicit permission.

## Current permitted work

While `BLOCKED_PREWORK`, work is limited to:

- remediation;
- testing and deterministic replay of existing contracts;
- canonical-state import and integrity checking;
- read-only broker reconciliation;
- orchestration reconciliation;
- documentation and evidence packaging;
- gate maintenance and conservative mirror updates.

## Current prohibited work

Until the authoritative private gate opens, do not perform:

- historical research or research-data acquisition;
- new or extended backtests;
- indicator searches or parameter sweeps;
- challenger fitting, tuning, or selection;
- prospective challenger operation;
- holdout access;
- model promotion.

This remains true even when Work capacity returns. Restored capacity is only one prerequisite; it does not open the project by itself.

## Scheduled architecture

The project retains exactly three scheduled components:

1. `OPENING_RUN`
2. `CLOSING_RUN`
3. `WEEKLY_ENGINEERING_REVIEW`

The learning and structured-assurance process belongs inside Weekly Engineering Review or non-scheduled CI. It is not a fourth scheduled task.

## Authority boundaries

This directive:

- does not authorize an order;
- does not activate or alter an execution contract;
- does not open a validation holdout;
- does not promote a model;
- does not permit automatic method adoption;
- does not change frozen production `v1.0-STMM`.

The public mirror may lag the private gate only in the conservative direction. It must never report a more permissive state than the authoritative private repository.
