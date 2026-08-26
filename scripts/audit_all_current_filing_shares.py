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
ASOF=pd.Timestamp.now(tz='UTC')

def get(url,sec=True):
    r=requests.get(url,headers=(HEAD if sec else {'User-Agent':'Mozilla/5.0'}),timeout=120); r.raise_for_status(); return r.content

def cik(x): return str(x).replace('.0','').strip().zfill(10)
def sym(x): return str(x).upper().replace('-','.').strip()
def class_letter(s):
    m=re.search(r'class\s*([abc])',str(s or ''),re.I); return m.group(1).upper() if m else None

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
    out=[]; future=[]; unmapped=[]
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
            bad_na=df[df.adt.isna()]
            if len(bad_na): unmapped.extend(bad_na.drop(columns='adt').to_dict('records'))
            bad_future=df[df.adt.notna() & (df.adt>ASOF)]
            if len(bad_future): future.extend(bad_future.drop(columns='adt').to_dict('records'))
            df=df[df.adt.notna() & (df.adt<=ASOF)]
            if df.empty: continue
            out.extend(df.sort_values(['adt','filing_date']).tail(1).drop(columns='adt').to_dict('records'))
    return pd.DataFrame(out),pd.DataFrame(future),pd.DataFrame(unmapped)

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

def soup_for_doc(raw):
    head=bytes(raw[:1024]).lstrip().lower(); is_xml=head.startswith(b'<?xml') or b'<xbrl' in head or b'<xbrli:xbrl' in head
    return BeautifulSoup(raw,'xml' if is_xml else 'lxml'),is_xml

def is_dei_share_tag(tag):
    return str(tag.attrs.get('name','')).lower().endswith('entitycommonstocksharesoutstanding') or str(tag.name or '').lower().endswith('entitycommonstocksharesoutstanding')

def parse(html,c,acc):
    soup,_=soup_for_doc(html); out=[]
    for tag in soup.find_all(True):
        if not is_dei_share_tag(tag): continue
        v=numeric(tag)
        if v is None or v<=0: continue
        cr=tag.attrs.get('contextref') or tag.attrs.get('contextRef'); ctx=soup.find(id=cr) if cr else None
        instant=None; members=[]
        if ctx:
            for ch in ctx.find_all(True):
                ln=str(ch.name or '').lower()
                if ln.endswith('instant'): instant=ch.get_text(' ',strip=True)
                if ln.endswith('explicitmember') or ln.endswith('typedmember'): members.append(ch.get_text(' ',strip=True))
        mem='|'.join(sorted(set(members)))
        out.append({'cik':c,'accn':acc,'fact_date':instant,'shares':v,'dimension_members':mem,'class_letter':class_letter(mem),'generic_common_member':generic_common(mem),'context_ref':cr})
    return pd.DataFrame(out).drop_duplicates() if out else pd.DataFrame()

def expected(symbol,index_name,listing_name):
    # Official exchange listing identity outranks the derivative index label.
    for s in (listing_name,index_name):
        c=class_letter(s)
        if c: return c
    m=re.search(r'\.([A-Z])$',str(symbol).upper()); return m.group(1) if m else None

def main():
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str}); cur['cik']=cur.cik.map(cik); cur['symbol_norm']=cur.symbol.map(sym)
    cur=cur.merge(listing_names(),on='symbol_norm',how='left')
    filings,future_filings,unmapped_filings=latest_filings(get(SEC_SUB,True),set(cur.cik))
    filings.to_csv(DATA/'qa_all_current_latest_filings.csv',index=False); future_filings.to_csv(DATA/'qa_all_current_future_filings_quarantined.csv',index=False); unmapped_filings.to_csv(DATA/'qa_all_current_unmapped_filing_acceptance.csv',index=False)
    facts=[]; fails=[]
    for _,r in filings.iterrows():
        c=r.cik; acc=str(r.accn); doc=str(r.primary_document)
        if not acc or not doc or doc=='nan': continue
        url=f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-','')}/{doc}"
        try:
            pf=parse(get(url,True),c,acc)
            if len(pf): pf['acceptance_datetime']=r.acceptance_datetime; pf['form']=r.form; pf['filing_url']=url; facts.append(pf)
        except Exception as e: fails.append({'cik':c,'symbol':'|'.join(cur[cur.cik.eq(c)].symbol.tolist()),'url':url,'error':repr(e)})
        time.sleep(0.11)
    f=pd.concat(facts,ignore_index=True) if facts else pd.DataFrame(); pd.DataFrame(fails).to_csv(DATA/'qa_all_current_fetch_failures.csv',index=False)
    if len(f):
        f['fact_dt']=pd.to_datetime(f.fact_date,errors='coerce',utc=True); f['acceptance_ts']=pd.to_datetime(f.acceptance_datetime,errors='coerce',utc=True)
        f['future_vs_asof']=f.fact_dt.notna() & (f.fact_dt>ASOF); f['future_vs_acceptance_day']=f.fact_dt.notna() & f.acceptance_ts.notna() & (f.fact_dt.dt.normalize()>f.acceptance_ts.dt.normalize())
    else: f['future_vs_asof']=[]; f['future_vs_acceptance_day']=[]
    badfacts=f[f.future_vs_asof | f.future_vs_acceptance_day].copy() if len(f) else pd.DataFrame(); badfacts.to_csv(DATA/'qa_all_current_future_facts_quarantined.csv',index=False)
    validf=f[~(f.future_vs_asof | f.future_vs_acceptance_day)].copy() if len(f) else f; validf.to_csv(DATA/'qa_all_current_filing_dei_facts.csv',index=False)
    symbols_by_cik=cur.groupby('cik').symbol.apply(list).to_dict(); rows=[]
    for _,r in cur.iterrows():
        cf=validf[validf.cik.eq(r.cik)].copy() if len(validf) else pd.DataFrame(); status='UNRESOLVED'; shares=None; fd=None; mem=None; reason='NO_VALID_LATEST_FILING_DEI'
        if len(cf):
            mx=cf.fact_dt.max(); cf=cf[cf.fact_dt.eq(mx)] if pd.notna(mx) else cf; ex=expected(r.symbol,r['name'],r.get('listing_security_name')); syms=symbols_by_cik.get(r.cik,[])
            if ex:
                z=cf[cf.class_letter.eq(ex)]; vals=z.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_CLASS_MATCH'; shares=float(vals[0]); fd=str(mx.date()); mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str)))); reason=f'CLASS_{ex}_OFFICIAL_IDENTITY_MATCH'
                else: reason=f'NO_UNIQUE_CLASS_{ex}_MATCH'
            if status=='UNRESOLVED' and len(syms)==1 and isinstance(r.get('listing_security_name'),str) and 'common stock' in r.listing_security_name.lower():
                z=cf[cf.generic_common_member.eq(True)]; vals=z.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_EXACT_GENERIC_COMMON'; shares=float(vals[0]); fd=str(mx.date()); mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str)))); reason='OFFICIAL_LISTING_COMMON_STOCK_PLUS_EXACT_COMMONSTOCKMEMBER'
            if status=='UNRESOLVED' and len(syms)==1:
                z=cf[cf.dimension_members.fillna('').astype(str).str.strip().eq('')]; vals=z.shares.dropna().unique()
                if len(vals)==1: status='RESOLVED_ONE_VALUE'; shares=float(vals[0]); fd=str(mx.date()); mem=''; reason='ONE_CURRENT_TICKER_ONE_NON_DIMENSIONAL_LATEST_DEI_VALUE'
                elif reason=='NO_VALID_LATEST_FILING_DEI': reason='NO_UNIQUE_NON_DIMENSIONAL_LATEST_DEI_VALUE'
        rows.append({'symbol':r.symbol,'cik':r.cik,'name':r['name'],'listing_security_name':r.get('listing_security_name'),'status':status,'shares':shares,'fact_date':fd,'dimension_members':mem,'reason':reason})
    res=pd.DataFrame(rows); res.to_csv(DATA/'qa_all_current_resolution.csv',index=False)
    total=len(res); solved=int(res.status.str.startswith('RESOLVED').sum()); unresolved=total-solved
    summary={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'audit_asof_utc':ASOF.isoformat(),'current_constituent_rows':int(total),'unique_current_ciks':int(cur.cik.nunique()),'latest_filings_found':int(len(filings)),'future_periodic_filings_quarantined':int(len(future_filings)),'unmapped_periodic_filing_acceptance_quarantined':int(len(unmapped_filings)),'fetch_failures':int(len(fails)),'filing_dei_fact_rows_raw':int(len(f)),'future_or_post_acceptance_fact_rows_quarantined':int(len(badfacts)),'filing_dei_fact_rows_valid':int(len(validf)),'resolved_rows':solved,'resolved_pct':round(100*solved/total,4) if total else None,'unresolved_rows':unresolved,'rule':'Official exchange listing identity precedes derivative index labels; hard timing cutoffs; inline/native XML XBRL; explicit class > exact CommonStockMember > single-ticker unique NON-DIMENSIONAL value only. No guessing.'}
    (DATA/'qa_all_current_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
