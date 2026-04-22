import json
import anthropic
from models.schemas import SubTopic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.loader import load_fmt


class SplitReviewerAgent:
    """Reviews the topic split for accuracy and prompt quality before agent dispatch."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL

    def review(self, topic: str, sub_topics: list[SubTopic]) -> list[SubTopic]:
        """Review and potentially revise sub-topic assignments for accuracy."""
        sub_topics_json = json.dumps([st.model_dump() for st in sub_topics], indent=2)

        prompt = load_fmt(
            "agents/split_reviewer_prompt_template",
            topic=topic,
            sub_topics_json=sub_topics_json,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        try:
            data = json.loads(raw)
            return [SubTopic(**item) for item in data]
        except (json.JSONDecodeError, Exception):
            # LLM returned malformed JSON — fall back to original sub-topics
            return sub_topics
