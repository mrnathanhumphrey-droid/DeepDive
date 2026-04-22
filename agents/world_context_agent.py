from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class WorldContextAgent(BaseAgent):
    agent_type = AgentType.CONTEXT_WORLD
    system_prompt = load("agents/world_context_system_prompt")

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        return load("agents/world_context_analysis_instruction")
