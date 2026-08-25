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
if not UA: raise SystemExit('SEC_USER_AGENT required')
HEAD={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}
FORMS={'10-Q','10-K','20-F','40-F'}

def get(url,sec=True):
    r=requests.get(url,headers=(HEAD if sec else {'User-Agent':'Mozilla/5.0'}),timeout=120)
    r.raise_for_status(); return r.content

def cik(x): return str(x).replace('.0','').strip().zfill(10)
def sym(x): return str(x).upper().replace('-','.').strip()

def class_letter(s):
    m=re.search(r'class\s*([abc])',str(s or ''),re.I)
    return m.group(1).upper() if m else None

def generic_common(s):
    parts=[p.strip() for p in str(s or '').split('|') if p.strip()]
    return any(p.split(':')[-1].lower()=='commonstockmember' for p in parts)

def listing_names():
    rows=[]
    for url,kind in [(NASDAQ_LISTED,'NASDAQ'),(OTHER_LISTED,'OTHER')]:
        txt=get(url,False).decode('utf-8','replace'); lines=[z for z in txt.splitlines() if z and not z.startswith('File Creation Time')]
        if not lines: continue
        hdr=lines[0].split('|')
        for ln in lines[1:]:
            p=ln.split('|')
            if len(p)!=len(hdr): continue
            d=dict(zip(hdr,p)); s=d.get('Symbol') if kind=='NASDAQ' else d.get('ACT Symbol'); n=d.get('Security Name')
            if s and n: rows.append({'symbol_norm':sym(s),'listing_security_name':n,'listing_source':kind})
    return pd.DataFrame(rows).drop_duplicates('symbol_norm')

def submission_rows(obj,c):
    r=obj.get('filings',{}).get('recent',{}); out=[]
    if not isinstance(r,dict): return out
    n=len(r.get('accessionNumber',[]))
    for i in range(n):
        def v(k):
            a=r.get(k,[]); return a[i] if i<len(a) else None
        out.append({'cik':c,'accn':v('accessionNumber'),'form':v('form'),'filing_date':v('filingDate'),'acceptance_datetime':v('acceptanceDateTime'),'primary_document':v('primaryDocument')})
    return out

def latest_filings(sub_bytes,current_ciks):
    out=[]
    with zipfile.ZipFile(io.BytesIO(sub_bytes)) as z:
        names=set(z.namelist())
        for c in sorted(current_ciks):
            n=f'CIK{c}.json'
            if n not in names: continue
            df=pd.DataFrame(submission_rows(json.loads(z.read(n)),c))
            if df.empty: continue
            df=df[df.form.isin(FORMS)].copy()
            if df.empty: continue
            df['adt']=pd.to_datetime(df.acceptance_datetime,errors='coerce',utc=True)
            out.extend(df.sort_values(['adt','filing_date']).tail(1).drop(columns='adt').to_dict('records'))
    return pd.DataFrame(out)

def numeric(tag):
    txt=re.sub(r'[^0-9.\-()]','',tag.get_text(' ',strip=True).replace(',','').replace('$',''))
    if not txt: return None
    neg=txt.startswith('(') and txt.endswith(')'); txt=txt.strip('()')
    try: v=float(txt)
    except: return None
    try: v*=10**int(tag.attrs.get('scale') or tag.attrs.get('Scale') or '0')
    except: pass
    if (tag.attrs.get('sign') or tag.attrs.get('Sign'))=='-' or neg: v=-abs(v)
    return v

def parse(html,c,acc):
    soup=BeautifulSoup(html,'lxml'); out=[]
    for tag in soup.find_all(True):
        if not str(tag.attrs.get('name','')).lower().endswith('entitycommonstocksharesoutstanding'): continue
        v=numeric(tag)
        if v is None or v<=0: continue
        cr=tag.attrs.get('contextref') or tag.attrs.get('contextRef'); ctx=soup.find(id=cr) if cr else None
        instant=None; members=[]
        if ctx:
            for ch in ctx.find_all(True):
                ln=ch.name.lower() if ch.name else ''
                if ln.endswith('instant'): instant=ch.get_text(' ',strip=True)
                if ln.endswith('explicitmember') or ln.endswith('typedmember'): members.append(ch.get_text(' ',strip=True))
        mem='|'.join(sorted(set(members)))
        out.append({'cik':c,'accn':acc,'fact_date':instant,'shares':v,'dimension_members':mem,'class_letter':class_letter(mem),'generic_common_member':generic_common(mem),'context_ref':cr})
    return pd.DataFrame(out).drop_duplicates() if out else pd.DataFrame()

def expected(symbol,index_name,listing_name):
    for s in (index_name,listing_name):
        c=class_letter(s)
        if c: return c
    m=re.search(r'\.([A-Z])$',str(symbol).upper()); return m.group(1) if m else None

def main():
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str}); cur['cik']=cur.cik.map(cik); cur['symbol_norm']=cur.symbol.map(sym)
    ln=listing_names(); cur=cur.merge(ln,on='symbol_norm',how='left')
    sub=get(SEC_SUB,True); filings=latest_filings(sub,set(cur.cik)); filings.to_csv(DATA/'qa_all_current_latest_filings.csv',index=False)
    facts=[]; fails=[]
    for _,r in filings.iterrows():
        c=r.cik; acc=str(r.accn); doc=str(r.primary_document)
        if not acc or not doc or doc=='nan': continue
        url=f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-','')}/{doc}"
        try:
            pf=parse(get(url,True),c,acc)
            if len(pf):
                pf['acceptance_datetime']=r.acceptance_datetime; pf['form']=r.form; pf['filing_url']=url; facts.append(pf)
        except Exception as e: fails.append({'cik':c,'symbol':'|'.join(cur[cur.cik.eq(c)].symbol.tolist()),'url':url,'error':repr(e)})
        time.sleep(0.11)
    f=pd.concat(facts,ignore_index=True) if facts else pd.DataFrame(); f.to_csv(DATA/'qa_all_current_filing_dei_facts.csv',index=False); pd.DataFrame(fails).to_csv(DATA/'qa_all_current_fetch_failures.csv',index=False)
    symbols_by_cik=cur.groupby('cik').symbol.apply(list).to_dict(); rows=[]
    for _,r in cur.iterrows():
        cf=f[f.cik.eq(r.cik)].copy() if len(f) else pd.DataFrame(); status='UNRESOLVED'; shares=None; fd=None; mem=None; reason='NO_LATEST_FILING_DEI'
        if len(cf):
            cf['dt']=pd.to_datetime(cf.fact_date,errors='coerce'); mx=cf.dt.max(); cf=cf[cf.dt.eq(mx)] if pd.notna(mx) else cf
            ex=expected(r.symbol,r['name'],r.get('listing_security_name')); syms=symbols_by_cik.get(r.cik,[])
            if ex:
                z=cf[cf.class_letter.eq(ex)]; vals=z.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_CLASS_MATCH'; shares=float(vals[0]); fd=str(mx.date()) if pd.notna(mx) else None; mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str)))); reason=f'CLASS_{ex}_OFFICIAL_IDENTITY_MATCH'
                else: reason=f'NO_UNIQUE_CLASS_{ex}_MATCH'
            if status=='UNRESOLVED' and len(syms)==1 and isinstance(r.get('listing_security_name'),str) and 'common stock' in r.listing_security_name.lower():
                z=cf[cf.generic_common_member.eq(True)]; vals=z.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_EXACT_GENERIC_COMMON'; shares=float(vals[0]); fd=str(mx.date()) if pd.notna(mx) else None; mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str)))); reason='OFFICIAL_LISTING_COMMON_STOCK_PLUS_EXACT_COMMONSTOCKMEMBER'
            if status=='UNRESOLVED' and len(syms)==1:
                vals=cf.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_ONE_VALUE'; shares=float(vals[0]); fd=str(mx.date()) if pd.notna(mx) else None; mem='|'.join(sorted(set(cf.dimension_members.fillna('').astype(str)))); reason='ONE_CURRENT_TICKER_ONE_LATEST_DEI_VALUE'
                elif reason=='NO_LATEST_FILING_DEI': reason='MULTIPLE_LATEST_DEI_VALUES'
        rows.append({'symbol':r.symbol,'cik':r.cik,'name':r['name'],'listing_security_name':r.get('listing_security_name'),'status':status,'shares':shares,'fact_date':fd,'dimension_members':mem,'reason':reason})
    res=pd.DataFrame(rows); res.to_csv(DATA/'qa_all_current_resolution.csv',index=False)
    total=len(res); solved=int(res.status.str.startswith('RESOLVED').sum()); unresolved=total-solved
    summary={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'current_constituent_rows':int(total),'unique_current_ciks':int(cur.cik.nunique()),'latest_filings_found':int(len(filings)),'fetch_failures':int(len(fails)),'filing_dei_fact_rows':int(len(f)),'resolved_rows':solved,'resolved_pct':round(100*solved/total,4) if total else None,'unresolved_rows':unresolved,'rule':'All-current filing-level DEI audit. Explicit class identity > exact generic CommonStockMember > one-current-ticker/one-value. No guessing.'}
    (DATA/'qa_all_current_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
