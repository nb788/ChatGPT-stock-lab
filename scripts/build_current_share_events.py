#!/usr/bin/env python3
from __future__ import annotations
import io, os, re, json, time, zipfile, requests, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup

DATA=Path('data'); SEC_SUB='https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip'
NASDAQ_LISTED='https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt'; OTHER_LISTED='https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'
UA=os.environ.get('SEC_USER_AGENT','').strip()
if not UA: raise SystemExit('SEC_USER_AGENT required')
HEAD={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}; FORMS={'10-Q','10-K','20-F','40-F'}; ASOF=pd.Timestamp.now(tz='UTC')

def get(url,sec=True):
    r=requests.get(url,headers=(HEAD if sec else {'User-Agent':'Mozilla/5.0'}),timeout=120); r.raise_for_status(); return r.content

def ncik(x): return str(x).replace('.0','').strip().zfill(10)
def nsym(x): return str(x).upper().replace('-','.').strip()
def class_letter(s):
    m=re.search(r'class\s*([abc])',str(s or ''),re.I); return m.group(1).upper() if m else None

def generic_common(s):
    return any(p.split(':')[-1].lower()=='commonstockmember' for p in [q.strip() for q in str(s or '').split('|') if q.strip()])

def listings():
    rows=[]
    for url,kind in [(NASDAQ_LISTED,'NASDAQ'),(OTHER_LISTED,'OTHER')]:
        lines=[x for x in get(url,False).decode('utf-8','replace').splitlines() if x and not x.startswith('File Creation Time')]
        if not lines: continue
        hdr=lines[0].split('|')
        for ln in lines[1:]:
            p=ln.split('|')
            if len(p)!=len(hdr): continue
            d=dict(zip(hdr,p)); s=d.get('Symbol') if kind=='NASDAQ' else d.get('ACT Symbol'); n=d.get('Security Name')
            if s and n: rows.append({'symbol_norm':nsym(s),'listing_security_name':n,'listing_source':kind})
    return pd.DataFrame(rows).drop_duplicates('symbol_norm')

def subrows(obj,c):
    r=obj.get('filings',{}).get('recent',{}); out=[]
    if not isinstance(r,dict): return out
    for i,a in enumerate(r.get('accessionNumber',[])):
        def v(k): z=r.get(k,[]); return z[i] if i<len(z) else None
        out.append({'cik':c,'accn':a,'form':v('form'),'filing_date':v('filingDate'),'acceptance_datetime':v('acceptanceDateTime'),'primary_document':v('primaryDocument')})
    return out

def recent_filings(sub_bytes,ciks,n_per_cik=2):
    out=[]; quarantined=[]
    with zipfile.ZipFile(io.BytesIO(sub_bytes)) as z:
        names=set(z.namelist())
        for c in sorted(ciks):
            fn=f'CIK{c}.json'
            if fn not in names: continue
            df=pd.DataFrame(subrows(json.loads(z.read(fn)),c))
            if df.empty: continue
            df=df[df.form.isin(FORMS)].copy(); df['adt']=pd.to_datetime(df.acceptance_datetime,errors='coerce',utc=True)
            bad=df[df.adt.isna() | (df.adt>ASOF)]
            if len(bad): quarantined.extend(bad.drop(columns='adt').to_dict('records'))
            df=df[df.adt.notna() & (df.adt<=ASOF)].sort_values('adt').tail(n_per_cik)
            out.extend(df.drop(columns='adt').to_dict('records'))
    return pd.DataFrame(out),pd.DataFrame(quarantined)

def numeric(tag):
    t=re.sub(r'[^0-9.\-()]','',tag.get_text(' ',strip=True).replace(',','').replace('$',''))
    if not t: return None
    neg=t.startswith('(') and t.endswith(')'); t=t.strip('()')
    try: v=float(t)
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
        cr=tag.attrs.get('contextref') or tag.attrs.get('contextRef'); ctx=soup.find(id=cr) if cr else None; instant=None; members=[]
        if ctx:
            for ch in ctx.find_all(True):
                ln=str(ch.name or '').lower()
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
    cur=pd.read_csv(DATA/'sp500_current_source.csv',dtype={'cik':str}); cur['cik']=cur.cik.map(ncik); cur['symbol_norm']=cur.symbol.map(nsym); cur=cur.merge(listings(),on='symbol_norm',how='left')
    filings,qfil=recent_filings(get(SEC_SUB,True),set(cur.cik)); filings.to_csv(DATA/'sec_current_share_event_filings.csv',index=False); qfil.to_csv(DATA/'qa_share_event_filings_quarantined.csv',index=False)
    facts=[]; fails=[]
    for _,r in filings.iterrows():
        url=f"https://www.sec.gov/Archives/edgar/data/{int(r.cik)}/{str(r.accn).replace('-','')}/{r.primary_document}"
        try:
            pf=parse(get(url,True),r.cik,r.accn)
            if len(pf): pf['acceptance_datetime']=r.acceptance_datetime; pf['form']=r.form; pf['filing_url']=url; facts.append(pf)
        except Exception as e: fails.append({'cik':r.cik,'accn':r.accn,'url':url,'error':repr(e)})
        time.sleep(0.08)
    f=pd.concat(facts,ignore_index=True) if facts else pd.DataFrame(); pd.DataFrame(fails).to_csv(DATA/'qa_share_event_fetch_failures.csv',index=False)
    if len(f):
        f['acceptance_ts']=pd.to_datetime(f.acceptance_datetime,errors='coerce',utc=True); f['fact_dt']=pd.to_datetime(f.fact_date,errors='coerce',utc=True)
        bad=f[f.fact_dt.isna() | (f.fact_dt>ASOF) | (f.acceptance_ts.isna()) | (f.acceptance_ts>ASOF) | (f.fact_dt.dt.normalize()>f.acceptance_ts.dt.normalize())].copy(); f=f.drop(bad.index)
    else: bad=pd.DataFrame()
    bad.to_csv(DATA/'qa_share_event_facts_quarantined.csv',index=False)
    bycik=cur.groupby('cik').symbol.apply(list).to_dict(); events=[]
    for _,r in cur.iterrows():
        cf=f[f.cik.eq(r.cik)].copy() if len(f) else pd.DataFrame(); exp=expected(r.symbol,r['name'],r.get('listing_security_name')); syms=bycik.get(r.cik,[])
        if not len(cf): continue
        for (acc,ats),g in cf.groupby(['accn','acceptance_datetime'],dropna=False):
            mx=g.fact_dt.max(); g=g[g.fact_dt.eq(mx)] if pd.notna(mx) else g; method=None; val=None; mem=None
            if exp:
                z=g[g.class_letter.eq(exp)]; vals=z.shares.dropna().unique()
                if len(vals)==1: method=f'CLASS_{exp}_OFFICIAL_IDENTITY'; val=float(vals[0]); mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str))))
            if val is None and len(syms)==1 and isinstance(r.get('listing_security_name'),str) and 'common stock' in r.listing_security_name.lower():
                z=g[g.generic_common_member.eq(True)]; vals=z.shares.dropna().unique()
                if len(vals)==1: method='EXACT_COMMONSTOCKMEMBER'; val=float(vals[0]); mem='|'.join(sorted(set(z.dimension_members.fillna('').astype(str))))
            if val is None and len(syms)==1:
                z=g[g.dimension_members.fillna('').astype(str).str.strip().eq('')]; vals=z.shares.dropna().unique()
                if len(vals)==1: method='ONE_CURRENT_TICKER_ONE_VALUE'; val=float(vals[0]); mem=''
            if val is not None: events.append({'symbol':r.symbol,'cik':r.cik,'acceptance_datetime':ats,'fact_date':str(mx.date()) if pd.notna(mx) else None,'shares_reported':val,'mapping_method':method,'dimension_members':mem,'accn':acc})
    ev=pd.DataFrame(events)
    if len(ev): ev['acceptance_ts']=pd.to_datetime(ev.acceptance_datetime,errors='coerce',utc=True); ev=ev.sort_values(['symbol','acceptance_ts','fact_date']).drop_duplicates(['symbol','acceptance_datetime','shares_reported','accn'])
    ev.drop(columns=['acceptance_ts'],errors='ignore').to_csv(DATA/'sec_current_share_events.csv',index=False)
    anchor_cut=ASOF-pd.Timedelta(days=45); cov=[]
    for _,r in cur.iterrows():
        z=ev[ev.symbol.eq(r.symbol)].copy() if len(ev) else pd.DataFrame(); ats=pd.to_datetime(z.acceptance_datetime,errors='coerce',utc=True) if len(z) else pd.Series([],dtype='datetime64[ns, UTC]')
        cov.append({'symbol':r.symbol,'cik':r.cik,'event_count':int(len(z)),'has_any_event':bool(len(z)),'has_anchor_before_45d':bool(len(z) and (ats<=anchor_cut).any()),'latest_acceptance':str(ats.max()) if len(z) else None})
    cv=pd.DataFrame(cov); cv.to_csv(DATA/'qa_share_event_coverage.csv',index=False)
    summary={'built_at_utc':datetime.now(timezone.utc).isoformat(),'asof_utc':ASOF.isoformat(),'current_rows':int(len(cur)),'periodic_filings_parsed':int(len(filings)),'filings_per_cik_target':2,'quarantined_filing_rows':int(len(qfil)),'fetch_failures':int(len(fails)),'raw_dei_facts_valid':int(len(f)),'quarantined_fact_rows':int(len(bad)),'mapped_share_events':int(len(ev)),'symbols_with_any_event':int(cv.has_any_event.sum()),'symbols_with_anchor_before_45d':int(cv.has_anchor_before_45d.sum()),'rule':'Events preserve acceptance time. Daily turnover as-of joins latest known same-class event; one-value fallback only for non-dimensional facts; then apply intervening splits. No backfill.'}
    (DATA/'qa_share_event_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
