# Guarded historical Stock-research entrypoint

Every future historical-data, feature/label, backtesting, challenger, or validation command in this repository should run through:

```bash
python scripts/run_guarded_stock_research.py \
  --activity HISTORICAL_RESEARCH_OR_BACKTESTING \
  --authoritative-gate /path/to/PROJECT_RESEARCH_RESUME_GATE.json \
  --expect-authoritative-sha256 <64-hex-sha256> \
  --receipt runs/GATE-RECEIPT.json \
  -- python path/to/job.py
```

The authoritative gate lives in `nb788/stock-lab-runtime` on `main`. The launching environment must fetch an exact copy, calculate and pin its SHA-256, and preserve the runtime gate commit and file hash with the resulting job artifacts.

## Fail-closed rules

The command is not launched when:

- no authoritative gate copy is supplied for research;
- the expected SHA-256 is absent or wrong;
- the authoritative gate is malformed or held;
- one of the ten readiness prerequisites is not `PASS` while the gate claims readiness;
- validation is attempted under `READY_FOR_WORK_DATA` rather than `READY_FOR_VALIDATION`;
- the declared activity is not registered.

While the project state is `HOLD_REMEDIATION_ONLY`, only remediation and Weekly Engineering Review work may run. Restored Work-data capacity does not change this.

## Receipt

Every allowed or blocked attempt writes an atomic receipt containing:

- pointer SHA-256;
- authoritative gate SHA-256 and state;
- declared activity;
- reasons for the decision;
- command argument hash rather than raw arguments;
- start and completion timestamps;
- child exit code;
- available GitHub repository, commit, workflow, and run identifiers;
- SHA-256 over the receipt payload.

## Governance limit

This wrapper cannot infer the true meaning of arbitrary code or prevent a privileged actor from bypassing it. Knowingly mislabeling a command or bypassing the wrapper is a governance incident. The wrapper cannot authorize an order, alter production, unlock the project, or open a holdout by itself.
