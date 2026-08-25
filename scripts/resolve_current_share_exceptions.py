#!/usr/bin/env python3
from __future__ import annotations
import io, os, re, json, time, zipfile, requests, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup

DATA=Path('data')
SEC_SUB='https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip'
UA=os.environ.get('SEC_USER_AGENT','').strip()
if not UA:
    raise SystemExit('SEC_USER_AGENT required')
HEAD={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}
FORMS={'10-Q','10-K','20-F','40-F'}


def get(url):
    r=requests.get(url,headers=HEAD,timeout=120)
    r.raise_for_status()
    return r.content


def norm_cik(x): return str(x).replace('.0','').strip().zfill(10)


def rows_from_submission(obj,cik):
    out=[]
    recent=obj.get('filings',{}).get('recent',{})
    if not isinstance(recent,dict): return out
    acc=recent.get('accessionNumber',[])
    for i,a in enumerate(acc):
        def v(k):
            arr=recent.get(k,[])
            return arr[i] if i < len(arr) else None
        out.append({'cik':cik,'accn':a,'form':v('form'),'filingDate':v('filingDate'),
                    'acceptanceDateTime':v('acceptanceDateTime'),'primaryDocument':v('primaryDocument')})
    return out


def latest_filings(sub_bytes,ciks):
    out=[]
    with zipfile.ZipFile(io.BytesIO(sub_bytes)) as z:
        names=set(z.namelist())
        for cik in sorted(ciks):
            name=f'CIK{cik}.json'
            if name not in names: continue
            obj=json.loads(z.read(name))
            rows=rows_from_submission(obj,cik)
            # recent is sufficient for current-period filings; use latest base periodic filing.
            df=pd.DataFrame(rows)
            if df.empty: continue
            df=df[df['form'].isin(FORMS)].copy()
            if df.empty: continue
            df['adt']=pd.to_datetime(df['acceptanceDateTime'],errors='coerce',utc=True)
            df=df.sort_values(['adt','filingDate']).tail(1)
            out.extend(df.drop(columns=['adt']).to_dict('records'))
    return pd.DataFrame(out)


def numeric_fact(tag):
    txt=tag.get_text(' ',strip=True).replace(',','').replace('$','').strip()
    txt=re.sub(r'[^0-9.\-()]','',txt)
    if not txt: return None
    neg=txt.startswith('(') and txt.endswith(')')
    txt=txt.strip('()')
    try: val=float(txt)
    except Exception: return None
    scale=tag.attrs.get('scale') or tag.attrs.get('Scale') or '0'
    try: val*=10**int(scale)
    except Exception: pass
    sign=tag.attrs.get('sign') or tag.attrs.get('Sign')
    if sign=='-': val=-abs(val)
    if neg: val=-abs(val)
    return val


def class_letter(s):
    if not s: return None
    t=str(s)
    m=re.search(r'class\s*([abc])',t,re.I)
    return m.group(1).upper() if m else None


def expected_class(symbol,name):
    c=class_letter(name)
    if c: return c
    m=re.search(r'\.([A-Z])$',str(symbol).upper())
    return m.group(1) if m else None


def parse_filing(html,cik,accn,symbols):
    soup=BeautifulSoup(html,'lxml')
    facts=[]
    for tag in soup.find_all(True):
        nm=str(tag.attrs.get('name',''))
        if not nm.lower().endswith('entitycommonstocksharesoutstanding'):
            continue
        val=numeric_fact(tag)
        if val is None or val<=0: continue
        cref=tag.attrs.get('contextref') or tag.attrs.get('contextRef')
        context=soup.find(id=cref) if cref else None
        instant=None; members=[]
        if context:
            for child in context.find_all(True):
                lname=child.name.lower() if child.name else ''
                if lname.endswith('instant'):
                    instant=child.get_text(' ',strip=True)
                if lname.endswith('explicitmember') or lname.endswith('typedmember'):
                    members.append(child.get_text(' ',strip=True))
        member='|'.join(sorted(set(members)))
        facts.append({'cik':cik,'accn':accn,'context_ref':cref,'fact_date':instant,
                      'shares':val,'dimension_members':member,'class_letter':class_letter(member),
                      'symbols_for_cik':'|'.join(symbols)})
    if not facts: return pd.DataFrame()
    return pd.DataFrame(facts).drop_duplicates()


def main():
    exc=pd.read_csv(DATA/'qa_current_exceptions.csv',dtype={'cik':str})
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str})
    exc['cik']=exc['cik'].map(norm_cik); cur['cik']=cur['cik'].map(norm_cik)
    target=set(exc['cik'])
    sub=get(SEC_SUB)
    filings=latest_filings(sub,target)
    filings.to_csv(DATA/'qa_current_exception_latest_filings.csv',index=False)
    allfacts=[]; fetch_fail=[]
    symbol_map=cur.groupby('cik')['symbol'].apply(list).to_dict()
    for _,r in filings.iterrows():
        cik=r['cik']; accn=str(r['accn']); doc=str(r['primaryDocument'])
        if not accn or not doc or doc=='nan': continue
        accnodash=accn.replace('-','')
        url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accnodash}/{doc}'
        try:
            html=get(url)
            pf=parse_filing(html,cik,accn,symbol_map.get(cik,[]))
            if len(pf):
                pf['filing_url']=url
                pf['form']=r['form']; pf['acceptance_datetime']=r['acceptanceDateTime']
                allfacts.append(pf)
        except Exception as e:
            fetch_fail.append({'cik':cik,'accn':accn,'url':url,'error':repr(e)})
        time.sleep(0.15)
    facts=pd.concat(allfacts,ignore_index=True) if allfacts else pd.DataFrame()
    facts.to_csv(DATA/'qa_current_filing_dei_facts.csv',index=False)
    pd.DataFrame(fetch_fail).to_csv(DATA/'qa_current_filing_fetch_failures.csv',index=False)

    # Conservative ticker-level resolution. Only exact latest filing DEI facts are used.
    resolved=[]
    for _,row in exc.iterrows():
        symbol=row['symbol']; cik=row['cik']; name=row['name']
        cf=facts[facts['cik'].eq(cik)].copy() if len(facts) else pd.DataFrame()
        status='UNRESOLVED'; shares=None; fact_date=None; member=None; reason='NO_FILING_DEI_FACT'
        if len(cf):
            cf['fact_dt']=pd.to_datetime(cf['fact_date'],errors='coerce')
            maxdt=cf['fact_dt'].max()
            if pd.notna(maxdt): cf=cf[cf['fact_dt'].eq(maxdt)]
            exp=expected_class(symbol,name)
            symbols=symbol_map.get(cik,[])
            if len(symbols)==1:
                vals=cf['shares'].dropna().unique()
                if len(vals)==1:
                    status='RESOLVED_SINGLE_SYMBOL'; shares=float(vals[0]); reason='ONE_CURRENT_TICKER_ONE_LATEST_DEI_VALUE'
                    fact_date=str(maxdt.date()) if pd.notna(maxdt) else None
                    member='|'.join(sorted(set(cf['dimension_members'].fillna('').astype(str))))
                else:
                    reason='MULTIPLE_LATEST_DEI_VALUES_SINGLE_TICKER'
            elif exp:
                mf=cf[cf['class_letter'].eq(exp)]
                vals=mf['shares'].dropna().unique()
                if len(vals)==1:
                    status='RESOLVED_CLASS_MATCH'; shares=float(vals[0]); reason=f'CLASS_{exp}_DIMENSION_MATCH'
                    fact_date=str(maxdt.date()) if pd.notna(maxdt) else None
                    member='|'.join(sorted(set(mf['dimension_members'].fillna('').astype(str))))
                else:
                    reason=f'NO_UNIQUE_CLASS_{exp}_MATCH'
            else:
                reason='MULTI_TICKER_CIK_WITHOUT_DETERMINISTIC_CLASS_LABEL'
        resolved.append({'symbol':symbol,'cik':cik,'name':name,'bulk_has_dei':bool(row.get('has_unambiguous_dei',False)),
                         'bulk_fact_age_days':row.get('fact_age_days'), 'fallback_status':status,
                         'fallback_shares':shares,'fallback_fact_date':fact_date,'dimension_members':member,'reason':reason})
    res=pd.DataFrame(resolved)
    res.to_csv(DATA/'qa_current_filing_resolution.csv',index=False)
    summary={
      'audited_at_utc':datetime.now(timezone.utc).isoformat(),
      'exception_symbols':int(len(exc)),
      'exception_ciks':int(len(target)),
      'latest_filings_found':int(len(filings)),
      'filing_fetch_failures':int(len(fetch_fail)),
      'filing_dei_fact_rows':int(len(facts)),
      'filing_dei_fact_ciks':int(facts['cik'].nunique()) if len(facts) else 0,
      'resolved_exception_symbols':int(res['fallback_status'].str.startswith('RESOLVED').sum()),
      'unresolved_exception_symbols':int((~res['fallback_status'].str.startswith('RESOLVED')).sum()),
      'rule':'Filing-level DEI fallback only; class mapping requires one-current-ticker/one-value or explicit class-letter dimension match. No guessing.'
    }
    (DATA/'qa_current_filing_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
