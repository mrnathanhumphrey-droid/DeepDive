"""
gdelt.py
Queries the GDELT 2.0 DOC API for news article resolution.
GDELT processes news in near real-time and is particularly strong
for policy, governance, and international affairs content.

Free, no API key required.
"""

import json
import logging
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


class GDELTSearch:
    """Queries GDELT 2.0 DOC API for headline resolution."""

    @property
    def available(self) -> bool:
        return True  # No API key needed

    def search(self, headline: str, mode: str = "ArtList",
               timespan: str = "72h", max_results: int = 10) -> list[dict]:
        """Search GDELT for articles matching a headline.

        Args:
            headline: The headline text to search for
            mode: "ArtList" for article list, "TimelineVol" for volume timeline
            timespan: Time window (e.g., "72h", "7d", "30d")
            max_results: Max articles to return

        Returns:
            List of dicts with url, title, outlet, summary, published, match_score
        """
        # Clean the query — GDELT doesn't handle very long queries well
        query = headline[:200].strip()

        params = urllib.parse.urlencode({
            "query": query,
            "mode": mode,
            "format": "json",
            "timespan": timespan,
            "maxrecords": min(max_results, 75),
            "sort": "DateDesc",
        })

        url = f"{GDELT_DOC_API}?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DeepDive/1.0"},
        )

        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.warning("[gdelt] HTTP %d: %s", e.code, e.read().decode()[:200])
            return []
        except Exception as e:
            logger.warning("[gdelt] Request failed: %s", e)
            return []

        results = []
        for article in data.get("articles", []):
            results.append({
                "url": article.get("url", ""),
                "title": article.get("title", ""),
                "outlet": article.get("domain", article.get("sourcecountry", "Unknown")),
                "summary": article.get("title", "")[:500],  # GDELT doesn't return summaries
                "published": article.get("seendate", ""),
                "match_score": 70.0,  # Lower baseline — GDELT matches on keywords, not semantics
                "source": "gdelt",
            })

        return results[:max_results]

    def search_policy(self, headline: str, timespan: str = "72h") -> list[dict]:
        """Search with policy/governance theme boosting.
        Appends domain-relevant terms to improve GDELT recall for policy content."""
        # GDELT responds well to theme-based queries
        base_results = self.search(headline, timespan=timespan)

        # If base search found enough, return
        if len(base_results) >= 3:
            return base_results

        # Try with wire service domain filter
        wire_query = f"{headline[:150]} sourcecountry:US"
        wire_results = self.search(wire_query, timespan=timespan, max_results=5)

        seen_urls = {r["url"] for r in base_results}
        for r in wire_results:
            if r["url"] not in seen_urls:
                base_results.append(r)

        return base_results[:10]
