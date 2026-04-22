from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class EconomicsDataAgent(BaseAgent):
    agent_type = AgentType.ECONOMICS_DATA
    system_prompt = load("agents/economics_data_system_prompt")

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        return load("agents/economics_data_analysis_instruction")
