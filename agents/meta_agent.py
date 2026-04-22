import json
import logging
import re
import anthropic
from models.schemas import AgentResult, AgentType
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from vector_store import CorrectionStore
from prompts.loader import load_fmt

logger = logging.getLogger(__name__)


class MetaReviewResult:
    """Holds the meta agent's critique and prompt adjustments."""

    def __init__(self, critique: str, adjustments: list[dict], needs_rerun: bool,
                 confidence: float, accuracy_verdict: str = "mostly_accurate"):
        self.critique = critique
        self.adjustments = adjustments
        self.needs_rerun = needs_rerun
        self.confidence = confidence
        self.accuracy_verdict = accuracy_verdict

    @property
    def agents_to_rerun(self) -> list[str]:
        return [a["agent_type"] for a in self.adjustments]

    def get_guidance_for(self, agent_type: str) -> str:
        for adj in self.adjustments:
            if adj["agent_type"] == agent_type:
                return adj["guidance"]
        return ""


class MetaAgent:
    """Reviews all pipeline outputs, critiques quality, produces corrective
    prompt adjustments, optimizes corrections from user feedback, and
    stores/retrieves correction patterns from the vector database."""

    MAX_ITERATIONS = 2

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.correction_store = CorrectionStore()

    def _build_past_corrections_context(self, topic: str) -> str:
        all_agent_types = [
            "facts", "perspectives", "timeline", "context_us",
            "context_world", "research_review", "government_docs"
        ]
        past = self.correction_store.query_corrections_for_agents(
            topic, all_agent_types, n_per_agent=2
        )
        if not past:
            return ""

        sections = []
        for agent_type, corrections in past.items():
            for c in corrections:
                sections.append(
                    f"- **{agent_type}**: Issue: {c.get('issue', 'N/A')} | "
                    f"User said: {c.get('user_feedback', 'N/A')} | "
                    f"Fix: {c.get('optimized_guidance', 'N/A')} | "
                    f"Effective: {c.get('effective', 'unknown')}"
                )

        return (
            "\n\n## Past Correction Patterns (from vector database)\n"
            "The following corrections were applied to similar topics previously. "
            "Use these to proactively catch recurring issues:\n\n"
            + "\n".join(sections)
        )

    def review(self, topic: str, agent_results: list[AgentResult],
               fact_check_result: AgentResult, synthesis: str,
               supplementary: dict, iteration: int = 0,
               economics: dict = None,
               verified_evidence: list[dict] = None) -> MetaReviewResult:

        MAX_AGENT_CHARS = 3000
        agent_sections = []
        for r in agent_results:
            content_preview = r.content[:MAX_AGENT_CHARS]
            if len(r.content) > MAX_AGENT_CHARS:
                content_preview += f"\n... [truncated — {len(r.content)} chars total]"
            agent_sections.append(
                f"### {r.agent_type.value} Agent\n"
                f"**Focus:** {r.sub_topic}\n"
                f"**Confidence:** {r.confidence:.0%}\n\n"
                f"{content_preview}"
            )
        agents_combined = "\n\n---\n\n".join(agent_sections)

        MAX_SUPPLEMENTARY_CHARS = 2000
        research_content = supplementary["research"].content if supplementary.get("research") else "N/A"
        gov_content = supplementary["government"].content if supplementary.get("government") else "N/A"
        research_content = research_content[:MAX_SUPPLEMENTARY_CHARS]
        gov_content = gov_content[:MAX_SUPPLEMENTARY_CHARS]

        economics = economics or {}
        econ_data_content = economics["data"].content[:MAX_SUPPLEMENTARY_CHARS] if economics.get("data") else ""
        econ_policy_content = economics["policy"].content[:MAX_SUPPLEMENTARY_CHARS] if economics.get("policy") else ""
        economics_active = bool(econ_data_content or econ_policy_content)

        MAX_SYNTHESIS_CHARS = 4000
        synthesis_preview = synthesis[:MAX_SYNTHESIS_CHARS]
        if len(synthesis) > MAX_SYNTHESIS_CHARS:
            synthesis_preview += f"\n... [truncated — {len(synthesis)} chars total]"

        past_corrections_context = self._build_past_corrections_context(topic)

        verified_evidence_block = ""
        if verified_evidence:
            evidence_items = []
            for ev in verified_evidence:
                evidence_items.append(
                    f"- URL: {ev.get('url', 'N/A')}\n"
                    f"  Status: {ev.get('status', 'unknown')}\n"
                    f"  Content: {ev.get('content', 'N/A')[:1500]}"
                )
            verified_evidence_block = (
                "SEALED VERIFIED EVIDENCE — OVERRIDES ALL AGENT OUTPUTS BELOW.\n"
                "The following source(s) are user-supplied and confirmed. If ANY agent "
                "claim below contradicts this evidence, the evidence is correct and the "
                "agent is wrong. Do not split the difference. Do not hedge. Update your "
                "accuracy verdict to reflect contradictions with this evidence.\n\n"
                + "\n\n".join(evidence_items)
                + "\n\n---\n\n"
            )

        economics_section = ""
        if economics_active:
            economics_section = (
                f"\n## Supplementary: Economic Data Analysis\n{econ_data_content}\n\n"
                f"## Supplementary: Economic Policy Analysis\n{econ_policy_content}\n"
            )

        economics_agent_types = ', "economics_data", "economics_policy"' if economics_active else ""

        prompt = load_fmt(
            "agents/meta_review_prompt_template",
            verified_evidence_block=verified_evidence_block,
            iteration_display=iteration + 1,
            max_iterations=self.MAX_ITERATIONS,
            iteration_note=(
                "Apply the same rigorous accuracy standard as the first pass — "
                "iteration number does not lower the bar."
            ) if iteration > 0 else "",
            topic=topic,
            agents_combined=agents_combined,
            fact_check_content=fact_check_result.content,
            synthesis_preview=synthesis_preview,
            research_content=research_content,
            gov_content=gov_content,
            economics_section=economics_section,
            past_corrections_context=past_corrections_context,
            economics_agent_types=economics_agent_types,
        )

        from agents.base_agent import BaseAgent
        _date = BaseAgent._date_preamble()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=3000,
                system=_date,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            raw = "\n".join(text_parts).strip()
        except (anthropic.BadRequestError, anthropic.APIError) as _e:
            body = getattr(_e, "body", None) or str(_e)
            status = getattr(_e, "status_code", "?")
            logger.warning(
                "[agent=MetaAgent] tool call rejected (status=%s) → retrying without tool. Detail: %.800s",
                status, str(body)
            )
            response = self.client.messages.create(
                model=self.model,
                max_tokens=3000,
                system=_date,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        if data is None:
            data = {
                "critique": raw[:2000] if raw else "Meta review produced no parseable output.",
                "overall_quality": "medium",
                "needs_rerun": False,
                "adjustments": [],
                "accuracy_verdict": "has_errors",
            }

        needs_rerun = data.get("needs_rerun", False) and iteration < self.MAX_ITERATIONS - 1

        return MetaReviewResult(
            critique=data.get("critique", ""),
            adjustments=data.get("adjustments", []) if needs_rerun else [],
            needs_rerun=needs_rerun,
            confidence={"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                data.get("overall_quality", "medium"), 0.6
            ),
            accuracy_verdict=data.get("accuracy_verdict", "mostly_accurate"),
        )

    def optimize_user_corrections(self, topic: str, meta_critique: str,
                                   user_feedback: str,
                                   agent_results: list[dict]) -> list[dict]:
        agent_summary = []
        for r in agent_results:
            agent_summary.append(
                f"- **{r['agent_type']}**: Focus: {r['sub_topic']} | "
                f"Confidence: {r['confidence']:.0%}"
            )
        agents_overview = "\n".join(agent_summary)

        prompt = load_fmt(
            "agents/meta_corrections_prompt_template",
            topic=topic,
            meta_critique=meta_critique,
            agents_overview=agents_overview,
            user_feedback=user_feedback,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        return json.loads(raw)

    def store_corrections(self, topic: str, adjustments: list[dict],
                          user_feedback: str) -> list[str]:
        doc_ids = []
        for adj in adjustments:
            doc_id = self.correction_store.store_correction(
                topic=topic,
                agent_type=adj["agent_type"],
                issue=adj["issue"],
                original_guidance=adj.get("guidance", ""),
                optimized_guidance=adj["guidance"],
                user_feedback=user_feedback,
            )
            doc_ids.append(doc_id)
        return doc_ids
