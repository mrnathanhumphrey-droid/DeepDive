"""
twitter_fetch_agent.py
Fetches tweets from verified accounts via the Twitter/X API v2.
Used by the orchestrator for breaking news verification and by
the standalone tweet classification pipeline.

Requires TWITTER_BEARER_TOKEN in .env.

COST MODEL (as of March 2026):
  Twitter: $0.005 per post read, $0.01 per user lookup
  Anthropic Haiku: ~$0.0002 per classification call
  Anthropic Sonnet: ~$0.01 per web search verification call

  Budget cap: $2.00 per search session (configurable via TWITTER_BUDGET_CAP in .env)
"""

import os
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from models.schemas import AgentResult, AgentType


TWITTER_API_BASE = "https://api.x.com/2"

# Cost rates
COST_PER_TWEET_READ = 0.005    # $0.005 per post read
COST_PER_USER_LOOKUP = 0.01    # $0.01 per user/DM lookup
COST_PER_HAIKU_CALL = 0.0003   # ~$0.0003 per Haiku classification
COST_PER_SONNET_CALL = 0.012   # ~$0.012 per Sonnet web search verification


class BudgetExceeded(Exception):
    """Raised when the cost budget for a search session is exceeded."""
    pass


class CostTracker:
    """Tracks cumulative cost within a search session and enforces the budget cap."""

    def __init__(self, budget_cap: float = 2.00):
        self.budget_cap = budget_cap
        self.twitter_reads = 0
        self.user_lookups = 0
        self.haiku_calls = 0
        self.sonnet_calls = 0

    @property
    def twitter_cost(self) -> float:
        return (self.twitter_reads * COST_PER_TWEET_READ
                + self.user_lookups * COST_PER_USER_LOOKUP)

    @property
    def anthropic_cost(self) -> float:
        return (self.haiku_calls * COST_PER_HAIKU_CALL
                + self.sonnet_calls * COST_PER_SONNET_CALL)

    @property
    def total_cost(self) -> float:
        return self.twitter_cost + self.anthropic_cost

    @property
    def remaining(self) -> float:
        return max(0, self.budget_cap - self.total_cost)

    def max_tweets_remaining(self) -> int:
        """How many more tweets can we read within budget?"""
        return int(self.remaining / COST_PER_TWEET_READ)

    def check_budget(self, additional_tweets: int = 0,
                     additional_users: int = 0,
                     additional_haiku: int = 0,
                     additional_sonnet: int = 0) -> bool:
        """Return True if the additional cost fits within budget."""
        projected = (
            self.total_cost
            + additional_tweets * COST_PER_TWEET_READ
            + additional_users * COST_PER_USER_LOOKUP
            + additional_haiku * COST_PER_HAIKU_CALL
            + additional_sonnet * COST_PER_SONNET_CALL
        )
        return projected <= self.budget_cap

    def record_tweets(self, count: int):
        self.twitter_reads += count

    def record_user_lookups(self, count: int):
        self.user_lookups += count

    def record_haiku(self, count: int = 1):
        self.haiku_calls += count

    def record_sonnet(self, count: int = 1):
        self.sonnet_calls += count

    def summary(self) -> dict:
        return {
            "budget_cap": self.budget_cap,
            "total_cost": round(self.total_cost, 4),
            "remaining": round(self.remaining, 4),
            "twitter_cost": round(self.twitter_cost, 4),
            "anthropic_cost": round(self.anthropic_cost, 4),
            "twitter_reads": self.twitter_reads,
            "user_lookups": self.user_lookups,
            "haiku_calls": self.haiku_calls,
            "sonnet_calls": self.sonnet_calls,
            "max_tweets_remaining": self.max_tweets_remaining(),
        }


class TwitterFetchAgent:
    """Fetches and classifies tweets from verified news and official accounts.

    Two-pass search system:
      Pass 1: Keyword search (100 results) → filter against 268 approved accounts
      Pass 2: Targeted per-account search (only if pass 1 found no verified sources)

    All operations are budget-capped to prevent runaway costs."""

    # Searchable accounts — these get direct API queries in pass 2
    SEARCH_WIRE = [
        "Reuters", "ReutersWorld", "ReutersUS", "AP", "AP_Politics", "AFP",
    ]
    SEARCH_US_GOV = [
        "WhiteHouse", "POTUS", "StateDept", "DeptofDefense",
        "TheJusticeDept", "FBI", "CDCgov", "FEMA",
    ]
    SEARCH_WORLD = [
        "ZelenskyyUa", "IsraeliPM", "NATO", "UN", "WHO",
        "IAEAorg", "EU_Commission", "IDF", "FCDOGovUK", "ChineseEmbinUS",
    ]
    SEARCH_NEWS = [
        "AJEnglish", "BBCWorld", "BBCBreaking", "nytimes", "washingtonpost",
        "guardian", "politico", "thehill", "axios", "NPR",
    ]
    SEARCH_CIVIL_RIGHTS = [
        "ACLU", "NAACP", "hrw", "amnesty", "splcenter",
        "LawyersComm", "EFF", "pressfreedom", "LambdaLegal",
    ]
    SEARCH_THINK_TANKS = ["americanprog", "Heritage"]

    ALL_SEARCHABLE = (SEARCH_WIRE + SEARCH_US_GOV + SEARCH_WORLD
                      + SEARCH_NEWS + SEARCH_CIVIL_RIGHTS + SEARCH_THINK_TANKS)

    # Domain-to-search-tier mapping for pass 2 targeted fan-out
    DOMAIN_SEARCH_MAP = {
        "geopolitical": SEARCH_WIRE + SEARCH_WORLD,
        "legal": SEARCH_WIRE + SEARCH_CIVIL_RIGHTS + ["SCOTUSblog"],
        "civil_rights": SEARCH_WIRE + SEARCH_CIVIL_RIGHTS,
        "legislative": SEARCH_WIRE + SEARCH_US_GOV + SEARCH_THINK_TANKS,
        "civic": SEARCH_WIRE + SEARCH_US_GOV + SEARCH_THINK_TANKS,
        "sociological": SEARCH_WIRE + SEARCH_CIVIL_RIGHTS + SEARCH_THINK_TANKS,
        "general": SEARCH_WIRE,
    }

    # Approved accounts — loaded from JSON, used as filter (zero API cost)
    _approved_accounts = None

    @classmethod
    def _load_approved(cls) -> set:
        if cls._approved_accounts is None:
            import json
            from pathlib import Path
            path = Path(__file__).parent.parent / "data" / "approved_twitter_accounts.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            accounts = set()
            for key, val in data.items():
                if not key.startswith("_") and isinstance(val, list):
                    accounts.update(v.lower() for v in val)
            cls._approved_accounts = accounts
        return cls._approved_accounts

    def __init__(self, budget_cap: float = None):
        from dotenv import load_dotenv
        load_dotenv()
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        if not self.bearer_token:
            raise ValueError("TWITTER_BEARER_TOKEN not set in .env")

        cap = budget_cap or float(os.getenv("TWITTER_BUDGET_CAP", "2.00"))
        self.cost = CostTracker(budget_cap=cap)
        self.approved = self._load_approved()

    def _api_request(self, endpoint: str, params: dict = None) -> dict:
        """Make an authenticated GET request to the Twitter API v2."""
        url = f"{TWITTER_API_BASE}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "DeepDive/1.0",
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            return {"error": True, "status": e.code, "detail": body[:500]}
        except Exception as e:
            return {"error": True, "detail": str(e)}

    # ── Search ────────────────────────────────────────────────────────

    def search_recent(self, query: str, max_results: int = 50,
                      hours_back: int = 168) -> list[dict]:
        """Search recent tweets matching a query.
        Enforces budget cap before making the API call."""
        # Clamp to what budget allows
        affordable = self.cost.max_tweets_remaining()
        if affordable <= 0:
            return []
        max_results = min(max_results, 100, affordable)

        # Pre-check: tweets + 1 user lookup (for expansions)
        if not self.cost.check_budget(additional_tweets=max_results, additional_users=1):
            max_results = min(max_results, affordable)
            if max_results < 10:
                return []

        start_time = (
            datetime.now(timezone.utc) - timedelta(hours=hours_back)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "query": query,
            "max_results": max(min(max_results, 100), 10),
            "start_time": start_time,
            "tweet.fields": "created_at,author_id,public_metrics,source",
            "expansions": "author_id",
            "user.fields": "username,verified,name",
        }

        data = self._api_request("tweets/search/recent", params)
        if data.get("error"):
            return []

        # Record costs
        tweet_count = len(data.get("data", []))
        user_count = len(data.get("includes", {}).get("users", []))
        self.cost.record_tweets(tweet_count)
        self.cost.record_user_lookups(user_count)

        # Build author lookup
        authors = {}
        for user in data.get("includes", {}).get("users", []):
            authors[user["id"]] = {
                "username": user["username"],
                "name": user.get("name", ""),
                "verified": user.get("verified", False),
            }

        tweets = []
        for t in data.get("data", []):
            author = authors.get(t.get("author_id"), {})
            tweets.append({
                "id": t["id"],
                "text": t["text"],
                "created_at": t.get("created_at", ""),
                "author_username": author.get("username", "unknown"),
                "author_name": author.get("name", ""),
                "verified": author.get("verified", False),
                "retweet_count": t.get("public_metrics", {}).get("retweet_count", 0),
                "like_count": t.get("public_metrics", {}).get("like_count", 0),
            })

        return tweets

    def fetch_from_accounts(self, accounts: list[str] = None,
                            max_per_account: int = 25,
                            hours_back: int = 168) -> list[dict]:
        """Fetch recent tweets from specific accounts.
        Stops early if budget is exhausted."""
        accounts = accounts or self.ALL_ACCOUNTS
        all_tweets = []

        for username in accounts:
            # Check if we can afford at least 10 more tweets
            if self.cost.max_tweets_remaining() < 10:
                print(f"  Budget cap reached after {len(all_tweets)} tweets "
                      f"(${self.cost.total_cost:.3f} / ${self.cost.budget_cap:.2f})")
                break

            query = f"from:{username} -is:retweet"
            tweets = self.search_recent(query, max_per_account, hours_back)
            for t in tweets:
                t["tier"] = self._get_tier(username)
            all_tweets.extend(tweets)

        return all_tweets

    def fetch_breaking_verification(self, topic: str,
                                     domain: str = "general",
                                     hours_back: int = 48) -> list[dict]:
        """Search for tweets about a breaking topic from domain-relevant accounts.
        Uses DOMAIN_SEARCH_MAP when a domain is provided, falls back to all wire
        accounts. Caps account list at 8 to stay under Twitter query length limits.
        Budget-capped to 20 tweets max."""
        accounts = self.DOMAIN_SEARCH_MAP.get(domain, self.SEARCH_WIRE)
        # Deduplicate and cap at 8 to avoid exceeding 512-char query limit
        accounts = list(dict.fromkeys(accounts))[:8]
        account_filter = " OR ".join(f"from:{a}" for a in accounts)
        query = f"({topic[:200]}) ({account_filter}) -is:retweet"
        return self.search_recent(query, max_results=20, hours_back=hours_back)

    # ── Two-pass topic search ─────────────────────────────────────────

    def two_pass_search(self, topic: str, domain: str = "general",
                        hours_back: int = 168) -> dict:
        """Two-pass search system:
        Pass 1: Keyword search for the topic (100 results, ~$0.76)
                Filter results against 268 approved accounts.
        Pass 2: Only if pass 1 found no verified sources — targeted
                per-account search for domain-relevant accounts (~$0.53).

        Returns dict with tweets, verified_count, pass_used, and cost."""
        all_tweets = []
        verified_tweets = []

        # ── Pass 1: Keyword search ────────────────────────────────────
        query = f"{topic[:200]} -is:retweet lang:en"
        pass1_results = self.search_recent(query, max_results=100, hours_back=hours_back)

        for t in pass1_results:
            username_lower = t.get("author_username", "").lower()
            t["is_approved"] = username_lower in self.approved
            t["tier"] = self._get_tier_from_approved(username_lower)
            all_tweets.append(t)
            if t["is_approved"]:
                verified_tweets.append(t)

        if verified_tweets:
            # Pass 1 found verified sources — no need for pass 2
            return {
                "tweets": all_tweets,
                "verified_tweets": verified_tweets,
                "verified_count": len(verified_tweets),
                "total_results": len(all_tweets),
                "pass_used": 1,
                "cost": self.cost.summary(),
            }

        # ── Pass 2: Targeted account search ───────────────────────────
        search_accounts = self.DOMAIN_SEARCH_MAP.get(domain, self.SEARCH_WIRE)
        # Deduplicate
        search_accounts = list(dict.fromkeys(search_accounts))

        for username in search_accounts:
            if self.cost.max_tweets_remaining() < 10:
                break
            q = f"from:{username} {topic[:100]} -is:retweet"
            tweets = self.search_recent(q, max_results=5, hours_back=hours_back)
            for t in tweets:
                t["is_approved"] = True
                t["tier"] = self._get_tier_from_approved(username.lower())
                all_tweets.append(t)
                verified_tweets.append(t)

        return {
            "tweets": all_tweets,
            "verified_tweets": verified_tweets,
            "verified_count": len(verified_tweets),
            "total_results": len(all_tweets),
            "pass_used": 2,
            "cost": self.cost.summary(),
        }

    def _get_tier(self, username: str) -> str:
        if username in self.SEARCH_WIRE:
            return "tier1_wire"
        if username in self.SEARCH_US_GOV:
            return "tier2_us_gov"
        if username in self.SEARCH_WORLD:
            return "tier3_world"
        if username in self.SEARCH_NEWS:
            return "tier4_news"
        if username in self.SEARCH_CIVIL_RIGHTS:
            return "tier5_civil_rights"
        if username in self.SEARCH_THINK_TANKS:
            return "tier5_think_tank"
        return "untiered"

    def _get_tier_from_approved(self, username_lower: str) -> str:
        """Determine tier from the approved accounts JSON categories."""
        import json
        from pathlib import Path
        # Use cached data
        path = Path(__file__).parent.parent / "data" / "approved_twitter_accounts.json"
        if not hasattr(self, '_tier_cache'):
            data = json.loads(path.read_text(encoding="utf-8"))
            self._tier_cache = {}
            tier_map = {
                "wire_services": "tier1_wire",
                "wire_journalists": "tier1_wire_journalist",
                "us_government": "tier2_us_gov",
                "us_legislative": "tier2_us_legislative",
                "us_senators_119th": "tier2_us_senator",
                "us_cabinet_2nd_trump": "tier2_us_cabinet",
                "us_judicial": "tier2_us_judicial",
                "world_leaders": "tier3_world_leader",
                "international_orgs": "tier3_intl_org",
                "foreign_government": "tier3_foreign_gov",
                "major_news": "tier4_news",
                "think_tanks_policy": "tier5_think_tank",
                "civil_rights_legal": "tier5_civil_rights",
            }
            for key, tier in tier_map.items():
                for handle in data.get(key, []):
                    self._tier_cache[handle.lower()] = tier
        return self._tier_cache.get(username_lower, "untiered")

    # ── Classification pipeline ───────────────────────────────────────

    def classify_tweets(self, tweets: list[dict]) -> list[dict]:
        """Run tweets through the input parser and add classification fields.
        Records Haiku cost for any LLM second-pass calls."""
        from input_parser import InputParser
        import input_parser as ip

        # Disable web search verification for batch processing
        orig = ip.InputParser._verify_recency_via_search
        ip.InputParser._verify_recency_via_search = lambda self, text: None
        parser = ip.InputParser()

        classified = []
        for t in tweets:
            text = t["text"]
            import re
            clean_text = re.sub(r'https?://\S+', '', text).strip()
            if len(clean_text) < 10:
                continue

            r = parser.parse(clean_text)

            # Estimate if Haiku was called (check for llm_classify in markers)
            if any("llm_classify" in str(m) for m in r.matched_breaking + r.matched_current):
                self.cost.record_haiku()

            t["classification"] = {
                "mode": r.mode,
                "domain": r.domain,
                "subdomain": r.subdomain,
                "is_headline": r.is_headline,
                "is_question": r.is_question,
                "matched_breaking": r.matched_breaking[:3],
                "matched_current": r.matched_current[:3],
            }
            classified.append(t)

        ip.InputParser._verify_recency_via_search = orig
        return classified

    def fetch_and_classify(self, accounts: list[str] = None,
                           max_per_account: int = 25,
                           hours_back: int = 168) -> dict:
        """Full pipeline: fetch, classify, summarize. Budget-enforced."""
        tweets = self.fetch_from_accounts(accounts, max_per_account, hours_back)
        classified = self.classify_tweets(tweets)

        modes = {}
        domains = {}
        for t in classified:
            m = t["classification"]["mode"]
            d = t["classification"]["domain"]
            modes[m] = modes.get(m, 0) + 1
            domains[d] = domains.get(d, 0) + 1

        total = len(classified)
        return {
            "total": total,
            "modes": modes,
            "domains": domains,
            "detection_rate": (
                (total - modes.get("general", 0)) / max(total, 1)
            ),
            "cost": self.cost.summary(),
            "tweets": classified,
        }

    # ── Export ─────────────────────────────────────────────────────────

    def export_dataset(self, data: dict, filepath: str = None) -> str:
        if filepath is None:
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "results", "twitter_classification.json"
            )
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return filepath
