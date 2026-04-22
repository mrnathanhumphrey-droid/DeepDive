import json
import logging
import re
import anthropic
from agents.base_agent import BaseAgent
from models.schemas import AgentResult, AgentType
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load, load_fmt

logger = logging.getLogger(__name__)


class FactCheckerAgent:
    """Reviews agent outputs for factual accuracy before final synthesis.
    Uses Claude's web search tool to verify claims against live sources."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    def review(self, topic: str, results: list[AgentResult]) -> AgentResult:
        """Fact-check all agent results before they go to final synthesis."""
        # Collect all upstream citations and removed_claims before the LLM call
        # so they can be merged back into the output regardless of what the
        # fact-checker's JSON block contains.
        upstream_citations: list[dict] = []
        upstream_removed: list[dict] = []
        for r in results:
            upstream_citations.extend(r.citations)
            upstream_removed.extend(r.removed_claims)

        sections = []
        for r in results:
            citation_summary = ""
            if r.citations:
                citation_summary = "\n**Agent Citation Block:**\n"
                for c in r.citations:
                    summary = c.get("claim_summary", c.get("event_summary",
                              c.get("metric", "")))
                    source = c.get("source_title", c.get("attributed_to",
                             c.get("publishing_agency", "")))
                    status = c.get("status", "unknown")
                    identifier = c.get("identifier", "none")
                    recency = c.get("recency_score", "?")
                    relevancy = c.get("relevancy_score", "?")
                    src_date = c.get("date", "unknown")
                    citation_summary += (
                        f"- {summary} | Source: {source} | "
                        f"ID: {identifier} | Status: {status} | "
                        f"Date: {src_date} | Recency: {recency} | Relevancy: {relevancy}\n"
                    )
            if r.removed_claims:
                citation_summary += "**Removed by agent (fabrication risk):**\n"
                for c in r.removed_claims:
                    summary = c.get("claim_summary", c.get("event_summary", ""))
                    citation_summary += f"- {summary}: {c.get('reason', '')}\n"

            sections.append(
                f"## {r.agent_type.value.title()} Analysis\n"
                f"**Focus:** {r.sub_topic}\n\n"
                f"{r.content}{citation_summary}"
            )
        combined = "\n\n---\n\n".join(sections)

        system_prompt = load("agents/fact_checker_system_prompt") + BaseAgent._date_preamble()
        prompt = load_fmt(
            "agents/fact_checker_prompt_template",
            topic=topic,
            combined=combined,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=6000,
                system=system_prompt,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )
            content_parts = []
            for block in response.content:
                if block.type == "text":
                    content_parts.append(block.text)
            content = "\n".join(content_parts)

        except (anthropic.BadRequestError, anthropic.APIError) as _e:
            body = getattr(_e, "body", None) or str(_e)
            status = getattr(_e, "status_code", "?")
            logger.warning(
                "[agent=FactCheckerAgent] tool call rejected (status=%s) → retrying without tool. Detail: %.800s",
                status, str(body)
            )
            response = self.client.messages.create(
                model=self.model,
                max_tokens=6000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text

        prose, fc_citations, fc_removed = BaseAgent._extract_citation_block(content)

        # Merge: fact-checker's own citations take priority (they may have
        # updated statuses). Upstream citations not already present are appended
        # so nothing is lost if the fact-checker's JSON block is incomplete.
        fc_ids = {c.get("identifier") for c in fc_citations if c.get("identifier")}
        merged_citations = list(fc_citations)
        for c in upstream_citations:
            if not c.get("identifier") or c.get("identifier") not in fc_ids:
                merged_citations.append(c)

        removed_ids = {c.get("identifier") for c in fc_removed if c.get("identifier")}
        merged_removed = list(fc_removed)
        for c in upstream_removed:
            if not c.get("identifier") or c.get("identifier") not in removed_ids:
                merged_removed.append(c)

        return AgentResult(
            agent_type=AgentType.FACT_CHECKER,
            sub_topic="Pre-Synthesis Fact Check",
            content=prose,
            confidence=self._estimate_confidence(prose, merged_citations),
            citations=merged_citations,
            removed_claims=merged_removed,
        )

    def _estimate_confidence(self, content: str, citations: list = None) -> float:
        if citations:
            verified = sum(1 for c in citations if c.get("status") == "verified")
            fabrication = sum(1 for c in citations if c.get("status") == "fabrication_risk")
            if fabrication > 0:
                return max(0.3, 0.5 - (fabrication * 0.1))
            return max(0.4, min(1.0, verified / max(len(citations), 1)))

        hedging = ["might", "possibly", "unclear", "uncertain", "allegedly", "reportedly"]
        hedge_count = sum(1 for word in hedging if word.lower() in content.lower())
        return max(0.3, min(1.0, 1.0 - (hedge_count * 0.1)))
