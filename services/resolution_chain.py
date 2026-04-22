"""
resolution_chain.py
Confidence-gated escalation chain for headline resolution.

Chain order:
  1. Failure cache check (instant — already resolved?)
  2. RSS cache (sub-second — wire feeds polled every 90s)
  3. Twitter reverse-anchor (seconds — wire accounts tweet links within minutes)
  4. Gemini grounded search (seconds — independent Google Search index via Gemini)
  5. GDELT (seconds — near-real-time, strong for policy/governance)
  6. Claude web_search (existing path — Google-backed, subject to indexing delay)
  7. Flag for failure cache (deferred retry)

Each tier returns (results, confidence). Chain stops at first result above threshold.
Diagnostic logging shows which tier resolved and which were tried.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Confidence threshold — stop escalating once a tier exceeds this
CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ResolutionResult:
    """Result from the resolution chain."""
    resolved: bool
    tier: str  # Which tier resolved it (e.g., "rss_cache", "twitter_anchor", "gemini_grounded")
    confidence: float
    url: str = ""
    title: str = ""
    outlet: str = ""
    summary: str = ""
    content: str = ""  # Full article content if available
    tiers_tried: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_evidence(self, headline: str) -> dict:
        """Convert to the evidence dict format used by orchestrator."""
        return {
            "url": self.url or f"headline_search:{headline[:80]}",
            "content": self.content or self.summary or f"[{self.tier}] {self.title}",
            "status": f"headline_verified_via_{self.tier}",
            "injected_by": "headline_lookup",
            "original_headline": headline,
            "resolution_tier": self.tier,
            "resolution_confidence": self.confidence,
            "tiers_tried": self.tiers_tried,
        }


class ResolutionChain:
    """Orchestrates headline resolution through a tiered escalation chain.

    Initialize once in the Orchestrator and reuse across the session.
    The failure cache and RSS poller maintain state across calls.
    """

    def __init__(self, twitter_agent=None, news_fetch_agent=None):
        # Lazy imports — tiers that aren't configured just get skipped
        from services.rss_poller import RSSPoller
        from services.gemini_search import GeminiSearch
        from services.gdelt import GDELTSearch
        from services.failure_cache import FailureCache

        self.rss = RSSPoller()
        self.gemini = GeminiSearch()
        self.gdelt = GDELTSearch()
        self.cache = FailureCache()

        # These are passed in from the orchestrator
        self.twitter_agent = twitter_agent
        self.news_fetch_agent = news_fetch_agent

        # Diagnostics
        self._total_calls = 0
        self._tier_hits = {}

    def resolve(self, headline: str, domain: str = "general",
                skip_web_search: bool = False) -> ResolutionResult:
        """Run the headline through the escalation chain.

        Args:
            headline: The pasted headline text
            domain: Topic domain (for Twitter tier targeting)
            skip_web_search: If True, skip the Claude web_search tier
                             (caller handles it separately)

        Returns:
            ResolutionResult with resolution details
        """
        start = time.time()
        self._total_calls += 1
        tiers_tried = []

        # ── Tier 0: Failure cache check ──────────────────────────────
        cached = self.cache.check(headline)
        if cached and cached["resolved"]:
            logger.info("[chain] Cache hit for '%s'", headline[:60])
            self._record_hit("failure_cache")
            return ResolutionResult(
                resolved=True,
                tier="failure_cache",
                confidence=0.9,
                url=cached["url"],
                content=cached.get("content", ""),
                tiers_tried=["failure_cache"],
                elapsed_ms=int((time.time() - start) * 1000),
            )

        # If cache says "don't retry yet", skip the chain entirely
        if cached and not cached["resolved"] and not cached["should_retry"]:
            logger.debug("[chain] Cache says skip retry for '%s' (attempt %d)",
                         headline[:60], cached["attempts"])
            return ResolutionResult(
                resolved=False,
                tier="failure_cache_skip",
                confidence=0.0,
                tiers_tried=["failure_cache_skip"],
                elapsed_ms=int((time.time() - start) * 1000),
            )

        # ── Tier 1: RSS cache ────────────────────────────────────────
        tiers_tried.append("rss_cache")
        try:
            rss_results = self.rss.search(headline)
            if rss_results:
                best = rss_results[0]
                confidence = best["match_score"] / 100.0
                if confidence >= CONFIDENCE_THRESHOLD:
                    self._record_hit("rss_cache")
                    self.cache.record_success(headline, best["url"], best.get("summary", ""))
                    return ResolutionResult(
                        resolved=True,
                        tier="rss_cache",
                        confidence=confidence,
                        url=best["url"],
                        title=best["title"],
                        outlet=best["outlet"],
                        summary=best.get("summary", ""),
                        tiers_tried=tiers_tried,
                        elapsed_ms=int((time.time() - start) * 1000),
                    )
        except Exception as e:
            logger.debug("[chain] RSS tier error: %s", e)

        # ── Tier 2: Twitter reverse-anchor ────────────────────────────
        if self.twitter_agent:
            tiers_tried.append("twitter_anchor")
            try:
                result = self._twitter_resolve(headline, domain)
                if result and result.confidence >= CONFIDENCE_THRESHOLD:
                    self._record_hit("twitter_anchor")
                    self.cache.record_success(headline, result.url, result.content)
                    result.tiers_tried = tiers_tried
                    result.elapsed_ms = int((time.time() - start) * 1000)
                    return result
            except Exception as e:
                logger.debug("[chain] Twitter tier error: %s", e)

        # ── Tier 3: Gemini grounded search ────────────────────────────
        if self.gemini.available:
            tiers_tried.append("gemini_grounded")
            try:
                gemini_results = self.gemini.search(headline)
                if gemini_results:
                    best = gemini_results[0]
                    confidence = best["match_score"] / 100.0
                    if confidence >= CONFIDENCE_THRESHOLD:
                        self._record_hit("gemini_grounded")
                        self.cache.record_success(headline, best["url"], best.get("summary", ""))
                        return ResolutionResult(
                            resolved=True,
                            tier="gemini_grounded",
                            confidence=confidence,
                            url=best["url"],
                            title=best["title"],
                            outlet=best["outlet"],
                            summary=best.get("summary", ""),
                            content=best.get("summary", ""),
                            tiers_tried=tiers_tried,
                            elapsed_ms=int((time.time() - start) * 1000),
                        )
            except Exception as e:
                logger.debug("[chain] Gemini tier error: %s", e)

        # ── Tier 4: GDELT ────────────────────────────────────────────
        tiers_tried.append("gdelt")
        try:
            gdelt_results = self.gdelt.search(headline)
            if gdelt_results:
                best = gdelt_results[0]
                confidence = best["match_score"] / 100.0
                if confidence >= CONFIDENCE_THRESHOLD:
                    self._record_hit("gdelt")
                    self.cache.record_success(headline, best["url"], best.get("summary", ""))
                    return ResolutionResult(
                        resolved=True,
                        tier="gdelt",
                        confidence=confidence,
                        url=best["url"],
                        title=best["title"],
                        outlet=best["outlet"],
                        summary=best.get("summary", ""),
                        tiers_tried=tiers_tried,
                        elapsed_ms=int((time.time() - start) * 1000),
                    )
        except Exception as e:
            logger.debug("[chain] GDELT tier error: %s", e)

        # ── Tier 5: Claude web_search (existing path) ─────────────────
        # This is handled by the caller (orchestrator) since it uses the
        # full NewsFetchAgent.analyze() flow. We just record that we got here.
        if not skip_web_search:
            tiers_tried.append("web_search")

        # ── No resolution — record failure ────────────────────────────
        self.cache.record_failure(headline, tier=tiers_tried[-1] if tiers_tried else "none")

        return ResolutionResult(
            resolved=False,
            tier="unresolved",
            confidence=0.0,
            tiers_tried=tiers_tried,
            elapsed_ms=int((time.time() - start) * 1000),
        )

    def _twitter_resolve(self, headline: str, domain: str) -> ResolutionResult | None:
        """Use Twitter API to find wire service tweets linking to the article."""
        import re

        # Search wire service accounts for the headline
        accounts = self.twitter_agent.SEARCH_WIRE
        # Build query: headline keywords + wire account filter
        words = headline.split()[:10]
        query_text = " ".join(words)
        account_filter = " OR ".join(f"from:{a}" for a in accounts)
        query = f"({query_text}) ({account_filter}) -is:retweet"

        tweets = self.twitter_agent.search_recent(query, max_results=20, hours_back=72)
        if not tweets:
            return None

        # Look for tweets containing URLs (wire services almost always include article links)
        for tweet in tweets:
            urls = re.findall(r'https?://[^\s\)\"\']+', tweet.get("text", ""))
            if urls:
                # Found a wire service tweet with a link — high confidence
                article_url = urls[0]
                return ResolutionResult(
                    resolved=True,
                    tier="twitter_anchor",
                    confidence=0.85,
                    url=article_url,
                    title=tweet.get("text", "")[:200],
                    outlet=f"@{tweet.get('author_username', 'unknown')}",
                    content=tweet.get("text", ""),
                )

        # Tweets found but no URLs — lower confidence, still useful as verification
        best_tweet = tweets[0]
        return ResolutionResult(
            resolved=True,
            tier="twitter_anchor",
            confidence=0.6,  # Below threshold — chain continues
            title=best_tweet.get("text", "")[:200],
            outlet=f"@{best_tweet.get('author_username', 'unknown')}",
            content=best_tweet.get("text", ""),
        )

    def _record_hit(self, tier: str):
        self._tier_hits[tier] = self._tier_hits.get(tier, 0) + 1

    @property
    def diagnostics(self) -> dict:
        return {
            "total_calls": self._total_calls,
            "tier_hits": dict(self._tier_hits),
            "cache_stats": self.cache.stats,
            "rss_cache_size": self.rss.cache_size,
            "gemini_available": self.gemini.available,
        }
