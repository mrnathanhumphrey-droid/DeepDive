import json
import re
import logging
import anthropic
from models.schemas import AgentResult, AgentType
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base class for all DeepDive analysis agents."""

    agent_type: AgentType = None
    system_prompt: str = ""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    ANTI_SYCOPHANCY_DIRECTIVE = load("shared/anti_sycophancy_directive")
    WEB_SEARCH_RECENCY_DIRECTIVE = load("shared/web_search_recency_directive")
    HISTORICAL_SOURCE_DIRECTIVE = load("shared/historical_source_directive")

    def _get_system_prompt(self, topic: str = "", sub_topic: str = "") -> str:
        """Return the system prompt for this agent. Subclasses can override
        to vary the prompt based on topic content (e.g., legal topic detection)."""
        return self.system_prompt

    @staticmethod
    def _date_preamble() -> str:
        """Inject today's date so all agents have a temporal anchor."""
        from datetime import date
        today = date.today()
        return (
            f"\n\nTODAY'S DATE: {today.strftime('%B %d, %Y')} ({today.isoformat()}). "
            f"Use this date to evaluate recency of all sources and events.\n"
        )

    def _call_claude(self, prompt: str, topic: str = "", sub_topic: str = "") -> str:
        system = (self._get_system_prompt(topic, sub_topic)
                  + self.ANTI_SYCOPHANCY_DIRECTIVE
                  + self._date_preamble())
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _log_tool_fallback(self, exc) -> None:
        """Called from the except clauses that fall back from web_search to
        tool-less retries. Captures the Anthropic error body so we can diagnose
        why tool-enabled calls get 400s (rate limits? schema? model?)."""
        body = getattr(exc, "body", None) or getattr(exc, "response", None) or str(exc)
        status = getattr(exc, "status_code", "?")
        cls = type(self).__name__
        logger.warning(
            "[agent=%s] tool call rejected (status=%s) → retrying without tool. Detail: %.800s",
            cls, status, str(body)
        )

    @staticmethod
    def _compute_recency_score(citation: dict, mode: str = "general",
                               anchor_year: int = None) -> float:
        """Compute a 0-1 source appropriateness score from date fields.

        For non-historical modes: 1.0 = published today, 0.0 = older than 2 years.
        For historical mode: scores based on era-appropriateness relative to
        the anchor year. A source from the anchor era scores HIGH, not low.
        """
        from datetime import date as _date
        import re as _re

        today = _date.today()
        date_fields = ["date", "published_date", "publishedAt", "source_date",
                       "publication_date", "ruling_date", "event_date",
                       "document_date"]

        pub = None
        # Try structured date fields first
        for field in date_fields:
            val = citation.get(field, "")
            if not val or not isinstance(val, str):
                continue
            m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', val)
            if m:
                try:
                    pub = _date.fromisoformat(m.group(0))
                    break
                except ValueError:
                    continue

        # Fallback: extract from text
        if not pub:
            text = citation.get("claim_summary", "") + " " + citation.get("source_title", "")
            iso_match = _re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
            if iso_match:
                try:
                    pub = _date.fromisoformat(iso_match.group(0))
                except ValueError:
                    pass

        if not pub:
            return 0.5  # unknown

        # ── Historical mode: era-appropriateness scoring ──
        if mode == "historical" and anchor_year:
            source_year = pub.year
            distance_from_anchor = abs(source_year - anchor_year)
            distance_from_present = abs(today.year - source_year)

            # Sources from the anchor era (within 5 years) score highest
            if distance_from_anchor <= 5:
                return 1.0
            # Established scholarship (10-40 years after anchor) scores well
            elif anchor_year < source_year <= anchor_year + 40:
                return max(0.6, 1.0 - (distance_from_anchor / 80))
            # Modern scholarship (past 10 years) scores well for retrospectives
            elif distance_from_present <= 10:
                return 0.7
            # Sources in between score moderately
            else:
                return 0.5

        # ── Standard mode: recency scoring (existing behavior) ──
        days = max((today - pub).days, 0)
        return max(0.0, min(1.0, 1.0 - (days / 730)))

    @staticmethod
    def _normalize_citation_list(items: list, mode: str = "general",
                                 anchor_year: int = None) -> list[dict]:
        """Ensure every entry is a dict. Adds recency_score and defaults
        relevancy_score if not provided by the agent."""
        normalized = []
        for item in items:
            if isinstance(item, dict):
                # Add recency_score from date fields (mode-aware)
                if "recency_score" not in item:
                    item["recency_score"] = BaseAgent._compute_recency_score(
                        item, mode=mode, anchor_year=anchor_year)
                # Default relevancy_score if agent didn't provide one
                if "relevancy_score" not in item:
                    item["relevancy_score"] = 0.5  # unknown — agent didn't rate
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append({
                    "claim_summary": item,
                    "reason": "returned as plain string by agent",
                    "status": "plausible_unverified",
                    "recency_score": 0.5,
                    "relevancy_score": 0.5,
                })
        return normalized

    @staticmethod
    def _extract_citation_block(content: str, mode: str = "general",
                                anchor_year: int = None) -> tuple[str, list[dict], list[dict]]:
        """Extract the JSON citation block from agent output.
        Returns (prose_content, citations_list, removed_claims_list).
        Strips the citation block from prose so truncation never touches it."""
        # Use greedy match to capture the full JSON block (handles nested braces)
        match = re.search(r'```json\s*(\{.*\})\s*```', content, re.DOTALL)
        if not match:
            return content, [], []
        # Always strip the JSON fence from prose, even if parsing fails
        prose = (content[:match.start()] + content[match.end():]).strip()
        try:
            block = json.loads(match.group(1))
            citations = BaseAgent._normalize_citation_list(
                block.get("citations", []), mode=mode, anchor_year=anchor_year)
            removed = BaseAgent._normalize_citation_list(
                block.get("removed_claims", []), mode=mode, anchor_year=anchor_year)
            for key in ("verified_citations", "downgraded_citations",
                        "fabrication_risk_flags", "upstream_hedged_claims"):
                if key in block:
                    block[key] = BaseAgent._normalize_citation_list(
                        block[key], mode=mode, anchor_year=anchor_year)
                    citations.extend(block[key])
            return prose, citations, removed
        except json.JSONDecodeError as _e:
            logger.warning(
                "Citation block JSON parse failed — citations dropped. "
                "Error: %s | Block preview: %.300s", _e, match.group(1)
            )
            return prose, [], []

    def analyze(self, topic: str, sub_topic: str, keywords: list[str] = None,
                corrective_guidance: str = "", mode: str = "general",
                anchor_year: int = None) -> AgentResult:
        keywords = keywords or []
        keyword_hint = f"\nRelevant keywords: {', '.join(keywords)}" if keywords else ""

        correction_block = ""
        if corrective_guidance:
            correction_block = (
                f"\n\n**IMPORTANT — Corrective guidance from quality review:**\n"
                f"{corrective_guidance}\n"
                f"Address the above issues in this revised analysis.\n\n"
            )

        prompt = (
            f"Analyze the following topic from your specialized perspective.\n\n"
            f"Main topic: {topic}\n"
            f"Your focus area: {sub_topic}{keyword_hint}"
            f"{correction_block}\n\n"
            f"{self._get_analysis_instruction(mode=mode)}"
        )

        raw_content = self._call_claude(prompt, topic=topic, sub_topic=sub_topic)
        prose, citations, removed_claims = self._extract_citation_block(
            raw_content, mode=mode, anchor_year=anchor_year)

        return AgentResult(
            agent_type=self.agent_type,
            sub_topic=sub_topic,
            content=prose,
            confidence=self._estimate_confidence(prose, citations),
            citations=citations,
            removed_claims=removed_claims,
        )

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        raise NotImplementedError

    def _estimate_confidence(self, content: str, citations: list = None) -> float:
        """Estimate confidence from citation statuses and content hedging.
        Penalizes fabrication_risk and plausible_unverified heavily.
        Does NOT reward self-assessed 'verified' tags — high self-confidence
        is not evidence of accuracy."""
        if citations:
            total = max(len(citations), 1)
            fabrication_risk = sum(1 for c in citations if c.get("status") == "fabrication_risk")
            unverified = sum(1 for c in citations if c.get("status") == "plausible_unverified")

            # Fabrication risk is a hard penalty
            if fabrication_risk > 0:
                return max(0.2, 0.4 - (fabrication_risk * 0.1))
            # Unverified claims reduce confidence proportionally
            unverified_ratio = unverified / total
            # Base of 0.6 (not 1.0) — self-assessed "verified" is NOT ground truth
            base = 0.6
            return max(0.3, min(0.85, base - (unverified_ratio * 0.3)))

        hedging = ["might", "possibly", "unclear", "uncertain", "allegedly", "reportedly"]
        hedge_count = sum(1 for word in hedging if word.lower() in content.lower())
        # Hedging is NOT penalized as heavily — honest uncertainty is better than false confidence
        return max(0.4, min(0.75, 0.7 - (hedge_count * 0.05)))
