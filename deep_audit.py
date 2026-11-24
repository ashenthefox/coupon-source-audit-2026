#!/usr/bin/env python3
"""Read-only: 26 RSS feeds, 57 GitHub repositories, 119 merchant coupon page texts."""
import csv,json,os,re,html,time,collections,datetime,urllib.request,urllib.error,urllib.parse,threading
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).parent; OUT=ROOT/"deep_reports";OUT.mkdir(exist_ok=True)
NOW=datetime.datetime.now(datetime.timezone.utc)
def rows(n):
 with (ROOT/"inputs"/n).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
sources=rows("sources_238.csv");coupons=rows("coupon_119.csv")
def fetch(u,limit=1500000,timeout=14,headers=None):
 start=time.monotonic();status=0;body=b"";error="";mime=""
 try:
  req=urllib.request.Request(u,headers=headers or {"User-Agent":"CouponSourceAudit/2.0 read-only research","Accept":"text/html,application/json,application/xml,application/rss+xml,*/*"})
  with urllib.request.urlopen(req,timeout=timeout) as x:
   status=x.status;mime=x.headers.get("content-type","").split(";")[0];body=x.read(limit+1)
 except urllib.error.HTTPError as e:status=e.code;error="HTTP "+str(status)
 except Exception as e:error=type(e).__name__+":"+str(e)[:100]
 return {"status":status,"body":body[:limit],"mime":mime,"truncated":len(body)>limit,"error":error,"ms":int((time.monotonic()-start)*1000)}
def save(name,data):
 with (OUT/name).open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
class Text(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.words=[]
 def handle_starttag(self,t,a):
  if t in ("script","style","noscript","svg","template"):self.skip+=1
 def handle_endtag(self,t):
  if t in ("script","style","noscript","svg","template"):self.skip=max(0,self.skip-1)
 def handle_data(self,s):
  if not self.skip:self.words.append(s)
def visible(b):
 p=Text()
 try:p.feed(b.decode("utf-8","replace"))
 except Exception:pass
 return re.sub(r"\s+"," "," ".join(p.words))
def xmlentries(b):
 r=ET.fromstring(b);items=r.findall(".//item")
 return items if items else r.findall(".//{http://www.w3.org/2005/Atom}entry")
# Feed validity: count real published items, dates, and coupons indicated by text
feeds=[]
for r in sources:
 if r.get("Category")!="26 public deal-community RSS":continue
 u=r["URL"];j=fetch(u,2000000);a=[];err=""
 try:a=xmlentries(j["body"])
 except Exception as e:err=str(e)[:150]
 counter=collections.Counter();dates=[]
 for item in a:
  text=" ".join(str(t).strip() for t in item.itertext() if t and t.strip())
  tags={x.tag.split("}")[-1].lower():(x.text or "").strip() for x in item.iter()}
  counter["title"]+=int(bool(tags.get("title")))
  counter["promo_context"]+=int(bool(re.search(r"(?i)\b(coupon|voucher|promo.?code|discount.?code|gutschein|cupon|cup[oó]n)\b",text)))
  counter["possible_code_phrase"]+=int(bool(re.search(r"(?i)\b(?:code|coupon|voucher|promo.?code)\s*(?:is|:|=|\\-)\s*[A-Z0-9][A-Z0-9_-]{3,16}\b",text)))
  counter["expiry_language"]+=int(bool(re.search(r"(?i)\b(expir(?:es|y|ation)|valid until|ends on)\b",text)))
  for k in ("pubdate","published","updated"):
   if tags.get(k):
    try:dates.append(parsedate_to_datetime(tags[k]).astimezone(datetime.timezone.utc).isoformat());break
    except Exception:pass
 feeds.append({"name":r.get("Name",""),"url":u,"http_status":j["status"],"feed_parse_ok":bool(a),"entries":len(a),"with_titles":counter["title"],"promo_context_entries":counter["promo_context"],"possible_code_phrase_entries":counter["possible_code_phrase"],"expiry_language_entries":counter["expiry_language"],"newest_date":max(dates) if dates else "","oldest_date":min(dates) if dates else "","mime":j["mime"],"parse_error":err,"checked_utc":NOW.isoformat()})
 print("RSS",j["status"],len(a),u[:85],flush=True)
save("RSS_26_CONTENT_CHECKS.csv",feeds)
# github checks: metadata, not building or executing untrusted repositories
gh=[];token=os.environ.get("GH_TOKEN","");hdr={"User-Agent":"CouponSourceAudit/2.0","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
if token:hdr["Authorization"]="Bearer "+token
for r in sources:
 if r.get("Category")!="GitHub project / source code":continue
 p=urllib.parse.urlsplit(r["URL"]).path.strip("/").split("/")
 owner,repo=(p[0],p[1].removesuffix(".git")) if len(p)>=2 else ("","")
 j=fetch("https://api.github.com/repos/"+owner+"/"+repo,limit=150000,headers=hdr) if owner and repo else {"status":0,"body":b"","error":"Invalid repo URL"}
 data={}
 try:data=json.loads(j["body"])
 except Exception:pass
 if not isinstance(data,dict):data={}
 license=(data.get("license") or {}).get("spdx_id","")
 pushed=data.get("pushed_at") or ""
 try:days=(NOW-datetime.datetime.fromisoformat(pushed.replace("Z","+00:00"))).days
 except Exception:days=""
 gh.append({"repo":owner+"/"+repo,"url":r["URL"],"http_status":j["status"],"metadata_available":j["status"]==200,"archived":data.get("archived",""),"disabled":data.get("disabled",""),"license_spdx":license,"pushed_utc":pushed,"days_since_push":days,"stars":data.get("stargazers_count",""),"default_branch":data.get("default_branch",""),"size_kib":data.get("size",""),"build_test":"NOT_DONE","error":j["error"],"checked_utc":NOW.isoformat()})
 print("GITHUB",j["status"],owner+"/"+repo,license,flush=True)
 time.sleep(.16)
save("GITHUB_57_METADATA_CHECKS.csv",gh)
# Merchant URL sampling once per distinct source, without carts, cookies, or code submission
cache={};urlset={r.get("source_url","").strip() for r in coupons if r.get("source_url","").strip()};locks=collections.defaultdict(threading.Lock);recent=collections.defaultdict(float)
def merchant_get(u):
 h=urllib.parse.urlsplit(u).hostname or ""
 with locks[h]:
  pause=max(0,1.15-(time.monotonic()-recent[h]))
  if pause:time.sleep(pause)
  recent[h]=time.monotonic()
 return u,fetch(u,limit=750000,timeout=12)
with ThreadPoolExecutor(max_workers=8) as pool:
 for t in as_completed([pool.submit(merchant_get,u) for u in urlset]):
  u,j=t.result();cache[u]=j
merchant=[]
for r in coupons:
 u=r.get("source_url","").strip();j=cache.get(u) or {"status":0,"body":b"","error":"missing url","truncated":False}
 code=r.get("code","").strip();txt=visible(j["body"]) if j["status"]==200 else ""
 matches=list(re.finditer(r"(?<![A-Za-z0-9])"+re.escape(code)+r"(?![A-Za-z0-9])",txt,re.I)) if code else []
 snippets=[txt[max(0,m.start()-80):m.end()+80] for m in matches[:10]]
 promo=sum(bool(re.search(r"(?i)(coupon|voucher|code|promo|discount|save|off|rabatt)",s)) for s in snippets)
 verdict="UNREADABLE_SOURCE" if j["status"]!=200 else ("CODE_NOT_IN_SERVER_TEXT" if not matches else ("MATCH_WITH_PROMO_CONTEXT" if promo else "MATCH_WITHOUT_PROMO_CONTEXT"))
 expiry=r.get("expires_on","").strip();validity="UNKNOWN_EXPIRY"
 if expiry:
  try:
   d=datetime.datetime.fromisoformat(expiry.replace("Z","+00:00"));d=d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
   validity="EXPIRED_BY_DATE" if d<NOW else "FUTURE_EXPIRY_NOT_CHECKOUT_VERIFIED"
  except Exception:validity="BAD_EXPIRY_FORMAT"
 merchant.append({"store":r.get("store",""),"code":code,"source_url":u,"http_status":j["status"],"visible_text_matches":len(matches),"matches_near_promo_words":promo,"verdict":verdict,"expiry":expiry,"expiry_verdict":validity,"previous_verified":r.get("last_verified",""),"checkout_verified":False,"error":j.get("error",""),"checked_utc":NOW.isoformat()})
save("MERCHANT_119_TEXT_CHECKS.csv",merchant)
summary={"checked_utc":NOW.isoformat(),"feed_urls":len(feeds),"parseable_feeds":sum(x["feed_parse_ok"] for x in feeds),"rss_entries":sum(x["entries"] for x in feeds),"rss_possible_code_entries":sum(x["possible_code_phrase_entries"] for x in feeds),"github_repos":len(gh),"github_metadata_ok":sum(x["metadata_available"] for x in gh),"github_license_detected":sum(bool(x["license_spdx"]) and x["license_spdx"]!="NOASSERTION" for x in gh),"merchant_codes":len(merchant),"unique_merchant_urls":len(cache),"merchant_text_verdicts":dict(collections.Counter(x["verdict"] for x in merchant)),"expiry_counts":dict(collections.Counter(x["expiry_verdict"] for x in merchant)),"limits":"No checkout redemption or publisher account tests. Public pages and GitHub metadata only; no license to republish implied."}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print("DEEP_SUMMARY_JSON",json.dumps(summary),flush=True)
assert len(feeds)==26 and len(gh)==57 and len(merchant)==119
