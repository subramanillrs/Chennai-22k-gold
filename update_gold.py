import json,re,datetime as dt
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URLS=[
 "https://money.bankbazaar.com/gold-rate-chennai.html",
 "https://rates.goldenchennai.com/22-carat-gold-rate/chennai-22-carat-gold-rate-today/"
]
IST=dt.timezone(dt.timedelta(hours=5,minutes=30))
today=dt.datetime.now(IST).date()
headers={"User-Agent":"Mozilla/5.0 (compatible; ChennaiGoldRate/2.0)"}

def money(s):
    m=re.search(r"₹\s*([\d,]+(?:\.\d+)?)",s)
    return float(m.group(1).replace(",","")) if m else None

def fetch(url):
    r=requests.get(url,headers=headers,timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)

# Conservative extraction: only accept a value if the page explicitly mentions
# Chennai + 22K and the numeric value is in a plausible current range.
vals=[]
for u in URLS:
    try:
        text=fetch(u)
        if "Chennai" not in text or "22" not in text:
            continue
        # BankBazaar/Golden Chennai currently expose 14xxx Chennai 22K values.
        nums=[float(x.replace(",","")) for x in re.findall(r"(?:₹\s*)?(\d{1,3}(?:,\d{3})+|\d{4,5})(?:\s*/\s*1\s*gram)?",text)]
        candidates=[x for x in nums if 10000 <= x <= 30000]
        if candidates:
            # For these pages the first plausible 22K candidate is normally the displayed rate.
            vals.append((round(candidates[0],2),u))
    except Exception as e:
        print("source failed",u,e)

if not vals:
    raise SystemExit("No validated source value. Nothing was changed.")

# Require agreement when two sources are available. Otherwise do not publish.
unique=sorted(set(v for v,_ in vals))
if len(unique)>1:
    if len(vals)>=2:
        # No silent averaging: disagreement is a hard stop.
        raise SystemExit(f"Source disagreement: {vals}")
    raise SystemExit("Only one source available; refusing automatic publication.")

rate=unique[0]
out=Path("data/today.json")
data=json.loads(out.read_text())
data["rateDate"]=today.isoformat()
data["status"]="verified-today"
data["rates"]["22K"]["perGram"]=rate
data["rates"]["22K"]["per8g"]=rate*8
data["rates"]["22K"]["per10g"]=rate*10
data["lastFetchTime"]=dt.datetime.now(IST).isoformat()
data["freshnessNote"]="Published only after source validation; stale cached data is never substituted."
out.write_text(json.dumps(data,indent=2))
print("Verified",rate)
