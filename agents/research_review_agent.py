from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class ResearchReviewAgent(BaseAgent):
    agent_type = AgentType.RESEARCH_REVIEW
    system_prompt = load("agents/research_review_system_prompt")

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        if mode == "historical":
            return load("agents/research_review_historical_analysis_instruction")
        return load("agents/research_review_analysis_instruction")
