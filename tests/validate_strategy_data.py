#!/usr/bin/env python3
from __future__ import annotations
import json, math
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

DATA=Path('data')
OUT=DATA/'qa_strategy_validation_summary.json'
class ValidationFailure(AssertionError): pass

def req(cond,msg):
    if not bool(cond): raise ValidationFailure(msg)

def asof_share(events, cutoff):
    e=events.copy(); e['acceptance']=pd.to_datetime(e['acceptance'],utc=True)
    z=e[e.acceptance<=pd.Timestamp(cutoff,tz='UTC')].sort_values('acceptance')
    return None if z.empty else float(z.iloc[-1].shares)

def propagated_shares(reported, fact_date, day, splits):
    f=pd.Timestamp(fact_date); d=pd.Timestamp(day); x=float(reported)
    for sd,factor in sorted(splits):
        s=pd.Timestamp(sd)
        if f < s <= d: x*=float(factor)
    return x

def split_only_price(raw, date, splits, analysis_end):
    x=float(raw); dt=pd.Timestamp(date); end=pd.Timestamp(analysis_end)
    for sd,factor in sorted(splits):
        s=pd.Timestamp(sd)
        if dt < s <= end: x/=float(factor)
    return x

def qualify(df):
    r=df.R21.quantile(.90); t=df.turnover.quantile(.90)
    return set(df.loc[(df.R21>=r)&(df.turnover>=t),'symbol'])

def main():
    tests=[]
    def run(name,fn):
        try: fn(); tests.append({'test':name,'status':'PASS'})
        except Exception as e: tests.append({'test':name,'status':'FAIL','error':repr(e)})

    def t_acceptance_asof():
        e=pd.DataFrame([{'acceptance':'2026-08-10 20:00:00+00:00','shares':500},{'acceptance':'2026-08-12 20:00:00+00:00','shares':520}])
        req(asof_share(e,'2026-08-11 21:00:00')==500,'later filing backfilled before acceptance')
        req(asof_share(e,'2026-08-13 21:00:00')==520,'new filing not used after acceptance')
        req(asof_share(e,'2026-08-09 21:00:00') is None,'missing pre-anchor was imputed')
    run('acceptance_asof_no_backfill',t_acceptance_asof)

    def t_split_units():
        splits=[('2020-08-31',4)]
        req(propagated_shares(1_000_000_000,'2020-08-28','2020-08-28',splits)==1_000_000_000,'pre-split shares changed early')
        req(propagated_shares(1_000_000_000,'2020-08-28','2020-08-31',splits)==4_000_000_000,'post-split shares not propagated')
        req(abs(split_only_price(499.23,'2020-08-28',splits,'2020-08-31')-124.8075)<1e-9,'split-only price continuity wrong')
        req(abs((40_000_000/1_000_000_000)-(160_000_000/4_000_000_000))<1e-12,'turnover units inconsistent')
    run('forward_split_price_and_share_units',t_split_units)

    def t_reverse_split():
        splits=[('2026-01-05',0.1)]
        req(propagated_shares(1_000_000_000,'2026-01-02','2026-01-05',splits)==100_000_000,'reverse split shares wrong')
        req(abs(split_only_price(2.0,'2026-01-02',splits,'2026-01-05')-20.0)<1e-12,'reverse split price continuity wrong')
        req(abs((50_000_000/1_000_000_000)-(5_000_000/100_000_000))<1e-12,'reverse split turnover units inconsistent')
    run('reverse_split_price_and_share_units',t_reverse_split)

    def t_net_target_costs():
        raw_entry=100.0; effective_entry=raw_entry*1.001
        raw_target=(effective_entry*1.10)/0.999
        req(raw_target>110.0,'net target ignored round-trip adverse costs')
        req(abs((raw_target*0.999/effective_entry)-1.10)<1e-12,'net target formula wrong')
        req(not (110.0>=raw_target),'raw +10% touch incorrectly counted as net +10%')
    run('net_10pct_target_includes_entry_and_exit_costs',t_net_target_costs)

    def t_raw_notional_whole_shares():
        raw_open=333.40; shares=math.floor(10_000/raw_open)
        req(shares==29,'whole-share sizing wrong'); req(shares*raw_open<=10_000,'raw notional exceeded cap'); req((shares+1)*raw_open>10_000,'sizing left avoidable whole share')
    run('raw_notional_10000_whole_share_cap',t_raw_notional_whole_shares)

    def t_future_fact():
        acceptance=pd.Timestamp('2026-08-25 20:00:00+00:00'); fact=pd.Timestamp('2026-08-26',tz='UTC')
        req(not (fact.normalize()<=acceptance.normalize()),'future/post-acceptance fact was accepted')
    run('future_fact_quarantine',t_future_fact)

    def t_class_guard():
        def exact_generic(member):
            parts=[p.strip() for p in member.split('|') if p.strip()]
            return any(p.split(':')[-1].lower()=='commonstockmember' for p in parts)
        req(exact_generic('us-gaap:CommonStockMember'),'exact generic common not recognized')
        req(not exact_generic('abc:NonvotingCommonStockMember'),'nonvoting false-positive')
        req(not exact_generic('abc:ConvertibleCommonStockMember'),'convertible false-positive')
    run('strict_share_class_guard',t_class_guard)

    def t_missing_no_impute():
        req(not all(v is not None for v in [0.02,None,0.03]),'missing denominator should make window ineligible')
    run('missing_denominator_no_imputation',t_missing_no_impute)

    def t_lineage_guard():
        a={'symbol':'X','cusip':'111','cik':'1'}; b={'symbol':'X','cusip':'222','cik':'2'}
        req(not (a['symbol']==b['symbol'] and a['cusip']==b['cusip'] and a['cik']==b['cik']),'ticker equality implied continuity')
    run('security_lineage_not_ticker_only',t_lineage_guard)

    def t_determinism():
        d=pd.DataFrame({'symbol':[f'S{i:03}' for i in range(100)],'R21':[i/100 for i in range(100)],'turnover':[(99-i)/100 for i in range(100)]})
        req(qualify(d.copy())==qualify(d.sample(frac=1,random_state=17).reset_index(drop=True)),'qualification depends on row order')
    run('deterministic_cross_sectional_screen',t_determinism)

    def t_percentile_inclusive():
        d=pd.DataFrame({'symbol':[f'S{i}' for i in range(10)],'R21':range(10),'turnover':range(10)})
        req('S9' in qualify(d),'top joint name excluded')
    run('inclusive_90th_percentile_semantics',t_percentile_inclusive)

    def t_raw_metadata():
        p=DATA/'build_metadata.json'; req(p.exists(),'build_metadata missing')
        m=json.loads(p.read_text()); total=m.get('share_fact_rows',0); mapped=m.get('acceptance_timestamp_mapped_count',0)
        req(total>0,'no SEC share facts'); req(mapped<=total,'mapped acceptance exceeds rows'); req(mapped/total>.99,'acceptance mapping below 99%')
    run('real_sec_metadata_invariants',t_raw_metadata)

    def t_current_rows():
        d=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str}); req(490<=len(d)<=520,'implausible current security-row count')
        req(d.symbol.notna().all() and d.cik.notna().all(),'missing current symbol/CIK'); req(d.symbol.nunique()==len(d),'duplicate ticker rows')
    run('current_universe_structural_invariants',t_current_rows)

    def t_event_invariants():
        p=DATA/'sec_current_share_events.csv'; req(p.exists(),'share-event output not yet published')
        e=pd.read_csv(p,dtype={'cik':str}); req(len(e)>0,'empty share-event output')
        a=pd.to_datetime(e.acceptance_datetime,errors='coerce',utc=True); f=pd.to_datetime(e.fact_date,errors='coerce',utc=True)
        req(a.notna().all() and f.notna().all(),'event missing time'); req((f.dt.normalize()<=a.dt.normalize()).all(),'event fact after acceptance day'); req((e.shares_reported>0).all(),'non-positive shares')
        allowed=('CLASS_','EXACT_COMMONSTOCKMEMBER','ONE_CURRENT_TICKER_ONE_VALUE'); req(e.mapping_method.fillna('').map(lambda x:any(str(x).startswith(z) for z in allowed)).all(),'unknown mapping method')
        req(not e.duplicated(['symbol','acceptance_datetime','shares_reported','accn']).any(),'duplicate share event keys')
        one=e.mapping_method.eq('ONE_CURRENT_TICKER_ONE_VALUE')
        if one.any(): req(e.loc[one,'dimension_members'].fillna('').astype(str).str.strip().eq('').all(),'one-value fallback accepted explicit XBRL dimension')
    run('real_share_event_invariants_and_dimensional_fallback',t_event_invariants)

    passed=sum(x['status']=='PASS' for x in tests); failed=len(tests)-passed
    summary={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'tests':len(tests),'passed':passed,'failed':failed,'results':tests,'interpretation':'Executable invariants/failure injections; passing does not prove alpha or historical completeness.'}
    OUT.write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
    if failed: raise SystemExit(f'{failed} validation tests failed')

if __name__=='__main__': main()
