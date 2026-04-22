"""
rss_poller.py
Polls wire service RSS feeds and maintains a short-lived in-memory cache
of recent articles. Used as the fastest tier in the resolution chain —
wire RSS updates within minutes of publication, well before Google indexes.

Dependencies: feedparser, rapidfuzz (install via pip)
"""

import time
import threading
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Wire service RSS feeds — these are the fastest public sources
DEFAULT_FEEDS = [
    # AP
    "https://rsshub.app/apnews/topics/apf-topnews",
    "https://rsshub.app/apnews/topics/apf-politics",
    "https://rsshub.app/apnews/topics/apf-usnews",
    # Reuters
    "https://rsshub.app/reuters/world",
    "https://rsshub.app/reuters/us",
    "https://rsshub.app/reuters/politics",
    # AFP (via Google News RSS)
    "https://news.google.com/rss/search?q=source:AFP&hl=en-US&gl=US&ceid=US:en",
]

# How long articles stay in cache (seconds)
CACHE_TTL = 3600  # 1 hour
# Minimum interval between feed polls (seconds)
POLL_INTERVAL = 90


@dataclass
class CachedArticle:
    title: str
    url: str
    summary: str
    outlet: str
    published: datetime
    fetched_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > CACHE_TTL


class RSSPoller:
    """Polls wire service RSS feeds and caches recent articles for fast lookup."""

    def __init__(self, feeds: list[str] = None):
        self.feeds = feeds or DEFAULT_FEEDS
        self._cache: list[CachedArticle] = []
        self._lock = threading.Lock()
        self._last_poll = 0.0

    def poll(self, force: bool = False) -> int:
        """Poll all feeds and update cache. Returns number of new articles added.
        Skips if polled recently unless force=True."""
        if not force and (time.time() - self._last_poll) < POLL_INTERVAL:
            return 0

        try:
            import feedparser
        except ImportError:
            logger.warning("[rss] feedparser not installed — pip install feedparser")
            return 0

        new_count = 0
        existing_urls = {a.url for a in self._cache}

        for feed_url in self.feeds:
            try:
                d = feedparser.parse(feed_url)
                for entry in d.entries[:20]:  # Cap per feed
                    url = entry.get("link", "")
                    if not url or url in existing_urls:
                        continue

                    # Parse publication date
                    published = datetime.now(timezone.utc)
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        except (TypeError, ValueError):
                            pass

                    # Detect outlet from feed URL
                    outlet = "Unknown"
                    feed_lower = feed_url.lower()
                    if "apnews" in feed_lower:
                        outlet = "AP"
                    elif "reuters" in feed_lower:
                        outlet = "Reuters"
                    elif "afp" in feed_lower:
                        outlet = "AFP"

                    article = CachedArticle(
                        title=entry.get("title", ""),
                        url=url,
                        summary=entry.get("summary", "")[:500],
                        outlet=outlet,
                        published=published,
                    )

                    with self._lock:
                        self._cache.append(article)
                        existing_urls.add(url)
                    new_count += 1

            except Exception as e:
                logger.debug("[rss] Feed error for %s: %s", feed_url[:60], e)

        # Evict expired entries
        with self._lock:
            self._cache = [a for a in self._cache if not a.is_expired]

        self._last_poll = time.time()
        logger.info("[rss] Polled %d feeds, added %d articles, cache size: %d",
                     len(self.feeds), new_count, len(self._cache))
        return new_count

    def search(self, headline: str, threshold: float = 65.0) -> list[dict]:
        """Fuzzy-match a headline against cached article titles.
        Returns matches sorted by score (highest first).

        Args:
            headline: The pasted headline text
            threshold: Minimum fuzzy match score (0-100)
        """
        # Ensure cache is fresh
        self.poll()

        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("[rss] rapidfuzz not installed — pip install rapidfuzz")
            # Fall back to simple substring matching
            return self._substring_search(headline)

        headline_lower = headline.lower().strip()
        matches = []

        with self._lock:
            for article in self._cache:
                score = fuzz.token_sort_ratio(headline_lower, article.title.lower())
                if score >= threshold:
                    matches.append({
                        "url": article.url,
                        "title": article.title,
                        "outlet": article.outlet,
                        "summary": article.summary,
                        "published": article.published.isoformat(),
                        "match_score": round(score, 1),
                        "source": "rss_cache",
                    })

        matches.sort(key=lambda m: m["match_score"], reverse=True)
        return matches[:5]

    def _substring_search(self, headline: str) -> list[dict]:
        """Fallback: simple keyword overlap matching when rapidfuzz isn't available."""
        headline_words = set(headline.lower().split())
        # Remove stopwords
        stopwords = {"the", "a", "an", "in", "on", "at", "for", "and", "or", "but", "to", "of", "is", "are", "was", "were"}
        headline_words -= stopwords
        if not headline_words:
            return []

        matches = []
        with self._lock:
            for article in self._cache:
                title_words = set(article.title.lower().split()) - stopwords
                if not title_words:
                    continue
                overlap = len(headline_words & title_words) / max(len(headline_words), 1)
                if overlap >= 0.5:
                    matches.append({
                        "url": article.url,
                        "title": article.title,
                        "outlet": article.outlet,
                        "summary": article.summary,
                        "published": article.published.isoformat(),
                        "match_score": round(overlap * 100, 1),
                        "source": "rss_cache",
                    })

        matches.sort(key=lambda m: m["match_score"], reverse=True)
        return matches[:5]

    @property
    def cache_size(self) -> int:
        return len(self._cache)
