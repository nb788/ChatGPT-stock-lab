# Cross-repository Stock Strategy research gate

This repository is a data and runtime-input surface for the same Stock Strategy project governed by `STOCK-PROJECT-RESEARCH-RESUMPTION-v1` in `nb788/stock-lab-runtime`.

The local state is currently `REMEDIATION_ONLY`.

## Enforcement

Pull requests are classified by changed path:

- `research_gate/**`, this hold, and the gate workflow are governance maintenance and may proceed;
- `data/**`, `runs/**`, `snapshots/**`, and `runtime_snapshot/**` are treated as frozen-production refresh candidates and require a narrow, current, hashed authorization manifest;
- research, backtest, experiment, model, challenger, validation, and holdout paths are blocked while the project gate is not READY;
- unclassified code or data changes fail closed.

Even after the project becomes READY, research changes require a current authorization bound to:

- the project gate report;
- canonical state revision;
- frozen work packet and packet set;
- run ID;
- maximum allowed conclusion;
- exact allowed paths;
- zero unauthorized holdout exposures;
- no signal, execution, or exit-rule change through this repository.

This guard does not authorize a trade or research conclusion. It prevents this repository from being used as a bypass around the project-wide gate.
