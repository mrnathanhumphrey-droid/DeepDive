import anthropic
from agents.base_agent import BaseAgent
from models.schemas import AgentType
from prompts.loader import load


class FactsAgent(BaseAgent):
    agent_type = AgentType.FACTS
    BREAKING_SOCIAL_DIRECTIVE = load("shared/breaking_social_sources_directive")

    LEGAL_KEYWORDS = {
        "court", "ruling", "decision", "supreme", "circuit", "district",
        "plaintiff", "defendant", "appeal", "precedent", "statute", "constitutional",
        "litigation", "case", "v.", "scotus", "held", "holding", "opinion",
        "concurrence", "dissent", "majority", "plurality", "per curiam",
        "judiciary", "judicial", "injunction", "certiorari", "amicus",
        "overturned", "reversed", "affirmed", "remanded", "chevron",
        "tro", "temporary restraining order", "preliminary injunction",
        "en banc", "remand", "stay", "mandate", "docket", "filed",
        "judge", "magistrate", "panel", "bench",
    }

    BASE_SYSTEM_PROMPT = load("agents/facts_system_prompt")
    LEGAL_ANALYSIS_SUPPLEMENT = load("agents/facts_legal_supplement")

    system_prompt = BASE_SYSTEM_PROMPT

    def _topic_has_legal_content(self, topic: str, sub_topic: str) -> bool:
        combined = f"{topic} {sub_topic}".lower()
        combined_words = set(combined.split())
        single_word = {kw for kw in self.LEGAL_KEYWORDS if " " not in kw}
        multi_word = {kw for kw in self.LEGAL_KEYWORDS if " " in kw}
        return bool(
            combined_words & single_word
            or any(kw in combined for kw in multi_word)
        )

    def _get_system_prompt(self, topic: str = "", sub_topic: str = "") -> str:
        if self._topic_has_legal_content(topic, sub_topic):
            return self.BASE_SYSTEM_PROMPT + self.LEGAL_ANALYSIS_SUPPLEMENT
        return self.BASE_SYSTEM_PROMPT

    def _call_claude(self, prompt: str, topic: str = "", sub_topic: str = "") -> str:
        """Override to use web search for live fact verification."""
        system = (self._get_system_prompt(topic, sub_topic)
                  + self.ANTI_SYCOPHANCY_DIRECTIVE
                  + self.WEB_SEARCH_RECENCY_DIRECTIVE
                  + self._date_preamble())
        # Inject social sources for breaking topics
        combined = (topic + " " + sub_topic).lower()
        if "anchor_event" in combined or "breaking" in combined or "past 7 days" in combined:
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

    def _get_analysis_instruction(self, mode: str = "general") -> str:
        if mode == "historical":
            return load("agents/facts_historical_analysis_instruction")
        return load("agents/facts_analysis_instruction")
