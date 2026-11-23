#!/usr/bin/env python3
"""Public, read-only supplier availability and coupon-evidence audit.
No logins, carts, payments, code redemption, crawling or redistribution.
A 200 response is only reachability, NEVER coupon validity.
"""
import csv, io, json, re, time, html, socket, ipaddress, threading, collections
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

DATASETS = [
 ("sources_238", "URL", "Name", "Category"),
 ("docs_113", "Primary_document", "Source", "Type"),
 ("v4_15", "Source_URL", "Source", "Category"),
 ("coupon_119", "source_url", "store", "status_as_published"),
]
ROOT=Path(__file__).parent
OUT=ROOT/"reports"
OUT.mkdir(exist_ok=True)
AUDIT_TIME=datetime.now(timezone.utc).isoformat()
MAX_BYTES=350000
DELAY=1.3
TIMEOUT=9
HOST_LOCKS=collections.defaultdict(threading.Lock)
HOST_LAST=collections.defaultdict(float)
USER_AGENT="CouponSourceAudit/1.0 (+https://github.com/ashenthefox/coupon-source-audit-2026; read-only URL health check)"

def legal_url(url):
    try:
        p=urllib.parse.urlsplit(url.strip())
        if p.scheme not in ("https", "http"):return False,"UNSUPPORTED_SCHEME"
        if not p.hostname:return False,"MISSING_HOST"
        h=p.hostname.lower().strip(".")
        if h in ("localhost","localhost.localdomain") or h.endswith((".local",".internal",".localhost")):return False,"PRIVATE_HOST"
        try:
            ip=ipaddress.ip_address(h)
            if not ip.is_global:return False,"NONPUBLIC_IP"
        except ValueError:pass
        if p.username or p.password:return False,"CREDENTIALS_IN_URL"
        return True,""
    except Exception:return False,"MALFORMED_URL"

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok,why=legal_url(newurl)
        if not ok:raise ValueError("UNSAFE_REDIRECT:"+why)
        if urllib.parse.urlsplit(newurl).scheme!="https":
            raise ValueError("REDIRECT_NOT_HTTPS")
        return super().redirect_request(req,fp,code,msg,headers,newurl)

OPENER=urllib.request.build_opener(SafeRedirect())
def fetch_one(url):
    ok,why=legal_url(url)
    if not ok:return {"probe_status":why,"http_status":"","final_url":"","mime":"","bytes_read":0,"latency_ms":0,"title":"","xml_entries":"","json_records":"","error":why,"text":""}
    hostname=urllib.parse.urlsplit(url).hostname.lower()
    lock=HOST_LOCKS[hostname]
    with lock:
        wait=max(0,DELAY-(time.monotonic()-HOST_LAST[hostname]))
        if wait:time.sleep(wait)
        HOST_LAST[hostname]=time.monotonic()
    started=time.monotonic()
    req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/json,application/xml,application/rss+xml,application/atom+xml,text/plain;q=0.8,*/*;q=0.4"})
    code=0; mime=""; final=url; raw=b""; error=""
    try:
        with OPENER.open(req,timeout=TIMEOUT) as response:
            code=response.status
            mime=response.headers.get("Content-Type","").split(";")[0].lower()
            final=response.geturl()
            raw=response.read(MAX_BYTES+1)
    except urllib.error.HTTPError as ex:
        code=ex.code; error="HTTP "+str(code)
        mime=ex.headers.get("Content-Type","").split(";")[0].lower() if ex.headers else ""
        final=ex.geturl()
    except Exception as ex:
        error=type(ex).__name__+": "+str(ex)[:200]
    elapsed=int((time.monotonic()-started)*1000)
    if code in (401,403,407):status="AUTH_OR_ACCESS_RESTRICTED"
    elif code==429:status="RATE_LIMITED"
    elif 200<=code<300:status="PUBLIC_HTTP_OK"
    elif 300<=code<400:status="REDIRECT_UNRESOLVED"
    elif code==404:status="NOT_FOUND"
    elif code>=500:status="SERVER_ERROR"
    elif code>=400:status="HTTP_CLIENT_ERROR"
    elif error:status="NETWORK_OR_FETCH_ERROR"
    else:status="NO_RESPONSE"
    if len(raw)>MAX_BYTES: raw=raw[:MAX_BYTES]; truncated=True
    else: truncated=False
    txt=raw.decode("utf-8",errors="replace")
    title=""
    match=re.search(r"<title[^>]*>(.*?)</title\s*>",txt,re.I|re.S)
    if match:title=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>","",match.group(1)))).strip()[:160]
    entries=""; records=""
    if raw and ("xml" in mime or "rss" in mime or txt[:100].lstrip().startswith(("<?xml","<rss","<feed"))):
        try:
            root=ET.fromstring(raw)
            entries=len(root.findall(".//item"))+len(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
        except Exception:
            entries="XML_UNPARSEABLE_OR_TRUNCATED"
    if raw and ("json" in mime or txt.lstrip()[:1] in ("{","[")):
        try:
            obj=json.loads(txt)
            if isinstance(obj,list):records=len(obj)
            elif isinstance(obj,dict):
                records=max([len(x) for x in obj.values() if isinstance(x,list)]+[0])
        except Exception:records="JSON_UNPARSEABLE_OR_TRUNCATED"
    return {"probe_status":status,"http_status":code or "","final_url":final,"mime":mime,"bytes_read":len(raw),"latency_ms":elapsed,"title":title,"xml_entries":entries,"json_records":records,"error":error,"truncated":truncated,"text":txt}
def canonical(url):
    return url.strip()

rows={}; urls={}
for name,url_field,name_field,typ_field in DATASETS:
    inp=ROOT/"inputs"/(name+".csv")
    with inp.open(newline="",encoding="utf-8-sig") as fd:
        rr=list(csv.DictReader(fd))
    rows[name]=rr
    for r in rr:
        url=canonical(r.get(url_field,""))
        if url:urls[url]=None
print("AUDIT_INPUT_COUNTS",json.dumps({k:len(v) for k,v in rows.items()},sort_keys=True),flush=True)
print("UNIQUE_URLS",len(urls),flush=True)

with ThreadPoolExecutor(max_workers=12) as pool:
    tasks={pool.submit(fetch_one,url):url for url in urls}
    for task in as_completed(tasks):
        url=tasks[task]
        try:urls[url]=task.result()
        except Exception as e:urls[url]={"probe_status":"PROBE_CRASH","error":str(e),"text":""}
        if sum(1 for v in urls.values() if v is not None)%75==0:
            print("PROGRESS",sum(1 for v in urls.values() if v is not None),"/",len(urls),flush=True)
fields=["dataset","row","name","kind","url","probe_status","http_status","final_url","mime","bytes_read","latency_ms","title","xml_entries","json_records","truncated","code_visible_on_source_page","code_check_method","source_published_status","source_last_verified","source_expiry","expiry_check","error","tested_utc"]
totals=collections.Counter()
for name,url_field,name_field,typ_field in DATASETS:
    output=[]
    for i,r in enumerate(rows[name],1):
        url=canonical(r.get(url_field,""))
        probe=urls.get(url) or {"probe_status":"URL_MISSING","error":"No URL"}
        code=r.get("code","").strip() if name=="coupon_119" else ""
        source_code_visible="NOT_APPLICABLE"
        check_method=""
        if name=="coupon_119":
            if probe["probe_status"]!="PUBLIC_HTTP_OK":source_code_visible="UNTESTABLE_PAGE"
            elif not code:source_code_visible="MISSING_CODE"
            elif len(code)<4:source_code_visible="TOO_SHORT_FOR_SAFE_TEXT_MATCH"
            else:
                text=html.unescape(probe.get("text",""))
                # Source-page appearance does not mean checkout acceptance.
                pat=r"(?<![A-Za-z0-9])"+re.escape(code)+r"(?![A-Za-z0-9])"
                source_code_visible="TEXT_PRESENT_NOT_CHECKOUT_VERIFIED" if re.search(pat,text,re.I) else "NOT_FOUND_IN_DOWNLOADED_TEXT"
                check_method="case-insensitive code boundary match against first 350k bytes of public page"
        expiry=r.get("expires_on","") if name=="coupon_119" else ""
        expire_flag="NOT_APPLICABLE"
        if name=="coupon_119":
            if not expiry:expire_flag="UNKNOWN_DATE"
            else:
                try:
                    expiry_dt=datetime.fromisoformat(expiry.replace("Z","+00:00"))
                    if expiry_dt.tzinfo is None:expiry_dt=expiry_dt.replace(tzinfo=timezone.utc)
                    expire_flag="EXPIRED_BY_DATE" if expiry_dt < datetime.now(timezone.utc) else "FUTURE_DATE_UNVERIFIED"
                except Exception:expire_flag="INVALID_DATE"
        d={"dataset":name,"row":i,"name":r.get(name_field,""),"kind":r.get(typ_field,""),"url":url,
           **{k:probe.get(k,"") for k in ("probe_status","http_status","final_url","mime","bytes_read","latency_ms","title","xml_entries","json_records","truncated","error")},
           "code_visible_on_source_page":source_code_visible,"code_check_method":check_method,
           "source_published_status":r.get("status_as_published",""),"source_last_verified":r.get("last_verified",""),
           "source_expiry":expiry,"expiry_check":expire_flag,"tested_utc":AUDIT_TIME}
        output.append(d)
        totals[(name,d["probe_status"])]+=1
    with (OUT/(name+"_TEST_RESULTS.csv")).open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");wr.writeheader();wr.writerows(output)
    print("RESULTS",name,len(output),json.dumps(dict(collections.Counter(r["probe_status"] for r in output)),sort_keys=True),flush=True)
coupon_rows=list(csv.DictReader((OUT/"coupon_119_TEST_RESULTS.csv").open()))
print("COUPON_TEXT_MATCH",json.dumps(dict(collections.Counter(r["code_visible_on_source_page"] for r in coupon_rows))),flush=True)
print("COUPON_EXPIRY",json.dumps(dict(collections.Counter(r["expiry_check"] for r in coupon_rows))),flush=True)
summary={
 "tested_utc":AUDIT_TIME,"total_rows":sum(map(len,rows.values())),
 "dataset_counts":{k:len(v) for k,v in rows.items()},
 "unique_urls_attempted":len(urls),"unique_hosts":len(set(urllib.parse.urlsplit(u).hostname for u in urls)),
 "unique_url_outcomes":dict(collections.Counter(x.get("probe_status","") for x in urls.values())),
 "row_outcomes":{k:dict(collections.Counter(y for (name,y),n in totals.items() if name==k for _ in range(n))) for k in rows},
 "coupon_text_match_counts":dict(collections.Counter(r["code_visible_on_source_page"] for r in coupon_rows)),
 "coupon_expiry_counts":dict(collections.Counter(r["expiry_check"] for r in coupon_rows)),
 "limits":"All results are read-only public GET observations. No authentication, checkout submission, merchant permission, quota load test, or code validity testing.",
 "status_semantics":"200 means HTTP page reachable. 401/403 may be normal auth. Absence of coupon from text does not prove failure. Public access does not confer redistribution rights."
}
(OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
assert all((OUT/(name+"_TEST_RESULTS.csv")).exists() for name,_,_,_ in DATASETS)
assert sum(map(len,rows.values()))==485, "Input row mismatch"
assert len(urls)>200, "Unexpectedly few distinct URLs"
print("AUDIT_COMPLETE_JSON",json.dumps(summary,sort_keys=True),flush=True)
