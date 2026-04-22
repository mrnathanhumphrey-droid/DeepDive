import anthropic
from agents.base_agent import BaseAgent
from models.schemas import AgentResult, AgentType
from prompts.loader import load


class NewsFetchAgent(BaseAgent):
    agent_type = AgentType.NEWS_FETCH
    system_prompt = load("agents/news_fetch_system_prompt")
    BREAKING_SOCIAL_DIRECTIVE = load("shared/breaking_social_sources_directive")

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        return load("agents/news_fetch_analysis_instruction")

    def _call_claude(self, prompt: str, topic: str = "", sub_topic: str = "") -> str:
        """Override to use web search tool for live news retrieval."""
        system = (self._get_system_prompt(topic, sub_topic)
                  + self.ANTI_SYCOPHANCY_DIRECTIVE
                  + self.WEB_SEARCH_RECENCY_DIRECTIVE
                  + self._date_preamble())
        # Inject verified social media sources for breaking topics only
        combined = (topic + " " + sub_topic).lower()
        if ("anchor_event" in combined or "breaking" in combined
                or "verify" in combined or "past 7 days" in combined
                or "past 48 hours" in combined):
            system += "\n" + self.BREAKING_SOCIAL_DIRECTIVE
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
