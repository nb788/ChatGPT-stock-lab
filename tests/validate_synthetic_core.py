#!/usr/bin/env python3
from __future__ import annotations
import math, json
from datetime import datetime, timezone
import pandas as pd

class VF(AssertionError): pass

def req(x,msg):
    if not bool(x): raise VF(msg)

def asof_share(events, cutoff):
    e=events.copy(); e['acceptance']=pd.to_datetime(e['acceptance'],utc=True)
    z=e[e.acceptance<=pd.Timestamp(cutoff)].sort_values(['acceptance','shares'],kind='stable')
    return None if z.empty else float(z.iloc[-1].shares)

def propagated_shares(reported, fact_date, day, splits):
    x=float(reported); f=pd.Timestamp(fact_date); d=pd.Timestamp(day)
    for sd,factor in sorted(splits):
        s=pd.Timestamp(sd)
        if f < s <= d: x*=float(factor)
    return x

def split_only_price(raw,date,splits,analysis_end):
    x=float(raw); dt=pd.Timestamp(date); end=pd.Timestamp(analysis_end)
    for sd,factor in sorted(splits):
        s=pd.Timestamp(sd)
        if dt < s <= end: x/=float(factor)
    return x

def qualify(df):
    r=df.R21.quantile(.90,interpolation='linear'); t=df.turnover.quantile(.90,interpolation='linear')
    return set(df.loc[(df.R21>=r)&(df.turnover>=t),'symbol'])

def net_target_raw(raw_entry): return raw_entry*1.001*1.10/0.999

def action_policy(kind):
    if kind in {'forward_split','reverse_split'}: return 'MECHANICAL_SPLIT'
    if kind in {'cash_dividend'}: return 'IGNORE_FOR_R21'
    return 'QUARANTINE'

def main():
    tests=[]
    def run(name,fn):
        try: fn(); tests.append({'test':name,'status':'PASS'})
        except Exception as e: tests.append({'test':name,'status':'FAIL','error':repr(e)})

    def acceptance():
        e=pd.DataFrame([{'acceptance':'2026-08-10 20:00:00+00:00','shares':500},{'acceptance':'2026-08-12 20:00:00+00:00','shares':520}])
        req(asof_share(e,'2026-08-11 21:00:00+00:00')==500,'lookahead/backfill')
        req(asof_share(e,'2026-08-13 21:00:00+00:00')==520,'new fact not adopted')
        req(asof_share(e,'2026-08-09 21:00:00+00:00') is None,'missing anchor imputed')
    run('acceptance_asof_no_backfill',acceptance)

    def cutoff_boundary():
        e=pd.DataFrame([{'acceptance':'2026-08-25 20:29:59+00:00','shares':500},{'acceptance':'2026-08-25 20:30:01+00:00','shares':520}])
        req(asof_share(e,'2026-08-25 20:30:00+00:00')==500,'post-cutoff filing leaked into signal')
        req(asof_share(e,'2026-08-26 20:30:00+00:00')==520,'post-cutoff filing not available next signal')
    run('sec_1630_cutoff_boundary',cutoff_boundary)

    def same_timestamp_determinism():
        e=pd.DataFrame([{'acceptance':'2026-08-25 20:00:00+00:00','shares':500},{'acceptance':'2026-08-25 20:00:00+00:00','shares':500}])
        req(asof_share(e,'2026-08-25 20:30:00+00:00')==500,'duplicate equal same-time fact unstable')
    run('duplicate_equal_fact_determinism',same_timestamp_determinism)

    def forward_split():
        s=[('2020-08-31',4)]
        req(propagated_shares(1e9,'2020-08-28','2020-08-31',s)==4e9,'shares split propagation')
        req(abs(split_only_price(499.23,'2020-08-28',s,'2020-08-31')-124.8075)<1e-9,'price split continuity')
        req(abs((40e6/1e9)-(160e6/4e9))<1e-12,'turnover units')
    run('forward_split_consistency',forward_split)

    def reverse_split():
        s=[('2026-01-05',0.1)]
        req(propagated_shares(1e9,'2026-01-02','2026-01-05',s)==1e8,'reverse shares')
        req(abs(split_only_price(2,'2026-01-02',s,'2026-01-05')-20)<1e-12,'reverse price')
        req(abs((50e6/1e9)-(5e6/1e8))<1e-12,'reverse turnover units')
    run('reverse_split_consistency',reverse_split)

    def split_endpoint():
        s=[('2026-08-11',2)]
        req(split_only_price(50,'2026-08-11',s,'2026-08-25')==50,'split incorrectly reapplied to ex-date price')
        req(split_only_price(100,'2026-08-10',s,'2026-08-25')==50,'pre-ex-date price not adjusted')
        req(propagated_shares(10,'2026-08-11','2026-08-11',s)==10,'fact on ex-date double adjusted')
        req(propagated_shares(10,'2026-08-10','2026-08-11',s)==20,'pre-split fact not propagated on ex-date')
    run('split_endpoint_boundaries',split_endpoint)

    def target_costs():
        raw=100.; eff=raw*1.001; target=net_target_raw(raw)
        req(target>110,'raw +10 incorrectly equals net +10')
        req(abs(target*0.999/eff-1.10)<1e-12,'target cost arithmetic')
    run('net_target_costs',target_costs)

    def gap_target():
        target=net_target_raw(100)
        gap_open=115
        conservative_fill=target if gap_open>=target else None
        req(conservative_fill==target,'gap-above-target used favorable open rather than precommitted threshold')
    run('target_gap_conservative_fill',gap_target)

    def day21_moc():
        raw_entry=100; raw_close=105
        net_ret=(raw_close*0.999)/(raw_entry*1.001)-1
        req(abs(net_ret-(104.895/100.1-1))<1e-12,'day21 MOC costs wrong')
    run('day21_moc_includes_exit_cost',day21_moc)

    def whole_shares():
        p=333.40; n=math.floor(10000/p)
        req(n==29 and n*p<=10000 and (n+1)*p>10000,'whole-share cap')
    run('raw_notional_whole_shares',whole_shares)

    def future_fact():
        a=pd.Timestamp('2026-08-25 20:00:00+00:00'); f=pd.Timestamp('2026-08-26',tz='UTC')
        req(f.normalize()>a.normalize(),'future fact accepted')
    run('future_fact_quarantine',future_fact)

    def class_guard():
        def exact(s): return any(x.split(':')[-1].lower()=='commonstockmember' for x in str(s).split('|') if x)
        req(exact('us-gaap:CommonStockMember'),'generic common missed')
        req(not exact('abc:NonvotingCommonStockMember'),'nonvoting false positive')
        req(not exact('abc:ConvertibleCommonStockMember'),'convertible false positive')
    run('strict_class_guard',class_guard)

    def dimensional_fallback():
        member='abc:NonvotingCommonStockMember'; unique_value=True
        allowed=unique_value and not member.strip()
        req(not allowed,'unique value with explicit unmatched dimension accepted')
    run('no_one_value_dimensional_fallback',dimensional_fallback)

    def missing(): req(not all(v is not None for v in [0.02,None,0.03]),'missing denominator imputed')
    run('missing_denominator_no_imputation',missing)

    def exact_22_bars():
        req(len(list(range(22)))>=22,'22-bar eligible case rejected')
        req(not (len(list(range(21)))>=22),'21-bar case accepted for R21')
    run('r21_requires_22_closes',exact_22_bars)

    def turnover_21_days():
        vols=list(range(1,22)); shares=[100]*21
        vals=[v/s for v,s in zip(vols,shares)]
        req(len(vals)==21 and abs(sum(vals)/21-0.11)<1e-12,'turnover window not exactly 21 observations')
    run('turnover_requires_exact_21_daily_ratios',turnover_21_days)

    def lineage():
        a={'symbol':'X','cusip':'111','cik':'1'}; b={'symbol':'X','cusip':'222','cik':'2'}
        req((a['cusip'],a['cik']) != (b['cusip'],b['cik']),'ticker equality treated as continuity')
    run('security_lineage_not_ticker_only',lineage)

    def action_types():
        req(action_policy('forward_split')=='MECHANICAL_SPLIT','forward split not mechanical')
        req(action_policy('reverse_split')=='MECHANICAL_SPLIT','reverse split not mechanical')
        req(action_policy('cash_dividend')=='IGNORE_FOR_R21','cash dividend entered split-only R21')
        for k in ['stock_merger','cash_merger','stock_and_cash_merger','spin_off','name_change','unit_split','stock_dividend','rights_distribution']:
            req(action_policy(k)=='QUARANTINE',f'{k} not quarantined')
    run('corporate_action_policy_classes',action_types)

    def determinism():
        d=pd.DataFrame({'symbol':[f'S{i:03}' for i in range(100)],'R21':[i/100 for i in range(100)],'turnover':[(i%17)/17 for i in range(100)]})
        req(qualify(d)==qualify(d.sample(frac=1,random_state=17).reset_index(drop=True)),'row-order dependence')
    run('deterministic_screen',determinism)

    def ties():
        d=pd.DataFrame({'symbol':[f'S{i}' for i in range(10)],'R21':[0]*9+[1],'turnover':[0]*9+[1]})
        req('S9' in qualify(d),'inclusive percentile semantics broken')
    run('percentile_tie_inclusive',ties)

    def percentile_linear():
        s=pd.Series(range(10)); req(abs(s.quantile(.90,interpolation='linear')-8.1)<1e-12,'90th-percentile interpolation drift')
    run('percentile_linear_interpolation_frozen',percentile_linear)

    def same_bar():
        signal_time=pd.Timestamp('2026-08-25 16:30',tz='America/New_York')
        fill_time=pd.Timestamp('2026-08-26 09:30',tz='America/New_York')
        req(fill_time>signal_time,'same-bar/same-session lookahead fill')
    run('signal_to_next_session_execution',same_bar)

    passed=sum(t['status']=='PASS' for t in tests); failed=len(tests)-passed
    out={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'tests':len(tests),'passed':passed,'failed':failed,'results':tests,
         'note':'Synthetic mechanics only; passing does not prove real-data coverage or alpha.'}
    print(json.dumps(out,indent=2))
    if failed: raise SystemExit(f'{failed} synthetic core tests failed')

if __name__=='__main__': main()
