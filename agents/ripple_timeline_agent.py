import anthropic
from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class RippleTimelineAgent(BaseAgent):
    """Builds a chronological record of the anchor event's consequences,
    annotated with causal relationship labels, running strictly forward."""

    agent_type = AgentType.RIPPLE_TIMELINE
    system_prompt = load("agents/ripple_timeline_system_prompt")

    def _call_claude(self, prompt: str, topic: str = "", sub_topic: str = "") -> str:
        system = (self._get_system_prompt(topic, sub_topic)
                  + self.ANTI_SYCOPHANCY_DIRECTIVE
                  + self.HISTORICAL_SOURCE_DIRECTIVE
                  + self._date_preamble())
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                block.text for block in response.content
                if hasattr(block, "text")
            )
        except (anthropic.BadRequestError, anthropic.APIError) as _e:
            self._log_tool_fallback(_e)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        return load("agents/ripple_timeline_analysis_instruction")
