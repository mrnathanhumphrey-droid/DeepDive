from pydantic import BaseModel
from enum import Enum
from typing import Optional


class AgentType(str, Enum):
    FACTS = "facts"
    CONTEXT = "context"
    CONTEXT_US = "context_us"
    CONTEXT_WORLD = "context_world"
    CONTEXT_SYNTHESIS = "context_synthesis"
    PERSPECTIVES = "perspectives"
    TIMELINE = "timeline"
    SPLIT_REVIEWER = "split_reviewer"
    FACT_CHECKER = "fact_checker"
    RESEARCH_REVIEW = "research_review"
    GOVERNMENT_DOCS = "government_docs"
    META_REVIEW = "meta_review"
    PROMPT_ENGINEER = "prompt_engineer"
    ECONOMICS_DATA = "economics_data"
    ECONOMICS_POLICY = "economics_policy"
    NEWS_FETCH = "news_fetch"
    INPUT_PARSER = "input_parser"
    # Historical pipeline agents
    HISTORICAL_ANCHOR = "historical_anchor"
    ERA_CONTEXT = "era_context"
    PRIMARY_SOURCE = "primary_source"
    CAUSAL_CHAIN = "causal_chain"
    MODERN_IMPACT = "modern_impact"
    SCHOLARLY_CONSENSUS = "scholarly_consensus"
    COUNTERFACTUAL = "counterfactual"
    RIPPLE_TIMELINE = "ripple_timeline"


class SubTopic(BaseModel):
    title: str
    description: str
    agent_type: AgentType
    keywords: list[str] = []

    # Parser-injected domain context — populated by split_topic()
    # Agents that check these get domain-precise sub-topics.
    # Agents that ignore them continue working identically.
    domain: str = "general"
    subdomain: str = ""
    high_risk_fields: list[str] = []
    search_priority: list[str] = []
    mode: str = "general"
    date_context: str = ""


class AgentResult(BaseModel):
    agent_type: AgentType
    sub_topic: str
    content: str
    confidence: float = 0.0
    citations: list[dict] = []
    removed_claims: list[dict] = []


class AnalysisReport(BaseModel):
    topic: str
    sub_topics: list[SubTopic] = []
    agent_results: list[AgentResult] = []
    synthesis: str = ""
