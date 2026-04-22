import json
import anthropic
from models.schemas import AgentResult
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load_fmt


class SourceExtractorAgent:
    """Scans all agent outputs and extracts two categorized source lists:
    1. Most-referenced sources (cited by multiple agents)
    2. Singular critical sources (sole source for a key claim)
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    def _build_structured_citations(self, agent_results: list[AgentResult],
                                     supplementary: dict) -> str:
        all_sources = []
        for r in agent_results:
            if r.citations:
                for c in r.citations:
                    summary = c.get("claim_summary", c.get("event_summary",
                              c.get("metric", "")))
                    source = c.get("source_title", c.get("attributed_to",
                             c.get("publishing_agency", c.get("publication", ""))))
                    source_org = c.get("source_org", c.get("issuing_agency", ""))
                    status = c.get("status", "unknown")
                    all_sources.append(
                        f"- [{r.agent_type.value}] {summary} | "
                        f"Source: {source} ({source_org}) | Status: {status}"
                    )
        for key in ("research", "government"):
            supp = supplementary.get(key)
            if supp and hasattr(supp, 'citations') and supp.citations:
                for c in supp.citations:
                    summary = c.get("claim_summary", c.get("document_title", ""))
                    source = c.get("source_title", c.get("document_title", ""))
                    source_org = c.get("source_org", c.get("issuing_agency", ""))
                    status = c.get("status", "unknown")
                    all_sources.append(
                        f"- [{key}] {summary} | "
                        f"Source: {source} ({source_org}) | Status: {status}"
                    )
        # Include news supplementary citations if available
        news_supp = supplementary.get("news")
        if news_supp and hasattr(news_supp, 'citations') and news_supp.citations:
            for c in news_supp.citations:
                summary = c.get("claim_summary", c.get("event_summary", ""))
                source = c.get("source_title", c.get("attributed_to", ""))
                source_org = c.get("source_org", c.get("publishing_agency", ""))
                status = c.get("status", "unknown")
                all_sources.append(
                    f"- [news] {summary} | "
                    f"Source: {source} ({source_org}) | Status: {status}"
                )

        if all_sources:
            return "## Structured Citation Data (pre-truncation, authoritative)\n" + \
                   "\n".join(all_sources)
        return ""

    def extract_sources(self, topic: str, agent_results: list[AgentResult],
                        fact_check_content: str, synthesis: str,
                        supplementary: dict) -> dict:
        structured_citations = self._build_structured_citations(agent_results, supplementary)

        sections = []
        for r in agent_results:
            max_chars = 8000 if r.agent_type.value in ("research_review", "government_docs") else 6000
            content_slice = r.content[:max_chars]
            if len(r.content) > max_chars:
                content_slice += f"\n... [+{len(r.content) - max_chars} chars]"
            sections.append(f"### {r.agent_type.value} Agent Output\n{content_slice}")

        research_content = supplementary["research"].content[:2000] if supplementary.get("research") else ""
        gov_content = supplementary["government"].content[:2000] if supplementary.get("government") else ""
        combined = "\n\n---\n\n".join(sections)

        prompt = load_fmt(
            "agents/source_extractor_prompt_template",
            topic=topic,
            structured_citations=structured_citations,
            combined=combined,
            fact_check_content=fact_check_content,
            research_content=research_content,
            gov_content=gov_content,
        )

        from agents.base_agent import BaseAgent
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=BaseAgent._date_preamble(),
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"most_referenced": [], "singular_critical": []}
