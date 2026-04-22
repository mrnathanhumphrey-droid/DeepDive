"""
failure_cache.py
Thread-safe shared cache that tracks headline resolution failures across agents.
Prevents 19 agents from independently hammering the same dead-end queries
and enables deferred resolution via exponential backoff retries.
"""

import time
import threading
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Retry schedule (seconds after first failure)
RETRY_BACKOFFS = [30, 120, 600]  # 30s, 2min, 10min


@dataclass
class FailureEntry:
    headline: str
    first_failed: float = field(default_factory=time.time)
    attempts: int = 1
    queries_tried: list[str] = field(default_factory=list)
    tiers_tried: list[str] = field(default_factory=list)
    resolved_url: str = ""
    resolved_content: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.resolved_url)

    @property
    def next_retry_at(self) -> float:
        """Timestamp of next retry, or 0 if all retries exhausted."""
        idx = min(self.attempts - 1, len(RETRY_BACKOFFS) - 1)
        if self.attempts > len(RETRY_BACKOFFS):
            return 0  # All retries exhausted
        return self.first_failed + RETRY_BACKOFFS[idx]

    @property
    def should_retry(self) -> bool:
        if self.is_resolved:
            return False
        if self.attempts > len(RETRY_BACKOFFS):
            return False
        return time.time() >= self.next_retry_at


class FailureCache:
    """Thread-safe cache for tracking headline resolution failures."""

    def __init__(self):
        self._entries: dict[str, FailureEntry] = {}
        self._lock = threading.Lock()

    def _normalize_key(self, headline: str) -> str:
        return headline.lower().strip()[:200]

    def record_failure(self, headline: str, queries_tried: list[str] = None,
                       tier: str = "") -> None:
        """Record a failed resolution attempt."""
        key = self._normalize_key(headline)
        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                entry.attempts += 1
                if queries_tried:
                    entry.queries_tried.extend(queries_tried)
                if tier and tier not in entry.tiers_tried:
                    entry.tiers_tried.append(tier)
            else:
                self._entries[key] = FailureEntry(
                    headline=headline,
                    queries_tried=queries_tried or [],
                    tiers_tried=[tier] if tier else [],
                )

        logger.debug("[failure_cache] Recorded failure for '%s' (attempt %d, tier=%s)",
                     headline[:60], self._entries[key].attempts, tier)

    def record_success(self, headline: str, url: str, content: str = "") -> None:
        """Record a successful resolution — future lookups will use this."""
        key = self._normalize_key(headline)
        with self._lock:
            if key in self._entries:
                self._entries[key].resolved_url = url
                self._entries[key].resolved_content = content
            else:
                self._entries[key] = FailureEntry(
                    headline=headline,
                    resolved_url=url,
                    resolved_content=content,
                )
        logger.info("[failure_cache] Resolved '%s' → %s", headline[:60], url[:80])

    def check(self, headline: str) -> dict | None:
        """Check if a headline has a cached result.

        Returns:
            None if not in cache
            {"resolved": True, "url": ..., "content": ...} if previously resolved
            {"resolved": False, "should_retry": bool, "attempts": int, ...} if failed
        """
        key = self._normalize_key(headline)
        with self._lock:
            entry = self._entries.get(key)

        if entry is None:
            return None

        if entry.is_resolved:
            return {
                "resolved": True,
                "url": entry.resolved_url,
                "content": entry.resolved_content,
                "source": "failure_cache",
            }

        return {
            "resolved": False,
            "should_retry": entry.should_retry,
            "attempts": entry.attempts,
            "tiers_tried": entry.tiers_tried,
            "queries_tried": entry.queries_tried[-10:],  # Last 10
        }

    def get_retryable(self) -> list[str]:
        """Return headlines that are due for retry."""
        with self._lock:
            return [
                entry.headline
                for entry in self._entries.values()
                if entry.should_retry
            ]

    @property
    def stats(self) -> dict:
        with self._lock:
            total = len(self._entries)
            resolved = sum(1 for e in self._entries.values() if e.is_resolved)
            retryable = sum(1 for e in self._entries.values() if e.should_retry)
        return {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "retryable": retryable,
        }
