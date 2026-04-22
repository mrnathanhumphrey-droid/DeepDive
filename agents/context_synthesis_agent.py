import anthropic
from models.schemas import AgentResult, AgentType
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load_fmt


class ContextSynthesisAgent:
    """Synthesizes US and World context analyses into a unified context report."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    def synthesize(self, topic: str, us_result: AgentResult, world_result: AgentResult) -> AgentResult:
        """Combine US and World context results into a single context analysis."""
        prompt = load_fmt(
            "agents/context_synthesis_prompt_template",
            topic=topic,
            us_content=us_result.content,
            world_content=world_result.content,
        )

        from agents.base_agent import BaseAgent
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=BaseAgent._date_preamble(),
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        prose, citations, removed = BaseAgent._extract_citation_block(raw)

        # Carry forward all parent citations — context synthesis prose does not
        # always reproduce the citation JSON block, so we merge them in here
        # to ensure no citation is lost through the synthesis step.
        parent_citations = list(us_result.citations) + list(world_result.citations)
        existing_ids = {c.get("identifier") for c in citations if c.get("identifier")}
        for c in parent_citations:
            if not c.get("identifier") or c.get("identifier") not in existing_ids:
                citations.append(c)

        parent_removed = list(us_result.removed_claims) + list(world_result.removed_claims)
        removed_ids = {c.get("identifier") for c in removed if c.get("identifier")}
        for c in parent_removed:
            if not c.get("identifier") or c.get("identifier") not in removed_ids:
                removed.append(c)

        avg_confidence = (us_result.confidence + world_result.confidence) / 2

        return AgentResult(
            agent_type=AgentType.CONTEXT_SYNTHESIS,
            sub_topic=f"Synthesized Context: {us_result.sub_topic} + {world_result.sub_topic}",
            content=prose,
            confidence=avg_confidence,
            citations=citations,
            removed_claims=removed,
        )
