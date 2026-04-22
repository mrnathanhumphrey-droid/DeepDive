import json
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load_fmt


class ContextSplittingAgent:
    """Splits a context research request into US and World history sub-tasks."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    def split_context(self, topic: str, sub_topic: str, keywords: list[str] = None) -> dict:
        """Split context analysis into US-focused and World-focused prompts."""
        keywords = keywords or []
        keyword_hint = f"\nRelevant keywords: {', '.join(keywords)}" if keywords else ""

        prompt = load_fmt(
            "agents/context_split_prompt_template",
            topic=topic,
            sub_topic=sub_topic,
            keyword_hint=keyword_hint,
        )

        from agents.base_agent import BaseAgent
        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=BaseAgent._date_preamble(),
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        return json.loads(raw)
