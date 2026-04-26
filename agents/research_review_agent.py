import re

from agents.base_agent import BaseAgent
from models.schemas import AgentResult, AgentType
from prompts.loader import load


class ResearchReviewAgent(BaseAgent):
    agent_type = AgentType.RESEARCH_REVIEW
    system_prompt = load("agents/research_review_system_prompt")

    # The shared SEARCH_PRIORITY list is news-first (AP/Reuters at the top)
    # because most agents need wire services. For a peer-reviewed lit review
    # that bleeds wire copy into academic citations — override with an
    # academic-only priority before the call.
    ACADEMIC_PRIORITY = (
        "peer-reviewed journals, NBER, SSRN, Brookings, RAND, "
        "Urban Institute, Pew Research, law reviews"
    )
    _SEARCH_PRIORITY_RE = re.compile(r'^SEARCH_PRIORITY:.*$', re.MULTILINE)

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        if mode == "historical":
            return load("agents/research_review_historical_analysis_instruction")
        return load("agents/research_review_analysis_instruction")

    def analyze(self, topic: str, sub_topic: str, keywords: list[str] = None,
                corrective_guidance: str = "", mode: str = "general",
                anchor_year: int = None) -> AgentResult:
        scoped_topic, n = self._SEARCH_PRIORITY_RE.subn(
            f'SEARCH_PRIORITY: {self.ACADEMIC_PRIORITY}', topic)
        if n == 0:
            scoped_topic = f'SEARCH_PRIORITY: {self.ACADEMIC_PRIORITY}\n\n{topic}'
        return super().analyze(
            scoped_topic, sub_topic, keywords=keywords,
            corrective_guidance=corrective_guidance, mode=mode,
            anchor_year=anchor_year,
        )
