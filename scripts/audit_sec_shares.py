#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

DATA = Path("data")
RAW = DATA / "sec_sp500_share_facts.csv"
CURRENT = DATA / "sp500_current_source.csv"


def norm_cik(s):
    return str(s).replace(".0", "").strip().zfill(10)


def main():
    x = pd.read_csv(RAW, dtype={"cik": str, "accn": str})
    cur = pd.read_csv(CURRENT, dtype={"cik": str})
    x["cik"] = x["cik"].map(norm_cik)
    cur["cik"] = cur["cik"].map(norm_cik)
    for c in ["filed", "fact_end"]:
        x[c] = pd.to_datetime(x[c], errors="coerce")
    x["acceptance_ts"] = pd.to_datetime(x["acceptance_datetime"], errors="coerce")
    x["shares"] = pd.to_numeric(x["shares"], errors="coerce")

    # 1. Acceptance timestamp exceptions.
    unmapped = x[x["acceptance_ts"].isna()].copy()
    unmapped_cols = ["cik","entity_name","taxonomy","tag","fact_end","filed","shares","form","accn"]
    unmapped[unmapped_cols].to_csv(DATA / "qa_unmapped_acceptance.csv", index=False)

    # 2. Exact duplicate rows are harmless but should already have been removed.
    exact_dup_count = int(x.duplicated().sum())

    # 3. Conflicting DEI facts for same filing/accession + fact date.
    dei = x[x["taxonomy"].eq("dei")].copy()
    grp_cols = ["cik","accn","filed","fact_end"]
    dei_conf = (dei.groupby(grp_cols, dropna=False)["shares"]
                .agg(n_values="nunique", min_shares="min", max_shares="max", rows="size")
                .reset_index())
    dei_conf = dei_conf[dei_conf["n_values"] > 1].copy()
    dei_conf.to_csv(DATA / "qa_dei_conflicts.csv", index=False)

    # 4. DEI vs us-gaap exact-date/accession disagreements.
    g = x[x["taxonomy"].eq("us-gaap")].copy()
    dvals = dei.groupby(grp_cols, dropna=False)["shares"].agg(list).reset_index(name="dei_values")
    gvals = g.groupby(grp_cols, dropna=False)["shares"].agg(list).reset_index(name="gaap_values")
    cross = dvals.merge(gvals, on=grp_cols, how="inner")
    def disagree(r):
        return not any(np.isclose(float(a), float(b), rtol=1e-9, atol=1.0)
                       for a in r.dei_values for b in r.gaap_values)
    if len(cross):
        cross["disagree"] = cross.apply(disagree, axis=1)
        gaap_conf = cross[cross["disagree"]].copy()
        gaap_conf["dei_values"] = gaap_conf["dei_values"].map(lambda v: "|".join(map(str, v)))
        gaap_conf["gaap_values"] = gaap_conf["gaap_values"].map(lambda v: "|".join(map(str, v)))
    else:
        gaap_conf = cross.copy()
    gaap_conf.to_csv(DATA / "qa_dei_gaap_disagreements.csv", index=False)

    # 5. Multi-class ambiguity proxy. CompanyFacts does not expose dimensional
    # context in this flattened table, so multiple distinct DEI values for the
    # same accession/fact date are treated as an ambiguity flag, not resolved.
    ambiguous_ciks = set(dei_conf["cik"].astype(str))

    # 6. Current-universe point-in-time coverage as of build time, before any
    # split propagation. This is a source-availability test, not a production denominator.
    build_now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    valid_dei = dei[(dei["acceptance_ts"].notna()) &
                    (dei["acceptance_ts"] <= build_now) &
                    (dei["fact_end"].notna()) &
                    (dei["fact_end"] <= build_now)].copy()
    valid_dei = valid_dei[~valid_dei["cik"].isin(ambiguous_ciks)]
    latest = (valid_dei.sort_values(["cik","acceptance_ts","fact_end"])
              .groupby("cik", as_index=False).tail(1))
    latest = latest[["cik","entity_name","fact_end","filed","acceptance_datetime","shares","form","accn"]]
    coverage = cur.merge(latest, on="cik", how="left")
    coverage["has_unambiguous_dei"] = coverage["shares"].notna()
    coverage["fact_age_days"] = (build_now - pd.to_datetime(coverage["fact_end"], errors="coerce")).dt.days
    coverage["stale_gt_180d"] = coverage["fact_age_days"] > 180
    coverage.to_csv(DATA / "qa_current_coverage.csv", index=False)

    # Compact list of current-universe failures/risks for ChatGPT inspection.
    exceptions = coverage[(~coverage["has_unambiguous_dei"]) | coverage["stale_gt_180d"]].copy()
    exceptions.to_csv(DATA / "qa_current_exceptions.csv", index=False)

    # 7. Basic scale/outlier diagnostics on latest current values. Ratios are
    # intentionally descriptive only; no automatic correction is applied.
    vals = coverage.loc[coverage["shares"].notna(), "shares"].astype(float)
    q = vals.quantile([0,.001,.01,.5,.99,.999,1]).to_dict() if len(vals) else {}

    # 8. Form distribution and temporal coverage.
    first_fact = x["fact_end"].min()
    last_fact = x["fact_end"].max()
    current_count = int(len(cur))
    current_good = int(coverage["has_unambiguous_dei"].sum())
    current_stale = int(coverage["stale_gt_180d"].fillna(False).sum())
    current_ambiguous = int(cur["cik"].isin(ambiguous_ciks).sum())

    summary = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_rows": int(len(x)),
        "unique_ciks_in_raw": int(x["cik"].nunique()),
        "first_fact_end": None if pd.isna(first_fact) else str(first_fact.date()),
        "last_fact_end": None if pd.isna(last_fact) else str(last_fact.date()),
        "acceptance_mapped_rows": int(x["acceptance_ts"].notna().sum()),
        "acceptance_unmapped_rows": int(len(unmapped)),
        "exact_duplicate_rows": exact_dup_count,
        "dei_conflict_groups": int(len(dei_conf)),
        "dei_conflict_ciks": int(dei_conf["cik"].nunique()) if len(dei_conf) else 0,
        "dei_gaap_disagreement_groups": int(len(gaap_conf)),
        "dei_gaap_disagreement_ciks": int(gaap_conf["cik"].nunique()) if len(gaap_conf) else 0,
        "current_constituent_rows": current_count,
        "current_unambiguous_dei_coverage_count": current_good,
        "current_unambiguous_dei_coverage_pct": round(100*current_good/current_count, 4) if current_count else None,
        "current_multi_value_ambiguity_count": current_ambiguous,
        "current_stale_gt_180d_count": current_stale,
        "latest_current_share_value_quantiles": {str(k): float(v) for k,v in q.items()},
        "hard_interpretation": "QA only. Coverage does not make a denominator production-valid until share-class identity, split propagation, signal-cutoff timing, and corporate-action reconciliation pass."
    }
    (DATA / "qa_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
