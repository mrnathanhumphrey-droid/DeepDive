'use strict'
"""
source_classifier_agent.py
Runs between fact-check and synthesis to verify source temporal relevance.
Uses the temporal_classifier_system_prompt to classify each citation's
recency and flag stale sources before they reach synthesis.
"""

import json
import anthropic
from datetime import date, timedelta
from models.schemas import AgentResult, AgentType
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_HAIKU
from prompts.loader import load


class SourceClassifierAgent:
    """Classifies all citations by temporal relevance and source quality
    before they reach the synthesis stage. Flags stale sources, computes
    aggregate recency/relevancy metrics, and downgrades citations that
    are too old for the topic's temporal mode."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_HAIKU
        self.temporal_prompt = load("agents/temporal_classifier_system_prompt")

    def classify_sources(self, topic: str, agent_results: list[AgentResult],
                         topic_mode: str = "general") -> dict:
        """Classify all citations across agent results.

        Returns a dict with:
          - classified_citations: list of all citations with updated scores
          - stale_count: number of citations flagged as too old for the topic mode
          - avg_recency: average recency score across all citations
          - avg_relevancy: average relevancy score across all citations
          - temporal_warnings: list of specific warnings for synthesis
        """
        today = date.today()
        all_citations = []
        stale_count = 0
        temporal_warnings = []

        # Define staleness thresholds based on topic mode
        staleness_days = {
            "breaking": 7,
            "current": 30,
            "recent": 365,
            "general": 730,
        }
        max_age = staleness_days.get(topic_mode, 730)

        for r in agent_results:
            for c in r.citations:
                entry = dict(c)
                entry["source_agent"] = r.agent_type.value

                # Compute recency from date field if available
                src_date = c.get("date", "unknown")
                if src_date and src_date != "unknown":
                    try:
                        pub = date.fromisoformat(src_date[:10])
                        days_old = (today - pub).days
                        entry["days_old"] = days_old
                        entry["recency_score"] = max(0.0, min(1.0, 1.0 - (days_old / 730)))

                        # Flag as stale if older than threshold
                        if days_old > max_age:
                            entry["stale"] = True
                            stale_count += 1
                            summary = c.get("claim_summary", "")[:60]
                            temporal_warnings.append(
                                f"STALE SOURCE ({days_old}d old, max {max_age}d for {topic_mode}): "
                                f"'{summary}' from {r.agent_type.value}"
                            )
                        else:
                            entry["stale"] = False
                    except (ValueError, TypeError):
                        entry["days_old"] = None
                        entry["stale"] = False
                else:
                    entry["days_old"] = None
                    entry["stale"] = False

                all_citations.append(entry)

        # Compute aggregates
        recency_scores = [c["recency_score"] for c in all_citations
                          if isinstance(c.get("recency_score"), (int, float))]
        relevancy_scores = [c["relevancy_score"] for c in all_citations
                            if isinstance(c.get("relevancy_score"), (int, float))]

        avg_recency = sum(recency_scores) / max(len(recency_scores), 1)
        avg_relevancy = sum(relevancy_scores) / max(len(relevancy_scores), 1)

        # If many citations are stale, add a synthesis-level warning
        if len(all_citations) > 0:
            stale_pct = stale_count / len(all_citations)
            if stale_pct > 0.3:
                temporal_warnings.insert(0,
                    f"WARNING: {stale_count}/{len(all_citations)} citations ({stale_pct:.0%}) "
                    f"are older than the {max_age}-day threshold for mode={topic_mode}. "
                    f"Synthesis should prioritize recent sources and flag dated claims."
                )

        # Use Haiku to batch-classify any undated citations
        undated = [c for c in all_citations if c.get("days_old") is None
                   and c.get("claim_summary")]
        if undated and len(undated) <= 20:
            self._classify_undated_batch(undated)

        return {
            "classified_citations": all_citations,
            "total_citations": len(all_citations),
            "stale_count": stale_count,
            "avg_recency": round(avg_recency, 3),
            "avg_relevancy": round(avg_relevancy, 3),
            "temporal_warnings": temporal_warnings,
        }

    def _classify_undated_batch(self, citations: list):
        """Use Haiku to estimate recency for citations without dates."""
        try:
            batch_text = "\n".join(
                f"{i+1}. {c.get('claim_summary', '')[:100]}"
                for i, c in enumerate(citations[:20])
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system=self.temporal_prompt,
                messages=[{"role": "user", "content": (
                    f"For each numbered claim below, respond with the number and "
                    f"one word: breaking, current, recent, or general.\n\n{batch_text}"
                )}],
            )

            text = response.content[0].text
            for i, c in enumerate(citations[:20]):
                line_num = str(i + 1)
                if f"{line_num}." in text or f"{line_num} " in text:
                    for mode in ["breaking", "current", "recent", "general"]:
                        # Find the mode word near the line number
                        idx = text.find(line_num)
                        if idx >= 0:
                            chunk = text[idx:idx+50].lower()
                            if mode in chunk:
                                mode_to_score = {
                                    "breaking": 0.95,
                                    "current": 0.75,
                                    "recent": 0.45,
                                    "general": 0.2,
                                }
                                c["recency_score"] = mode_to_score[mode]
                                c["recency_classified_by"] = "haiku_batch"
                                break
        except Exception:
            pass  # Silently continue — undated citations keep 0.5 default

    def format_warnings_for_synthesis(self, classification: dict) -> str:
        """Format temporal warnings as a block to inject into synthesis prompt."""
        warnings = classification.get("temporal_warnings", [])
        if not warnings:
            return ""

        lines = ["\n\nSOURCE TEMPORAL ANALYSIS:"]
        lines.append(f"Total citations: {classification['total_citations']}")
        lines.append(f"Stale citations: {classification['stale_count']}")
        lines.append(f"Avg recency score: {classification['avg_recency']}")
        lines.append(f"Avg relevancy score: {classification['avg_relevancy']}")
        lines.append("")
        for w in warnings[:10]:
            lines.append(f"- {w}")
        lines.append("")
        return "\n".join(lines)
