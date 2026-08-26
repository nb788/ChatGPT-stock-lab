#!/usr/bin/env python3
from __future__ import annotations
import os, json, time, requests, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import build_current_share_events as base

DATA=Path('data')
UA=os.environ.get('SEC_USER_AGENT','').strip()
if not UA: raise SystemExit('SEC_USER_AGENT required')
HEAD={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}
FORMS=base.FORMS
ASOF=pd.Timestamp.now(tz='UTC')

def get_json(url):
    r=requests.get(url,headers=HEAD,timeout=60); r.raise_for_status(); return r.json()

def main():
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str}); cur['cik']=cur.cik.map(base.ncik); cur['symbol_norm']=cur.symbol.map(base.nsym)
    cur=cur.merge(base.listings(),on='symbol_norm',how='left')
    meta=json.loads((DATA/'build_metadata.json').read_text()); bulk=pd.Timestamp(meta['built_at_utc'])
    bulk=bulk.tz_localize('UTC') if bulk.tzinfo is None else bulk.tz_convert('UTC')
    bycik=cur.groupby('cik').symbol.apply(list).to_dict(); filings=[]; api_fail=[]
    for c in sorted(set(cur.cik)):
        try:
            obj=get_json(f'https://data.sec.gov/submissions/CIK{c}.json'); df=pd.DataFrame(base.subrows(obj,c))
            if len(df):
                df=df[df.form.isin(FORMS)].copy(); df['adt']=pd.to_datetime(df.acceptance_datetime,errors='coerce',utc=True)
                z=df[df.adt.notna() & (df.adt>bulk) & (df.adt<=ASOF)]
                if len(z): filings.extend(z.drop(columns='adt').to_dict('records'))
        except Exception as e: api_fail.append({'cik':c,'error':repr(e)})
        time.sleep(0.11)
    fd=pd.DataFrame(filings); fd.to_csv(DATA/'sec_live_delta_filings.csv',index=False); pd.DataFrame(api_fail).to_csv(DATA/'qa_live_delta_api_failures.csv',index=False)
    facts=[]; fetch_fail=[]
    for r in filings:
        c=r['cik']; acc=str(r['accn']); doc=str(r['primary_document']); url=f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-','')}/{doc}"
        try:
            pf=base.parse(base.get(url,True),c,acc)
            if len(pf): pf['acceptance_datetime']=r['acceptance_datetime']; pf['form']=r['form']; pf['filing_url']=url; facts.append(pf)
        except Exception as e: fetch_fail.append({'cik':c,'accn':acc,'url':url,'error':repr(e)})
        time.sleep(0.11)
    f=pd.concat(facts,ignore_index=True) if facts else pd.DataFrame(); pd.DataFrame(fetch_fail).to_csv(DATA/'qa_live_delta_fetch_failures.csv',index=False)
    if len(f):
        f['acceptance_ts']=pd.to_datetime(f.acceptance_datetime,errors='coerce',utc=True); f['fact_dt']=pd.to_datetime(f.fact_date,errors='coerce',utc=True)
        bad=f[f.fact_dt.isna() | f.acceptance_ts.isna() | (f.acceptance_ts>ASOF) | (f.fact_dt>ASOF) | (f.fact_dt.dt.normalize()>f.acceptance_ts.dt.normalize())].copy(); f=f.drop(bad.index)
    else: bad=pd.DataFrame()
    bad.to_csv(DATA/'qa_live_delta_facts_quarantined.csv',index=False)
    events=[]; unresolved_affected=[]
    for _,r in cur.iterrows():
        cf=f[f.cik.eq(r.cik)].copy() if len(f) else pd.DataFrame(); syms=bycik.get(r.cik,[]); exp=base.expected(r.symbol,r['name'],r.get('listing_security_name'))
        if not len(cf): continue
        for (acc,ats),g in cf.groupby(['accn','acceptance_datetime'],dropna=False):
            mx=g.fact_dt.max(); g=g[g.fact_dt.eq(mx)] if pd.notna(mx) else g; val=None; method=None; mem=None
            if exp:
                z=g[g.class_letter.eq(exp)]; vals=z.shares.dropna().unique()
                if len(vals)==1: val=float(vals[0]); method=f'CLASS_{exp}_OFFICIAL_IDENTITY'; mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str))))
            if val is None and len(syms)==1 and isinstance(r.get('listing_security_name'),str) and 'common stock' in r.listing_security_name.lower():
                z=g[g.generic_common_member.eq(True)]; vals=z.shares.dropna().unique()
                if len(vals)==1: val=float(vals[0]); method='EXACT_COMMONSTOCKMEMBER'; mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str))))
            if val is None and len(syms)==1:
                z=g[g.dimension_members.fillna('').astype(str).str.strip().eq('')]; vals=z.shares.dropna().unique()
                if len(vals)==1: val=float(vals[0]); method='ONE_CURRENT_TICKER_ONE_VALUE'; mem=''
            if val is not None: events.append({'symbol':r.symbol,'cik':r.cik,'acceptance_datetime':ats,'fact_date':str(mx.date()),'shares_reported':val,'mapping_method':method,'dimension_members':mem,'accn':acc,'source':'SEC_LIVE_DELTA'})
            else: unresolved_affected.append({'symbol':r.symbol,'cik':r.cik,'accn':acc,'acceptance_datetime':ats,'reason':'NEW_PERIODIC_FILING_HAS_NO_DETERMINISTIC_SAME_CLASS_SHARE_EVENT'})
    ev=pd.DataFrame(events); ev.to_csv(DATA/'sec_live_share_events.csv',index=False); pd.DataFrame(unresolved_affected).to_csv(DATA/'qa_live_delta_unresolved_affected.csv',index=False)
    affected=sorted(set(fd.cik.astype(str))) if len(fd) else []
    summary={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'bulk_built_at_utc':bulk.isoformat(),'current_ciks_checked':int(cur.cik.nunique()),'api_failures':int(len(api_fail)),'new_periodic_filings_since_bulk':int(len(fd)),'affected_ciks':affected,'filing_fetch_failures':int(len(fetch_fail)),'quarantined_fact_rows':int(len(bad)),'mapped_live_share_events':int(len(ev)),'unresolved_affected_events':int(len(unresolved_affected)),'production_rule':'Combine valid live events with nightly history by acceptance time. New affected filings without deterministic same-class mapping make affected ticker ineligible.'}
    (DATA/'qa_live_delta_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
    if api_fail: raise SystemExit('Live SEC freshness incomplete: API failures present')
    if fetch_fail: raise SystemExit('Live SEC freshness incomplete: new filing fetch failures present')

if __name__=='__main__': main()
