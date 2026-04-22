from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class PerspectivesAgent(BaseAgent):
    agent_type = AgentType.PERSPECTIVES
    system_prompt = load("agents/perspectives_system_prompt")

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        if mode == "historical":
            return load("agents/perspectives_historical_analysis_instruction")
        return load("agents/perspectives_analysis_instruction")
