# Stock project research hold

The Stock Strategy Lab is currently in `HOLD_REMEDIATION_ONLY` state.

Before any Work-data acquisition, historical backtest, feature construction, challenger development, or validation begins, verify the authoritative gate in:

- repository: `nb788/stock-lab-runtime`
- branch: `main`
- path: `PROJECT_RESEARCH_RESUME_GATE.json`

The local `PROJECT_RESEARCH_RESUME_GATE_POINTER.json` is a fail-closed mirror. If the authoritative gate is unavailable, inconsistent, or lacks a valid reviewed unlock record, this repository remains on HOLD.

Restored Work-data capacity is not authorization to resume. Every resumed job must record the authoritative gate commit and file SHA-256 in its immutable run artifact.

While held, work is limited to remediation, integrity testing, adapter implementation, documentation, and preregistration that does not consume validation evidence. The gate does not create a fourth scheduled task; it is closed through the existing Weekly Engineering Review.
