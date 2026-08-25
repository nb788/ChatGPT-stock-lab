#!/usr/bin/env python3
from __future__ import annotations
import io, os, json, zipfile, requests, pandas as pd
from pathlib import Path
from datetime import datetime, timezone

SEC_CF = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SEC_SUB = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SP_HIST = "https://raw.githubusercontent.com/lawcal/sp500-components-history/main/data/components_history.csv"
SP_CUR = "https://raw.githubusercontent.com/lawcal/sp500-components-history/main/data/sp500_components.csv"
OUT = Path("data")
OUT.mkdir(exist_ok=True)
UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT environment variable is required.")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}

def fetch(url, sec=False):
    headers = HEADERS if sec else {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=240)
    r.raise_for_status()
    return r.content

def clean_date(x):
    if pd.isna(x): return None
    x = str(x).strip().rstrip("*")
    return x or None

def build_target_ciks():
    hist = pd.read_csv(io.BytesIO(fetch(SP_HIST)), dtype={"cik": str})
    cur = pd.read_csv(io.BytesIO(fetch(SP_CUR)), dtype={"cik": str})
    for df in (hist, cur):
        df["cik"] = df["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10)
    if "date_added" in hist: hist["date_added"] = hist["date_added"].map(clean_date)
    if "date_removed" in hist: hist["date_removed"] = hist["date_removed"].map(clean_date)
    hist.to_csv(OUT / "sp500_membership_history_source.csv", index=False)
    cur.to_csv(OUT / "sp500_current_source.csv", index=False)
    return sorted(set(hist["cik"].dropna()) | set(cur["cik"].dropna()))

def recent_rows(obj):
    recent = obj.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict): return []
    acc = recent.get("accessionNumber", [])
    out=[]
    for i, a in enumerate(acc):
        adt = recent.get("acceptanceDateTime", [])
        out.append((a, adt[i] if i < len(adt) else None))
    return out

def build_acceptance_map(sub_bytes, target_ciks):
    amap={}
    with zipfile.ZipFile(io.BytesIO(sub_bytes)) as z:
        names=set(z.namelist())
        for cik in target_ciks:
            main=f"CIK{cik}.json"
            if main not in names: continue
            obj=json.loads(z.read(main))
            for accn, adt in recent_rows(obj): amap[accn]=adt
            for f in obj.get("filings", {}).get("files", []) or []:
                name=f.get("name")
                if not name or name not in names: continue
                old=json.loads(z.read(name))
                if "accessionNumber" in old:
                    accs=old.get("accessionNumber", [])
                    adts=old.get("acceptanceDateTime", [])
                    for i, accn in enumerate(accs): amap[accn]=adts[i] if i < len(adts) else None
                else:
                    for accn, adt in recent_rows(old): amap[accn]=adt
    return amap

def extract(obj, taxonomy, tag):
    rows=[]
    fact=obj.get("facts", {}).get(taxonomy, {}).get(tag, {})
    for unit, arr in fact.get("units", {}).items():
        if unit.lower() not in ("shares", "share"): continue
        for v in arr:
            if v.get("val") is None: continue
            rows.append({"taxonomy":taxonomy,"tag":tag,"unit":unit,"fact_end":v.get("end"),
                         "filed":v.get("filed"),"shares":v.get("val"),"form":v.get("form"),
                         "accn":v.get("accn"),"fy":v.get("fy"),"fp":v.get("fp"),"frame":v.get("frame")})
    return rows

def build_share_rows(cf_bytes, target_ciks, amap):
    rows=[]
    with zipfile.ZipFile(io.BytesIO(cf_bytes)) as z:
        names=set(z.namelist())
        for cik in target_ciks:
            name=f"CIK{cik}.json"
            if name not in names: continue
            obj=json.loads(z.read(name)); entity=obj.get("entityName")
            facts=extract(obj,"dei","EntityCommonStockSharesOutstanding") + extract(obj,"us-gaap","CommonStockSharesOutstanding")
            for r in facts:
                r.update(cik=cik, entity_name=entity, acceptance_datetime=amap.get(r.get("accn")))
                rows.append(r)
    x=pd.DataFrame(rows)
    if x.empty: return x
    x["shares"]=pd.to_numeric(x["shares"], errors="coerce")
    x=x[x["shares"].notna() & (x["shares"] > 0)].drop_duplicates()
    cols=["cik","entity_name","taxonomy","tag","unit","fact_end","filed","acceptance_datetime","shares","form","accn","fy","fp","frame"]
    return x[cols].sort_values(["cik","filed","fact_end","taxonomy","shares"])

def main():
    ciks=build_target_ciks()
    cf=fetch(SEC_CF, sec=True)
    sub=fetch(SEC_SUB, sec=True)
    amap=build_acceptance_map(sub,ciks)
    shares=build_share_rows(cf,ciks,amap)
    shares.to_csv(OUT/"sec_sp500_share_facts.csv", index=False)
    if not shares.empty:
        filed=pd.to_datetime(shares["filed"], errors="coerce")
        cutoff=pd.Timestamp.now(tz="UTC").tz_localize(None)-pd.Timedelta(days=550)
        shares[filed >= cutoff].to_csv(OUT/"sec_sp500_share_facts_recent.csv", index=False)
    meta={"built_at_utc":datetime.now(timezone.utc).isoformat(),"source_companyfacts":SEC_CF,
          "source_submissions":SEC_SUB,"source_sp500_history":SP_HIST,"target_cik_count":len(ciks),
          "share_fact_rows":int(len(shares)),"acceptance_timestamp_mapped_count":int(shares["acceptance_datetime"].notna().sum()) if not shares.empty else 0,
          "rule":"Raw relevant facts only; no imputation, favorable conflict resolution, or share-class guessing."}
    (OUT/"build_metadata.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))

if __name__ == "__main__": main()
