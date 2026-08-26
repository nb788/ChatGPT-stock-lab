#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

DATA=Path('data'); RAW=DATA/'sec_sp500_share_facts.csv'; CURRENT=DATA/'sp500_current_source.csv'
def norm_cik(s): return str(s).replace('.0','').strip().zfill(10)

def main():
    x=pd.read_csv(RAW,dtype={'cik':str,'accn':str}); cur=pd.read_csv(CURRENT,dtype={'cik':str}); x['cik']=x.cik.map(norm_cik); cur['cik']=cur.cik.map(norm_cik)
    for c in ['filed','fact_end']: x[c]=pd.to_datetime(x[c],errors='coerce')
    x['acceptance_ts']=pd.to_datetime(x.acceptance_datetime,errors='coerce',utc=True); x['shares']=pd.to_numeric(x.shares,errors='coerce')
    unmapped=x[x.acceptance_ts.isna()].copy(); unmapped[['cik','entity_name','taxonomy','tag','fact_end','filed','shares','form','accn']].to_csv(DATA/'qa_unmapped_acceptance.csv',index=False)
    exact_dup_count=int(x.duplicated().sum()); dei=x[x.taxonomy.eq('dei')].copy(); grp_cols=['cik','accn','filed','fact_end']
    dei_conf=(dei.groupby(grp_cols,dropna=False).shares.agg(n_values='nunique',min_shares='min',max_shares='max',rows='size').reset_index()); dei_conf=dei_conf[dei_conf.n_values>1]; dei_conf.to_csv(DATA/'qa_dei_conflicts.csv',index=False)
    g=x[x.taxonomy.eq('us-gaap')].copy(); dvals=dei.groupby(grp_cols,dropna=False).shares.agg(list).reset_index(name='dei_values'); gvals=g.groupby(grp_cols,dropna=False).shares.agg(list).reset_index(name='gaap_values'); cross=dvals.merge(gvals,on=grp_cols,how='inner')
    def disagree(r): return not any(np.isclose(float(a),float(b),rtol=1e-9,atol=1.0) for a in r.dei_values for b in r.gaap_values)
    if len(cross):
        cross['disagree']=cross.apply(disagree,axis=1); gaap_conf=cross[cross.disagree].copy(); gaap_conf['dei_values']=gaap_conf.dei_values.map(lambda v:'|'.join(map(str,v))); gaap_conf['gaap_values']=gaap_conf.gaap_values.map(lambda v:'|'.join(map(str,v)))
    else: gaap_conf=cross.copy()
    gaap_conf.to_csv(DATA/'qa_dei_gaap_disagreements.csv',index=False)

    # Form-family diagnostic: do not infer validity from frequency. This exists to detect
    # systematic exclusions caused by a parser form whitelist.
    form_summary=(dei.assign(form=dei.form.fillna('MISSING').astype(str))
                  .groupby('form',dropna=False)
                  .agg(rows=('shares','size'),unique_ciks=('cik','nunique'),first_fact=('fact_end','min'),last_fact=('fact_end','max'))
                  .reset_index().sort_values(['rows','unique_ciks'],ascending=False))
    form_summary.to_csv(DATA/'qa_dei_form_distribution.csv',index=False)
    periodic={'10-Q','10-K','20-F','40-F'}
    nonperiodic=dei[~dei.form.fillna('').isin(periodic)].copy()
    recent_cut=pd.Timestamp.now(tz='UTC').tz_localize(None)-pd.Timedelta(days=550)
    recent_nonperiodic=nonperiodic[nonperiodic.fact_end.notna() & (nonperiodic.fact_end>=recent_cut)]

    ambiguous_ciks=set(dei_conf.cik.astype(str)); build_now_utc=pd.Timestamp.now(tz='UTC'); build_now_naive=build_now_utc.tz_localize(None)
    valid_dei=dei[(dei.acceptance_ts.notna())&(dei.acceptance_ts<=build_now_utc)&(dei.fact_end.notna())&(dei.fact_end<=build_now_naive)].copy(); valid_dei=valid_dei[~valid_dei.cik.isin(ambiguous_ciks)]
    latest=valid_dei.sort_values(['cik','acceptance_ts','fact_end']).groupby('cik',as_index=False).tail(1); latest=latest[['cik','entity_name','fact_end','filed','acceptance_datetime','shares','form','accn']]
    coverage=cur.merge(latest,on='cik',how='left'); coverage['has_unambiguous_dei']=coverage.shares.notna(); coverage['fact_age_days']=(build_now_naive-pd.to_datetime(coverage.fact_end,errors='coerce')).dt.days; coverage['stale_gt_180d']=coverage.fact_age_days>180; coverage.to_csv(DATA/'qa_current_coverage.csv',index=False)
    exceptions=coverage[(~coverage.has_unambiguous_dei)|coverage.stale_gt_180d].copy(); exceptions.to_csv(DATA/'qa_current_exceptions.csv',index=False)
    vals=coverage.loc[coverage.shares.notna(),'shares'].astype(float); q=vals.quantile([0,.001,.01,.5,.99,.999,1]).to_dict() if len(vals) else {}; first_fact=x.fact_end.min(); last_fact=x.fact_end.max(); current_count=len(cur); current_good=int(coverage.has_unambiguous_dei.sum()); current_stale=int(coverage.stale_gt_180d.fillna(False).sum()); current_ambiguous=int(cur.cik.isin(ambiguous_ciks).sum())
    fs={str(r.form):{'rows':int(r.rows),'unique_ciks':int(r.unique_ciks),'first_fact':None if pd.isna(r.first_fact) else str(r.first_fact.date()),'last_fact':None if pd.isna(r.last_fact) else str(r.last_fact.date())} for _,r in form_summary.head(20).iterrows()}
    summary={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'raw_rows':int(len(x)),'unique_ciks_in_raw':int(x.cik.nunique()),'first_fact_end':None if pd.isna(first_fact) else str(first_fact.date()),'last_fact_end':None if pd.isna(last_fact) else str(last_fact.date()),'acceptance_mapped_rows':int(x.acceptance_ts.notna().sum()),'acceptance_unmapped_rows':int(len(unmapped)),'exact_duplicate_rows':exact_dup_count,'dei_conflict_groups':int(len(dei_conf)),'dei_conflict_ciks':int(dei_conf.cik.nunique()) if len(dei_conf) else 0,'dei_gaap_disagreement_groups':int(len(gaap_conf)),'dei_gaap_disagreement_ciks':int(gaap_conf.cik.nunique()) if len(gaap_conf) else 0,'dei_form_top20':fs,'nonperiodic_dei_rows':int(len(nonperiodic)),'nonperiodic_dei_unique_ciks':int(nonperiodic.cik.nunique()),'recent_550d_nonperiodic_dei_rows':int(len(recent_nonperiodic)),'recent_550d_nonperiodic_dei_unique_ciks':int(recent_nonperiodic.cik.nunique()),'current_constituent_rows':int(current_count),'current_unambiguous_dei_coverage_count':current_good,'current_unambiguous_dei_coverage_pct':round(100*current_good/current_count,4) if current_count else None,'current_multi_value_ambiguity_count':current_ambiguous,'current_stale_gt_180d_count':current_stale,'latest_current_share_value_quantiles':{str(k):float(v) for k,v in q.items()},'hard_interpretation':'QA only. Form counts diagnose whitelist selection risk; they do not make non-periodic facts valid automatically. Production validity still requires class identity, timing, split propagation and lineage reconciliation.'}
    (DATA/'qa_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
