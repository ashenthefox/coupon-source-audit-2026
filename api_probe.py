#!/usr/bin/env python3
"""One-shot read-only JSON/API contract sampling. No credentials, checkout, account operations."""
import urllib.request,urllib.error,urllib.parse,json,time,datetime,collections,csv,html,re
from pathlib import Path
OUT=Path("api_reports");OUT.mkdir(exist_ok=True)
tests=[
("that.promo offers","GET","https://that.promo/offers.json",None),
("that.promo changes","GET","https://that.promo/changes.json?limit=20",None),
("Lantern Works current deals","GET","https://thelanternworks.com/api/v1/deals.json",None),
("Lantern Works legacy deals","GET","https://thelanternworks.com/deals.json",None),
("FreeLLMCredits offers","GET","https://freellmcredits.com/api/offers.json",None),
("c0upons public coupons","GET","https://c0upons.pwa.pit.world/api/coupons",None),
("c0upons public stores","GET","https://c0upons.pwa.pit.world/api/stores",None),
("c0upons search","GET","https://c0upons.pwa.pit.world/api/search?q=nike",None),
("Scoopdeals categories","GET","https://scoopdeals.com/wp-json/sdh/v1/categories",None),
("Scoopdeals browse","GET","https://scoopdeals.com/wp-json/sdh/v1/browse?category=electronics&sort=off",None),
("Scoopdeals suggestions","GET","https://scoopdeals.com/wp-json/sdh/v1/suggest?q=earbuds&max=20",None),
("Clickwise public deals","GET","https://partners.clickwise.net/api/v1/deals/?lang=en&page_size=20",None),
("Freebin approved offers","POST","https://freebin.app/functions/publicApi",{"action":"search_offers","limit":20}),
("Freebin public companies","POST","https://freebin.app/functions/publicApi",{"action":"companies","limit":20}),
("Freebin referral codes","POST","https://freebin.app/functions/publicApi",{"action":"referral_codes","limit":20}),
("coupon-swarm JSON","GET","https://raw.githubusercontent.com/Geo-Coder-17/coupon-swarm/main/codes.json",None),
("WhaleCoupons JSON","GET","https://whalecoupons.co/codes.json",None),
("CouponAPI.org full feed auth check","GET","https://couponapi.org/api/getFullFeed/",None)
]
fields=["source","method","url","http_status","outcome","mime","bytes_read","truncated","root_type","record_count","sampled_records","nonempty_codes","expiry_fields_present","last_verified_fields_present","top_level_keys","rate_limit_header","retry_after_header","elapsed_ms","error","test_time_utc"]
output=[]
for label,method,url,body in tests:
    started=time.monotonic();error="";status=0;ctype="";data=b"";heads={}; final=url
    try:
        hdr={"User-Agent":"CouponSourceAudit/1.0 (+https://github.com/ashenthefox/coupon-source-audit-2026)","Accept":"application/json"}
        b=json.dumps(body).encode() if body is not None else None
        if body is not None: hdr["Content-Type"]="application/json"
        req=urllib.request.Request(url,headers=hdr,data=b,method=method)
        with urllib.request.urlopen(req,timeout=18) as response:
            status=response.status;ctype=response.headers.get("Content-Type","");heads=dict(response.headers);final=response.geturl();data=response.read(5000001)
    except urllib.error.HTTPError as e:
        status=e.code;error="HTTP "+str(status);heads=dict(e.headers)
        try:data=e.read(10000)
        except Exception:pass
    except Exception as e:error=type(e).__name__+":"+str(e)[:200]
    truncated=len(data)>5000000
    data=data[:5000000]
    root="";count="";sample_count="";codes="";expiry="";verified="";keys=""
    try:
        obj=json.loads(data)
        root=type(obj).__name__
        if isinstance(obj,dict):keys=", ".join(str(k) for k in list(obj)[:20])
        arrays=[("root",obj)] if isinstance(obj,list) else [(k,v) for k,v in obj.items() if isinstance(v,list)] if isinstance(obj,dict) else []
        if arrays:
            k,l=max(arrays,key=lambda x:len(x[1]));count=len(l);sample=l[:min(100,len(l))];sample_count=len(sample)
            codes=sum(1 for x in sample if isinstance(x,dict) and any(x.get(p) not in ("",None,False) for p in ("code","promo_code","coupon_code","voucher_code")))
            expiry=sum(1 for x in sample if isinstance(x,dict) and any(p in x for p in ("expiry","expires_on","expires_at","expiry_date","end_date","valid_to","date_end")))
            verified=sum(1 for x in sample if isinstance(x,dict) and any(p in x for p in ("last_verified","verified_at","checked_at","last_checked","verification_date")))
    except Exception as e:
        if not error and 200<=status<300:error="JSON parse: "+str(e)[:100]
    if 200<=status<300 and count!="" and not truncated:outcome="PARSED_PUBLIC_JSON"
    elif 200<=status<300 and truncated:outcome="PUBLIC_RESPONSE_TOO_LARGE_FOR_FULL_PARSE"
    elif 200<=status<300:outcome="PUBLIC_RESPONSE_NOT_PARSED_JSON"
    elif status in (401,403):outcome="ACCESS_RESTRICTED"
    elif status==429:outcome="RATE_LIMITED"
    elif status==404:outcome="NOT_FOUND"
    elif status:outcome="OTHER_HTTP_ERROR"
    else:outcome="FETCH_ERROR"
    row=dict(source=label,method=method,url=url,http_status=status,outcome=outcome,mime=ctype,bytes_read=len(data),truncated=truncated,root_type=root,record_count=count,sampled_records=sample_count,nonempty_codes=codes,expiry_fields_present=expiry,last_verified_fields_present=verified,top_level_keys=keys,rate_limit_header=heads.get("RateLimit","") or heads.get("X-RateLimit-Limit","") or heads.get("RateLimit-Limit",""),retry_after_header=heads.get("Retry-After",""),elapsed_ms=int((time.monotonic()-started)*1000),error=error,test_time_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    output.append(row)
    print("API_TEST",label,"=>",outcome,"HTTP",status,"records",count,"codes",codes,"expiry_fields",expiry,"err",error[:60],flush=True)
    time.sleep(0.4)
with (OUT/"PUBLIC_JSON_API_CONTRACT_TESTS.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(output)
summary={"tests":len(output),"results":dict(collections.Counter(x["outcome"] for x in output)),"records_parsed":sum(x["record_count"] for x in output if isinstance(x["record_count"],int)),"limits":"One request per endpoint. Unauthenticated source-sample checks only. Nonempty code field != accepted code. Sample counts are NOT complete worldwide coupon inventory."}
(OUT/"api_summary.json").write_text(json.dumps(summary,indent=2));print("API_SUMMARY_JSON",json.dumps(summary),flush=True)
assert len(output)==len(tests)
