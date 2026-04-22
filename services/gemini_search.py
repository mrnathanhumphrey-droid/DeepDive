"""
gemini_search.py
Gemini 2.5 Flash with Google Search grounding — serves two roles:

1. Resolution chain tier: finds articles Claude's web_search may miss
   (different crawl/index pipeline = genuinely independent second index)
2. Fact-checker spot-check: cross-references claims against Google Search
   via a separate LLM to catch hallucinations from the primary pipeline

Requires GOOGLE_AI_API_KEY in .env.
Cost: ~$0.035 per grounded call ($35/1000 requests).
"""

import os
import logging
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Gemini grounding wraps every source URL in this redirect host
GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
# Max time (s) we'll wait on one redirect-follow HEAD before giving up
REDIRECT_TIMEOUT = 3.0
# Max parallel redirect resolutions per _grounded_call
REDIRECT_CONCURRENCY = 8
# In-process cache size for resolved redirects
REDIRECT_CACHE_MAX = 512


class GeminiSearch:
    """Parallel search and verification using Gemini grounded search."""

    # Class-level cache shared across instances — redirects are stable
    _redirect_cache: dict[str, str] = {}
    _redirect_lock = threading.Lock()

    def __init__(self):
        from dotenv import load_dotenv
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_AI_API_KEY", "")
        self._client = None
        if not self.api_key:
            logger.info("[gemini] GOOGLE_AI_API_KEY not set — tier disabled")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self):
        if self._client is None and self.available:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _grounded_call(self, prompt: str, max_tokens: int = 1024) -> dict:
        """Make a single Gemini call with Google Search grounding.
        Returns {"text": str, "sources": list[dict]} or {"error": str}."""
        if not self.available:
            return {"error": "GOOGLE_AI_API_KEY not set"}

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "tools": [{"google_search": {}}],
                    "max_output_tokens": max_tokens,
                },
            )

            text = response.text or ""

            # Extract grounding sources
            sources = []
            metadata = response.candidates[0].grounding_metadata
            if metadata and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    if chunk.web:
                        sources.append({
                            "title": chunk.web.title or "",
                            "url": chunk.web.uri or "",
                        })

            # Canonicalize grounding redirect URLs in parallel so downstream
            # consumers (URL dedup, RSS/GDELT cross-matching) see real article URLs
            self._canonicalize_sources(sources)

            return {"text": text, "sources": sources}

        except Exception as e:
            logger.warning("[gemini] Grounded call failed: %s", e)
            return {"error": str(e)}

    # ── Resolution chain tier ─────────────────────────────────────────

    def search(self, headline: str, freshness_hint: str = "past 24 hours") -> list[dict]:
        """Search for articles matching a headline via Gemini grounded search.
        Used as a tier in the resolution chain.

        Args:
            headline: The pasted headline text
            freshness_hint: Time hint for the search (e.g., "past 24 hours",
                           "past week", "" for no constraint)

        Returns:
            List of dicts with url, title, outlet, summary, match_score, source
        """
        time_clause = f" from the {freshness_hint}" if freshness_hint else ""

        prompt = (
            f"Find the original news article for this headline{time_clause}. "
            f"Return the outlet name, publication date, and a 2-sentence summary "
            f"of the key facts.\n\n"
            f"Headline: {headline[:300]}\n\n"
            f"If you find the article, start your response with FOUND: followed by the details. "
            f"If you cannot find a matching article, start with NOT_FOUND: and explain briefly."
        )

        result = self._grounded_call(prompt, max_tokens=512)
        if "error" in result:
            return []

        text = result["text"]
        sources = result["sources"]

        # If Gemini couldn't find it, return empty
        if text.upper().startswith("NOT_FOUND"):
            return []

        # Build results from grounding sources
        results = []
        for src in sources:
            if src["url"]:
                results.append({
                    "url": src["url"],
                    "title": src["title"],
                    "outlet": self._extract_outlet(src["url"], src["title"]),
                    "summary": text[:500],
                    "match_score": 80.0,
                    "source": "gemini_grounded",
                })

        # If grounding returned no URLs but Gemini said FOUND, still return
        # the synthesis as a result
        if not results and not text.upper().startswith("NOT_FOUND"):
            results.append({
                "url": "",
                "title": headline[:200],
                "outlet": "Unknown (via Gemini)",
                "summary": text[:500],
                "match_score": 60.0,
                "source": "gemini_grounded",
            })

        return results[:5]

    # ── Fact-checker spot-check ────────────────────────────────────────

    def verify_claim(self, claim: str) -> dict:
        """Cross-reference a specific claim against Google Search via Gemini.
        Used by the fact-checker agent for independent verification.

        Returns:
            {
                "verdict": "supported" | "contradicted" | "unverifiable",
                "confidence": float 0-1,
                "evidence": str,
                "sources": list[dict]
            }
        """
        prompt = (
            f"Verify this specific claim using current information:\n\n"
            f'Claim: "{claim[:500]}"\n\n'
            f"Respond in this exact format:\n"
            f"VERDICT: supported OR contradicted OR unverifiable\n"
            f"CONFIDENCE: 0.0 to 1.0\n"
            f"EVIDENCE: One paragraph explaining what you found."
        )

        result = self._grounded_call(prompt, max_tokens=400)
        if "error" in result:
            return {
                "verdict": "unverifiable",
                "confidence": 0.0,
                "evidence": f"Gemini unavailable: {result['error']}",
                "sources": [],
            }

        text = result["text"]
        return {
            "verdict": self._extract_field(text, "VERDICT", "unverifiable"),
            "confidence": self._extract_confidence(text),
            "evidence": self._extract_field(text, "EVIDENCE", text[:300]),
            "sources": result["sources"],
        }

    # ── Helpers ────────────────────────────────────────────────────────

    KNOWN_OUTLETS = {
        "apnews.com": "AP", "reuters.com": "Reuters",
        "bbc.com": "BBC", "bbc.co.uk": "BBC",
        "nytimes.com": "NYT", "washingtonpost.com": "Washington Post",
        "theguardian.com": "Guardian", "politico.com": "Politico",
        "thehill.com": "The Hill", "axios.com": "Axios",
        "cnn.com": "CNN", "nbcnews.com": "NBC News",
        "cbsnews.com": "CBS News", "abcnews.go.com": "ABC News",
        "wsj.com": "WSJ", "bloomberg.com": "Bloomberg",
        "npr.org": "NPR", "aljazeera.com": "Al Jazeera",
    }

    @classmethod
    def _extract_outlet(cls, url: str, title: str) -> str:
        """Best-effort outlet extraction. Gemini grounding returns redirect URLs
        (vertexaisearch.cloud.google.com/...) and puts the real outlet domain in
        the title field, so prefer `title` when `url` is a grounding redirect."""
        from urllib.parse import urlparse

        def _lookup(domain: str) -> str | None:
            domain = domain.lower().replace("www.", "")
            if not domain:
                return None
            if domain in cls.KNOWN_OUTLETS:
                return cls.KNOWN_OUTLETS[domain]
            return domain.split(".")[0].capitalize()

        # Title field from grounding_chunks.web.title is often the outlet domain
        if title:
            hit = _lookup(title.strip())
            if hit and hit != "Unknown":
                return hit

        try:
            domain = urlparse(url).netloc.lower().replace("www.", "")
            if "vertexaisearch.cloud.google.com" in domain or "grounding-api-redirect" in url:
                return "Unknown (via Gemini)"
            return _lookup(domain) or "Unknown"
        except Exception:
            return "Unknown"

    # ── Redirect canonicalization ─────────────────────────────────────

    @classmethod
    def _canonicalize_one(cls, url: str) -> str:
        """Follow a Gemini grounding redirect to its canonical article URL.
        Returns the original URL unchanged for non-redirect hosts or on error."""
        if not url or GROUNDING_REDIRECT_HOST not in url:
            return url

        with cls._redirect_lock:
            if url in cls._redirect_cache:
                return cls._redirect_cache[url]

        resolved = url
        try:
            # HEAD request, let urllib follow redirects. Cheap and doesn't pull
            # the article body — Gemini's redirect host 302s to the real URL.
            req = urllib.request.Request(
                url,
                method="HEAD",
                headers={"User-Agent": "DeepDive/1.0 (+resolution-chain)"},
            )
            with urllib.request.urlopen(req, timeout=REDIRECT_TIMEOUT) as resp:
                final = resp.geturl()
                if final and GROUNDING_REDIRECT_HOST not in final:
                    resolved = final
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            logger.debug("[gemini] Redirect canonicalize failed for %s: %s", url[:80], e)

        with cls._redirect_lock:
            # Cheap LRU: drop oldest entries when full. dict preserves insertion order.
            if len(cls._redirect_cache) >= REDIRECT_CACHE_MAX:
                for old_key in list(cls._redirect_cache.keys())[:REDIRECT_CACHE_MAX // 4]:
                    cls._redirect_cache.pop(old_key, None)
            cls._redirect_cache[url] = resolved

        return resolved

    @classmethod
    def _canonicalize_sources(cls, sources: list[dict]) -> None:
        """Follow all grounding redirects in parallel, updating `url` in-place.
        Sources that aren't grounding redirects pass through untouched."""
        targets = [s for s in sources if s.get("url") and GROUNDING_REDIRECT_HOST in s["url"]]
        if not targets:
            return

        with ThreadPoolExecutor(max_workers=min(REDIRECT_CONCURRENCY, len(targets))) as ex:
            resolved = list(ex.map(lambda s: cls._canonicalize_one(s["url"]), targets))

        for src, final_url in zip(targets, resolved):
            src["url"] = final_url

    @staticmethod
    def _extract_field(text: str, field: str, default: str) -> str:
        """Extract a labeled field from structured Gemini output."""
        import re
        pattern = rf'{field}:\s*(.+?)(?:\n|$)'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return default

    @staticmethod
    def _extract_confidence(text: str) -> float:
        """Extract confidence float from Gemini output."""
        import re
        m = re.search(r'CONFIDENCE:\s*([\d.]+)', text, re.IGNORECASE)
        if m:
            try:
                return max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        return 0.5
