"""Scrape Twitter for verified institutional accounts.
Budget: $5.00. Adds to approved_twitter_accounts.json."""

import os, sys, json, time
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
API = "https://api.x.com/2"
MAX_COST = 5.00
reads = 0
lookups = 0

def cost():
    return reads * 0.005 + lookups * 0.01

def remaining():
    return MAX_COST - cost()

def search(query, max_results=100):
    global reads, lookups
    if remaining() < max_results * 0.005 + 0.01:
        return []
    start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "query": query,
        "max_results": min(max_results, 100),
        "start_time": start,
        "tweet.fields": "author_id,created_at",
        "expansions": "author_id",
        "user.fields": "username,name,verified,description,public_metrics",
    }
    url = API + "/tweets/search/recent?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        tc = len(data.get("data", []))
        uc = len(data.get("includes", {}).get("users", []))
        reads += tc
        lookups += uc
        return data.get("includes", {}).get("users", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"  HTTP {e.code}: {body}")
        return []
    except Exception as e:
        print(f"  Error: {e}")
        return []

PUNDIT_WORDS = {"opinion", "commentator", "host of", "anchor", "pundit", "contributor", "analyst", "my views", "personal", "parody", "fan", "satire", "retired", "former"}

def is_pundit(desc):
    d = (desc or "").lower()
    return any(w in d for w in PUNDIT_WORDS)

accounts = {}

def collect(users, category, bio_keywords=None, min_followers=0):
    for u in users:
        desc = (u.get("description", "") or "")
        followers = u.get("public_metrics", {}).get("followers_count", 0)
        if is_pundit(desc):
            continue
        if min_followers and followers < min_followers:
            continue
        if bio_keywords:
            dl = desc.lower()
            if not any(w in dl for w in bio_keywords):
                continue
        accounts[u["username"].lower()] = {
            "username": u["username"],
            "name": u.get("name", ""),
            "description": desc[:200],
            "followers": followers,
            "category": category,
        }

def run_batch(label, queries, category, bio_keywords=None, min_followers=0, max_per=50):
    print(f"\n=== {label} ===")
    for q in queries:
        if remaining() < 0.30:
            print(f"  Budget limit (${cost():.2f}), stopping {label}")
            break
        users = search(q, max_per)
        collect(users, category, bio_keywords, min_followers)
        print(f"  [{len(users):3} users] ${cost():.2f} | {q[:65]}")
        time.sleep(1)

# ── Run all categories ──

run_batch("FEDERAL AGENCIES", [
    "from:DeptofDefense OR from:StateDept OR from:USTreasury -is:retweet",
    "from:DHSgov OR from:ICEgov OR from:CBP OR from:USCIS -is:retweet",
    "from:SECGov OR from:FTC OR from:FCC OR from:EPA -is:retweet",
    "from:FBI OR from:CDCgov OR from:US_FDA OR from:FEMA -is:retweet",
    "from:USDOL OR from:HHSGov OR from:USDA OR from:USDOT -is:retweet",
    "from:WhiteHouse OR from:POTUS OR from:VP -is:retweet",
], "federal_agency")

run_batch("WIRE JOURNALISTS", [
    "AP reporter OR correspondent washington -is:retweet lang:en",
    "Reuters reporter OR correspondent -is:retweet lang:en",
    "AFP correspondent OR reporter -is:retweet lang:en",
    "BBC correspondent washington OR court -is:retweet lang:en",
    "NPR correspondent OR reporter politics -is:retweet lang:en",
    "PBS NewsHour reporter -is:retweet lang:en",
    "CNN reporter correspondent court OR pentagon -is:retweet lang:en",
], "wire_journalist",
   bio_keywords=["ap ", "associated press", "reuters", "afp", "bbc", "npr", "pbs", "cnn", "nyt", "new york times", "washington post", "politico", "wall street journal", "bloomberg", "reporter", "correspondent", "journalist", "editor", "bureau"])

run_batch("NEWS ORGANIZATIONS", [
    "from:cnnbrk OR from:CNN OR from:CNNPolitics -is:retweet",
    "from:NBCNews OR from:CBSNews OR from:ABCNewsLive -is:retweet",
    "from:nytimes OR from:washingtonpost OR from:WSJ -is:retweet",
    "from:Bloomberg OR from:politico OR from:thehill -is:retweet",
    "from:AJEnglish OR from:guardian OR from:BBCWorld -is:retweet",
    "from:axios OR from:rollcall OR from:ProPublica -is:retweet",
    "from:LawfareBlog OR from:SCOTUSblog -is:retweet",
    "from:France24_en OR from:dwnews OR from:CBCNews -is:retweet",
    "court ruling judge OR law -is:retweet lang:en",
], "news_org", min_followers=5000)

run_batch("MARYLAND OFFICIALS", [
    "from:GovWesMoore -is:retweet",
    "from:SenVanHollen OR from:SenCardin -is:retweet",
    "Maryland governor OR senator OR delegate official -is:retweet lang:en",
    "Maryland General Assembly delegate -is:retweet lang:en",
    "Montgomery County council OR executive Maryland -is:retweet lang:en",
    "Baltimore mayor OR council official -is:retweet lang:en",
    "Prince George county Maryland official -is:retweet lang:en",
    "Annapolis Maryland legislature -is:retweet lang:en",
    "Maryland House of Delegates -is:retweet lang:en",
    "Maryland state senator -is:retweet lang:en",
], "maryland_official",
   bio_keywords=["maryland", "annapolis", "baltimore", "montgomery county", "prince george", "delegate", "senator", "council", "mayor", "governor", "representative", "commissioner", "md "])

run_batch("US SENATORS", [
    "United States Senator -is:retweet lang:en",
    "U.S. Senator official -is:retweet lang:en",
    "senator committee chair ranking -is:retweet lang:en",
    "senate judiciary OR appropriations OR foreign relations -is:retweet lang:en",
], "us_senator",
   bio_keywords=["senator", "u.s. senate", "united states senate", "ranking member", "chairman", "chairwoman"])

run_batch("US CABINET", [
    "secretary of state OR defense OR treasury official -is:retweet lang:en",
    "attorney general OR homeland security secretary -is:retweet lang:en",
], "us_cabinet",
   bio_keywords=["secretary", "attorney general", "administrator", "director", "cabinet"])

run_batch("THINK TANKS", [
    "from:BrookingsInst OR from:RANDCorporation OR from:CFR_org -is:retweet",
    "from:CarnegieEndow OR from:urbaninstitute OR from:pewresearch -is:retweet",
    "from:BrennanCenter OR from:Heritage OR from:AEI -is:retweet",
    "from:CatoInstitute OR from:CrisisGroup OR from:AtlanticCouncil -is:retweet",
    "policy research institute nonpartisan -is:retweet lang:en",
    "think tank policy brief analysis -is:retweet lang:en",
], "think_tank",
   bio_keywords=["policy", "research", "institute", "think tank", "nonpartisan", "center for", "foundation", "analysis"])

run_batch("CIVIL RIGHTS", [
    "from:ACLU OR from:NAACP OR from:hrw OR from:amnesty -is:retweet",
    "from:splcenter OR from:LawyersComm OR from:EFF -is:retweet",
    "from:LambdaLegal OR from:pressfreedom -is:retweet",
    "civil rights organization official -is:retweet lang:en",
    "human rights advocacy legal defense -is:retweet lang:en",
], "civil_rights_org",
   bio_keywords=["civil rights", "civil liberties", "human rights", "legal defense", "advocacy", "justice", "equality", "freedom"])

run_batch("INTERNATIONAL", [
    "from:UN OR from:NATO OR from:WHO OR from:IAEAorg -is:retweet",
    "from:EU_Commission OR from:WorldBank OR from:IMFNews -is:retweet",
    "from:IntlCrimCourt OR from:OPCW OR from:Refugees -is:retweet",
    "prime minister OR president official statement -is:retweet lang:en",
    "foreign minister OR ministry official -is:retweet lang:en",
], "international", min_followers=20000)

# ── Summary ──
print(f"\n{'='*60}")
print(f"TOTAL UNIQUE ACCOUNTS: {len(accounts)}")
print(f"TOTAL COST: ${cost():.2f} / ${MAX_COST:.2f}")
print(f"  Tweet reads: {reads}")
print(f"  User lookups: {lookups}")
print()

cats = {}
for a in accounts.values():
    c = a["category"]
    cats[c] = cats.get(c, 0) + 1
for c in sorted(cats.keys()):
    print(f"  {c:25} {cats[c]:4}")

# Save raw scrape
output = "results/twitter_account_scrape.json"
os.makedirs("results", exist_ok=True)
with open(output, "w") as f:
    json.dump({
        "total": len(accounts),
        "cost": {"reads": reads, "lookups": lookups, "total_usd": round(cost(), 2)},
        "categories": cats,
        "accounts": accounts,
    }, f, indent=2)
print(f"\nSaved to {output}")

# Merge into approved list
approved_path = "data/approved_twitter_accounts.json"
approved = json.load(open(approved_path))
new_count = 0
for handle, info in accounts.items():
    cat = info["category"]
    # Map to approved JSON categories
    cat_map = {
        "federal_agency": "us_government",
        "wire_journalist": "wire_journalists",
        "news_org": "major_news",
        "maryland_official": "maryland_officials",
        "us_senator": "us_senators_119th",
        "us_cabinet": "us_cabinet_2nd_trump",
        "think_tank": "think_tanks_policy",
        "civil_rights_org": "civil_rights_legal",
        "international": "international_orgs",
    }
    target_key = cat_map.get(cat, "major_news")
    if target_key not in approved:
        approved[target_key] = []
    existing = {h.lower() for h in approved[target_key]}
    if handle not in existing:
        approved[target_key].append(info["username"])
        new_count += 1

# Add maryland_officials category if new
if "maryland_officials" not in approved:
    approved["maryland_officials"] = []

with open(approved_path, "w") as f:
    json.dump(approved, f, indent=2)

print(f"\nMerged {new_count} new accounts into {approved_path}")
total_approved = sum(len(v) for k, v in approved.items() if not k.startswith("_") and isinstance(v, list))
print(f"Total approved accounts: {total_approved}")
