#!/usr/bin/env python3
from __future__ import annotations
import io, os, re, json, time, zipfile, requests, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup

DATA=Path('data')
SEC_SUB='https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip'
NASDAQ_LISTED='https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt'
OTHER_LISTED='https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'
UA=os.environ.get('SEC_USER_AGENT','').strip()
if not UA:
    raise SystemExit('SEC_USER_AGENT required')
HEAD={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}
FORMS={'10-Q','10-K','20-F','40-F'}


def get(url,sec=True):
    h=HEAD if sec else {'User-Agent':'Mozilla/5.0'}
    r=requests.get(url,headers=h,timeout=120)
    r.raise_for_status()
    return r.content


def norm_cik(x): return str(x).replace('.0','').strip().zfill(10)

def norm_symbol(s): return str(s).upper().replace('-','.').strip()


def listing_security_names():
    rows=[]
    for url,kind in [(NASDAQ_LISTED,'NASDAQ'),(OTHER_LISTED,'OTHER')]:
        txt=get(url,sec=False).decode('utf-8','replace')
        lines=[ln for ln in txt.splitlines() if ln and not ln.startswith('File Creation Time')]
        if not lines: continue
        header=lines[0].split('|')
        for ln in lines[1:]:
            parts=ln.split('|')
            if len(parts)!=len(header): continue
            d=dict(zip(header,parts))
            if kind=='NASDAQ':
                sym=d.get('Symbol'); name=d.get('Security Name')
            else:
                sym=d.get('ACT Symbol'); name=d.get('Security Name')
            if sym and name: rows.append({'symbol':norm_symbol(sym),'listing_security_name':name,'listing_source':kind})
    out=pd.DataFrame(rows).drop_duplicates('symbol') if rows else pd.DataFrame(columns=['symbol','listing_security_name','listing_source'])
    out.to_csv(DATA/'qa_listing_security_names.csv',index=False)
    return out


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
            df=pd.DataFrame(rows_from_submission(obj,cik))
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
    try: val*=10**int(tag.attrs.get('scale') or tag.attrs.get('Scale') or '0')
    except Exception: pass
    if (tag.attrs.get('sign') or tag.attrs.get('Sign'))=='-': val=-abs(val)
    if neg: val=-abs(val)
    return val


def class_letter(s):
    if not s: return None
    m=re.search(r'class\s*([abc])',str(s),re.I)
    return m.group(1).upper() if m else None


def expected_class(symbol,index_name,listing_name):
    for s in (index_name,listing_name):
        c=class_letter(s)
        if c: return c
    m=re.search(r'\.([A-Z])$',str(symbol).upper())
    return m.group(1) if m else None


def is_generic_common_member(s):
    t=str(s or '').lower()
    return ('commonstockmember' in t and 'class' not in t) or t.endswith(':commonstockmember')


def parse_filing(html,cik,accn,symbols):
    soup=BeautifulSoup(html,'lxml')
    facts=[]
    for tag in soup.find_all(True):
        nm=str(tag.attrs.get('name',''))
        if not nm.lower().endswith('entitycommonstocksharesoutstanding'): continue
        val=numeric_fact(tag)
        if val is None or val<=0: continue
        cref=tag.attrs.get('contextref') or tag.attrs.get('contextRef')
        context=soup.find(id=cref) if cref else None
        instant=None; members=[]
        if context:
            for child in context.find_all(True):
                lname=child.name.lower() if child.name else ''
                if lname.endswith('instant'): instant=child.get_text(' ',strip=True)
                if lname.endswith('explicitmember') or lname.endswith('typedmember'):
                    members.append(child.get_text(' ',strip=True))
        member='|'.join(sorted(set(members)))
        facts.append({'cik':cik,'accn':accn,'context_ref':cref,'fact_date':instant,'shares':val,
                      'dimension_members':member,'class_letter':class_letter(member),
                      'generic_common_member':is_generic_common_member(member),
                      'symbols_for_cik':'|'.join(symbols)})
    return pd.DataFrame(facts).drop_duplicates() if facts else pd.DataFrame()


def main():
    exc=pd.read_csv(DATA/'qa_current_exceptions.csv',dtype={'cik':str})
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str})
    exc['cik']=exc['cik'].map(norm_cik); cur['cik']=cur['cik'].map(norm_cik)
    cur['symbol_norm']=cur['symbol'].map(norm_symbol); exc['symbol_norm']=exc['symbol'].map(norm_symbol)
    listings=listing_security_names()
    exc=exc.merge(listings,left_on='symbol_norm',right_on='symbol',how='left',suffixes=('','_listing')).drop(columns=['symbol_listing'],errors='ignore')
    target=set(exc['cik'])
    sub=get(SEC_SUB,sec=True)
    filings=latest_filings(sub,target)
    filings.to_csv(DATA/'qa_current_exception_latest_filings.csv',index=False)
    allfacts=[]; fetch_fail=[]
    symbol_map=cur.groupby('cik')['symbol'].apply(list).to_dict()
    for _,r in filings.iterrows():
        cik=r['cik']; accn=str(r['accn']); doc=str(r['primaryDocument'])
        if not accn or not doc or doc=='nan': continue
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-','')}/{doc}"
        try:
            pf=parse_filing(get(url,sec=True),cik,accn,symbol_map.get(cik,[]))
            if len(pf):
                pf['filing_url']=url; pf['form']=r['form']; pf['acceptance_datetime']=r['acceptanceDateTime']; allfacts.append(pf)
        except Exception as e: fetch_fail.append({'cik':cik,'accn':accn,'url':url,'error':repr(e)})
        time.sleep(0.15)
    facts=pd.concat(allfacts,ignore_index=True) if allfacts else pd.DataFrame()
    facts.to_csv(DATA/'qa_current_filing_dei_facts.csv',index=False)
    pd.DataFrame(fetch_fail).to_csv(DATA/'qa_current_filing_fetch_failures.csv',index=False)

    resolved=[]
    for _,row in exc.iterrows():
        symbol=row['symbol']; cik=row['cik']; name=row['name']; listing=row.get('listing_security_name')
        cf=facts[facts['cik'].eq(cik)].copy() if len(facts) else pd.DataFrame()
        status='UNRESOLVED'; shares=None; fact_date=None; member=None; reason='NO_FILING_DEI_FACT'
        if len(cf):
            cf['fact_dt']=pd.to_datetime(cf['fact_date'],errors='coerce')
            maxdt=cf['fact_dt'].max()
            if pd.notna(maxdt): cf=cf[cf['fact_dt'].eq(maxdt)]
            exp=expected_class(symbol,name,listing)
            symbols=symbol_map.get(cik,[])
            if exp:
                mf=cf[cf['class_letter'].eq(exp)]
                vals=mf['shares'].dropna().unique()
                if len(vals)==1:
                    status='RESOLVED_CLASS_MATCH'; shares=float(vals[0]); reason=f'CLASS_{exp}_OFFICIAL_LISTING_OR_INDEX_MATCH'
                    fact_date=str(maxdt.date()) if pd.notna(maxdt) else None
                    member='|'.join(sorted(set(mf['dimension_members'].fillna('').astype(str))))
                else: reason=f'NO_UNIQUE_CLASS_{exp}_MATCH'
            if status=='UNRESOLVED' and len(symbols)==1 and listing and 'common stock' in str(listing).lower():
                mf=cf[cf['generic_common_member'].eq(True)]
                vals=mf['shares'].dropna().unique()
                if len(vals)==1:
                    status='RESOLVED_GENERIC_LISTED_COMMON'; shares=float(vals[0]); reason='OFFICIAL_LISTING_COMMON_STOCK_MATCHES_GENERIC_COMMON_MEMBER'
                    fact_date=str(maxdt.date()) if pd.notna(maxdt) else None
                    member='|'.join(sorted(set(mf['dimension_members'].fillna('').astype(str))))
            if status=='UNRESOLVED' and len(symbols)==1:
                vals=cf['shares'].dropna().unique()
                if len(vals)==1:
                    status='RESOLVED_SINGLE_SYMBOL'; shares=float(vals[0]); reason='ONE_CURRENT_TICKER_ONE_LATEST_DEI_VALUE'
                    fact_date=str(maxdt.date()) if pd.notna(maxdt) else None
                    member='|'.join(sorted(set(cf['dimension_members'].fillna('').astype(str))))
                elif reason=='NO_FILING_DEI_FACT': reason='MULTIPLE_LATEST_DEI_VALUES_SINGLE_TICKER'
            elif status=='UNRESOLVED' and len(symbols)>1 and not exp:
                reason='MULTI_TICKER_CIK_WITHOUT_DETERMINISTIC_CLASS_LABEL'
        resolved.append({'symbol':symbol,'cik':cik,'name':name,'listing_security_name':listing,
                         'bulk_has_dei':bool(row.get('has_unambiguous_dei',False)),'bulk_fact_age_days':row.get('fact_age_days'),
                         'fallback_status':status,'fallback_shares':shares,'fallback_fact_date':fact_date,
                         'dimension_members':member,'reason':reason})
    res=pd.DataFrame(resolved)
    res.to_csv(DATA/'qa_current_filing_resolution.csv',index=False)
    summary={
      'audited_at_utc':datetime.now(timezone.utc).isoformat(),'exception_symbols':int(len(exc)),
      'exception_ciks':int(len(target)),'latest_filings_found':int(len(filings)),'filing_fetch_failures':int(len(fetch_fail)),
      'filing_dei_fact_rows':int(len(facts)),'filing_dei_fact_ciks':int(facts['cik'].nunique()) if len(facts) else 0,
      'listing_name_matches_found':int(exc['listing_security_name'].notna().sum()),
      'resolved_exception_symbols':int(res['fallback_status'].str.startswith('RESOLVED').sum()),
      'unresolved_exception_symbols':int((~res['fallback_status'].str.startswith('RESOLVED')).sum()),
      'rule':'Filing-level DEI fallback + official listing security-name class identity. Resolution requires explicit class match, generic-listed-common match, or one-current-ticker/one-value. No guessing.'
    }
    (DATA/'qa_current_filing_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
