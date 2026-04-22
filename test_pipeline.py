"""
Data pipeline logic test for DeepDive.
Mocks all Claude API calls to validate the full flow without spending tokens.
"""
import json
import sys
import os
import shutil
import gc
from unittest.mock import patch, MagicMock
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

# ── Test config override ────────────────────────────────────────────
os.environ["VECTOR_DB_PATH"] = os.path.join(os.path.dirname(__file__), ".chromadb_test")

# ── Helpers ─────────────────────────────────────────────────────────

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def cleanup_test_db():
    """Best-effort cleanup of the test ChromaDB directory."""
    test_db_path = os.path.join(os.path.dirname(__file__), ".chromadb_test")
    gc.collect()
    try:
        if os.path.exists(test_db_path):
            shutil.rmtree(test_db_path, ignore_errors=True)
    except Exception:
        pass


def make_mock_response(text):
    """Create a mock Anthropic API response."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    return mock_resp


# ── Mock API responses ──────────────────────────────────────────────

SPLIT_RESPONSE = json.dumps([
    {"agent_type": "facts", "title": "Economic Data Points", "description": "Key economic indicators", "keywords": ["GDP", "inflation", "employment"]},
    {"agent_type": "context", "title": "Historical Economic Policy", "description": "Past policy decisions", "keywords": ["fiscal policy", "monetary policy"]},
    {"agent_type": "perspectives", "title": "Stakeholder Reactions", "description": "Different viewpoints on the economy", "keywords": ["labor", "corporate", "government"]},
    {"agent_type": "timeline", "title": "Economic Events Timeline", "description": "Chronological economic events", "keywords": ["Q1 2026", "budget", "fed meeting"]},
])

REVIEW_RESPONSE = SPLIT_RESPONSE  # reviewer approves as-is

CONTEXT_SPLIT_RESPONSE = json.dumps({
    "us_context": {
        "title": "US Economic Policy History",
        "description": "American fiscal policy background",
        "keywords": ["Federal Reserve", "US Treasury", "Congress"]
    },
    "world_context": {
        "title": "Global Economic Trends",
        "description": "International economic backdrop",
        "keywords": ["ECB", "World Bank", "emerging markets"]
    }
})

AGENT_ANALYSIS = "This is a detailed analysis with **key findings** and data points. Some claims are reportedly unverified and possibly need further investigation."

FACT_CHECK_RESPONSE = "## Verified Claims\n- GDP data confirmed\n## Flagged\n- Employment figure reportedly uncertain"

SYNTHESIS_RESPONSE = "## Executive Summary\nComprehensive analysis.\n## Key Findings\n- Finding 1\n## Areas of Consensus\n- Agents agree\n## Contradictions\n- None major\n## Assessment\nSolid analysis."

CONTEXT_SYNTHESIS_RESPONSE = "## Unified Background\nUS and global context combined.\n## Intersections\nTrade policy overlap.\n## Divergences\nDomestic vs international focus."

META_REVIEW_RESPONSE = json.dumps({
    "critique": "Overall the analysis is solid. The facts agent provided good data. The perspectives agent could dig deeper into labor impacts. The timeline is comprehensive.",
    "overall_quality": "high",
    "needs_rerun": False,
    "adjustments": []
})

META_REVIEW_WITH_ISSUES = json.dumps({
    "critique": "The facts agent missed key economic data. The perspectives agent needs more anticapitalist analysis.",
    "overall_quality": "medium",
    "needs_rerun": True,
    "adjustments": [
        {"agent_type": "facts", "issue": "Missing GDP data", "guidance": "Include Q1 2026 GDP figures"},
        {"agent_type": "perspectives", "issue": "Weak anticapitalist lens", "guidance": "Emphasize corporate profit extraction"}
    ]
})

USER_CORRECTION_RESPONSE = json.dumps([
    {"agent_type": "timeline", "issue": "Missing 2023 events", "guidance": "Include key events from 2023 fiscal year including budget negotiations and debt ceiling crisis"}
])


# ── Test 1: Schema imports and types ────────────────────────────────

def test_schemas():
    print("\n1. Testing schemas...")
    from models.schemas import AgentType, SubTopic, AgentResult, AnalysisReport

    # All agent types exist
    expected = ["FACTS", "CONTEXT", "CONTEXT_US", "CONTEXT_WORLD", "CONTEXT_SYNTHESIS",
                "PERSPECTIVES", "TIMELINE", "SPLIT_REVIEWER", "FACT_CHECKER",
                "RESEARCH_REVIEW", "GOVERNMENT_DOCS", "META_REVIEW"]
    for t in expected:
        check(f"AgentType.{t} exists", hasattr(AgentType, t))

    # SubTopic creation
    st = SubTopic(title="Test", description="Desc", agent_type=AgentType.FACTS, keywords=["a"])
    check("SubTopic creates", st.title == "Test" and st.agent_type == AgentType.FACTS)

    # AgentResult creation
    ar = AgentResult(agent_type=AgentType.FACTS, sub_topic="Test", content="Content", confidence=0.85)
    check("AgentResult creates", ar.confidence == 0.85)

    # AnalysisReport creation
    report = AnalysisReport(topic="Test Topic")
    check("AnalysisReport creates", report.topic == "Test Topic")


# ── Test 2: Agent imports and structure ─────────────────────────────

def test_agent_imports():
    print("\n2. Testing agent imports...")
    from agents.facts_agent import FactsAgent
    from agents.perspectives_agent import PerspectivesAgent
    from agents.timeline_agent import TimelineAgent
    from agents.us_context_agent import USContextAgent
    from agents.world_context_agent import WorldContextAgent
    from agents.context_agent import ContextSplittingAgent
    from agents.context_synthesis_agent import ContextSynthesisAgent
    from agents.split_reviewer_agent import SplitReviewerAgent
    from agents.fact_checker_agent import FactCheckerAgent
    from agents.research_review_agent import ResearchReviewAgent
    from agents.government_docs_agent import GovernmentDocsAgent
    from agents.meta_agent import MetaAgent, MetaReviewResult

    check("All agents import", True)

    from models.schemas import AgentType
    check("FactsAgent type", FactsAgent.agent_type == AgentType.FACTS)
    check("PerspectivesAgent type", PerspectivesAgent.agent_type == AgentType.PERSPECTIVES)
    check("TimelineAgent type", TimelineAgent.agent_type == AgentType.TIMELINE)
    check("USContextAgent type", USContextAgent.agent_type == AgentType.CONTEXT_US)
    check("WorldContextAgent type", WorldContextAgent.agent_type == AgentType.CONTEXT_WORLD)
    check("ResearchReviewAgent type", ResearchReviewAgent.agent_type == AgentType.RESEARCH_REVIEW)
    check("GovernmentDocsAgent type", GovernmentDocsAgent.agent_type == AgentType.GOVERNMENT_DOCS)

    # Check system prompts exist and contain key terms
    check("FactsAgent has system_prompt", "fact" in FactsAgent.system_prompt.lower())
    check("PerspectivesAgent pluralist", "pluralist" in PerspectivesAgent.system_prompt.lower())
    check("USContextAgent US focus", "united states" in USContextAgent.system_prompt.lower())
    check("WorldContextAgent global focus", "world" in WorldContextAgent.system_prompt.lower())
    check("ResearchReviewAgent peer-reviewed", "peer-reviewed" in ResearchReviewAgent.system_prompt.lower())
    check("GovernmentDocsAgent gov docs", "government" in GovernmentDocsAgent.system_prompt.lower())

    # Global news source priority
    check("USContext prioritizes diverse sources", "diverse international" in USContextAgent.system_prompt.lower())
    check("WorldContext prioritizes diverse sources", "diverse international" in WorldContextAgent.system_prompt.lower())
    check("Perspectives prioritizes diverse sources", "diverse international" in PerspectivesAgent.system_prompt.lower())


# ── Test 3: BaseAgent corrective guidance ───────────────────────────

def test_base_agent_guidance():
    print("\n3. Testing BaseAgent corrective guidance...")
    from agents.base_agent import BaseAgent
    from models.schemas import AgentType

    class TestAgent(BaseAgent):
        agent_type = AgentType.FACTS
        system_prompt = "test"
        def _get_analysis_instruction(self):
            return "Analyze."

    with patch.object(BaseAgent, '__init__', lambda self: None):
        agent = TestAgent()
        agent.client = MagicMock()
        agent.model = "test-model"
        agent.client.messages.create.return_value = make_mock_response(AGENT_ANALYSIS)

        # Without guidance
        result = agent.analyze("topic", "sub_topic", ["kw1"])
        call_args = agent.client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        check("No guidance block when empty", "Corrective guidance" not in prompt)

        # With guidance
        result = agent.analyze("topic", "sub_topic", ["kw1"], corrective_guidance="Fix the GDP data")
        call_args = agent.client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        check("Guidance block injected", "Fix the GDP data" in prompt)
        check("Guidance marked as corrective", "Corrective guidance from quality review" in prompt)

        # Confidence estimation
        check("Confidence < 1.0 with hedge words", result.confidence < 1.0,
              f"got {result.confidence}")
        check("Confidence >= 0.3 floor", result.confidence >= 0.3)


# ── Test 4: Vector store ────────────────────────────────────────────

def test_vector_store():
    print("\n4. Testing vector store...")
    # Clean up any previous test DB
    test_db_path = os.path.join(os.path.dirname(__file__), ".chromadb_test")
    if os.path.exists(test_db_path):
        shutil.rmtree(test_db_path)

    from vector_store import CorrectionStore

    store = CorrectionStore()
    check("CorrectionStore creates", store is not None)
    check("Collection exists", store.collection is not None)

    # Store a correction
    doc_id = store.store_correction(
        topic="US Economy 2026",
        agent_type="facts",
        issue="Missing GDP data",
        original_guidance="Include GDP",
        optimized_guidance="Include Q1 2026 GDP figures with BEA source",
        user_feedback="Need GDP numbers"
    )
    check("Correction stored", doc_id is not None and len(doc_id) > 0)

    # Store another
    doc_id2 = store.store_correction(
        topic="EU Trade Policy",
        agent_type="perspectives",
        issue="Missing labor perspective",
        original_guidance="Add labor",
        optimized_guidance="Include European trade union positions on tariffs",
        user_feedback="What about workers?"
    )
    check("Second correction stored", doc_id2 != doc_id)

    # Query similar
    results = store.query_similar_corrections("US Economy trends", agent_type="facts")
    check("Query returns results", len(results) > 0)
    check("Query finds relevant correction", any("GDP" in str(r) for r in results))

    # Query for multiple agents
    multi = store.query_corrections_for_agents("Economy", ["facts", "perspectives"])
    check("Multi-agent query works", isinstance(multi, dict))

    # Mark effective
    store.mark_effective(doc_id, True)
    all_corrections = store.get_all_corrections()
    updated = [c for c in all_corrections if c["id"] == doc_id]
    check("Mark effective works", len(updated) > 0 and updated[0].get("effective") == "yes")

    # Get all
    all_c = store.get_all_corrections()
    check("Get all returns both", len(all_c) >= 2)

    # Delete
    store.delete_correction(doc_id2)
    after_delete = store.get_all_corrections()
    check("Delete works", len(after_delete) == len(all_c) - 1)

    # Clear
    store.clear_all()
    after_clear = store.get_all_corrections()
    check("Clear all works", len(after_clear) == 0)


# ── Test 5: Meta agent review + optimize + store ────────────────────

def test_meta_agent():
    print("\n5. Testing meta agent...")
    from agents.meta_agent import MetaAgent, MetaReviewResult
    from models.schemas import AgentResult, AgentType

    # Create mock results
    mock_results = [
        AgentResult(agent_type=AgentType.FACTS, sub_topic="Facts", content="Facts content", confidence=0.8),
        AgentResult(agent_type=AgentType.PERSPECTIVES, sub_topic="Perspectives", content="Perspectives content", confidence=0.7),
        AgentResult(agent_type=AgentType.TIMELINE, sub_topic="Timeline", content="Timeline content", confidence=0.9),
        AgentResult(agent_type=AgentType.CONTEXT_SYNTHESIS, sub_topic="Context", content="Context content", confidence=0.75),
    ]
    mock_fact_check = AgentResult(agent_type=AgentType.FACT_CHECKER, sub_topic="Fact Check", content="All verified", confidence=0.9)
    mock_supplementary = {
        "research": AgentResult(agent_type=AgentType.RESEARCH_REVIEW, sub_topic="Research", content="Papers found", confidence=0.8),
        "government": AgentResult(agent_type=AgentType.GOVERNMENT_DOCS, sub_topic="Gov Docs", content="Bills found", confidence=0.7),
    }

    with patch("agents.meta_agent.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        # Test review (high quality, no reruns)
        mock_client.messages.create.return_value = make_mock_response(META_REVIEW_RESPONSE)

        meta = MetaAgent()
        result = meta.review("US Economy", mock_results, mock_fact_check, "Synthesis text", mock_supplementary)

        check("MetaReviewResult type", isinstance(result, MetaReviewResult))
        check("High quality no rerun", not result.needs_rerun)
        check("No adjustments", len(result.adjustments) == 0)
        check("Confidence 0.9 for high", result.confidence == 0.9)
        check("Critique populated", len(result.critique) > 0)

        # Test review with issues
        mock_client.messages.create.return_value = make_mock_response(META_REVIEW_WITH_ISSUES)

        result2 = meta.review("US Economy", mock_results, mock_fact_check, "Synthesis text", mock_supplementary)
        check("Medium quality needs rerun", result2.needs_rerun)
        check("Has 2 adjustments", len(result2.adjustments) == 2)
        check("Agents to rerun list", "facts" in result2.agents_to_rerun)
        check("Get guidance for facts", "GDP" in result2.get_guidance_for("facts"))

        # Test iteration cap
        result3 = meta.review("US Economy", mock_results, mock_fact_check, "Synthesis text",
                              mock_supplementary, iteration=1)
        check("Iteration cap blocks rerun", not result3.needs_rerun)

        # Test optimize_user_corrections
        mock_client.messages.create.return_value = make_mock_response(USER_CORRECTION_RESPONSE)

        mock_summaries = [
            {"agent_type": r.agent_type.value, "sub_topic": r.sub_topic, "confidence": r.confidence}
            for r in mock_results
        ]
        adjustments = meta.optimize_user_corrections(
            "US Economy", "Original critique", "Add 2023 events to timeline", mock_summaries
        )
        check("Optimize returns list", isinstance(adjustments, list))
        check("Has adjustments", len(adjustments) > 0)
        check("Timeline agent targeted", adjustments[0]["agent_type"] == "timeline")
        check("Guidance includes 2023", "2023" in adjustments[0]["guidance"])

        # Test store_corrections
        doc_ids = meta.store_corrections("US Economy", adjustments, "Add 2023 events")
        check("Store returns doc IDs", len(doc_ids) > 0)

    cleanup_test_db()


# ── Test 6: Orchestrator pipeline phases ────────────────────────────

def test_orchestrator_phases():
    print("\n6. Testing orchestrator pipeline phases...")

    # We need to patch at the anthropic module level for all agents
    with patch("agents.base_agent.anthropic") as mock_ba, \
         patch("agents.orchestrator.anthropic") as mock_orch, \
         patch("agents.split_reviewer_agent.anthropic") as mock_sr, \
         patch("agents.context_agent.anthropic") as mock_ca, \
         patch("agents.context_synthesis_agent.anthropic") as mock_cs, \
         patch("agents.fact_checker_agent.anthropic") as mock_fc, \
         patch("agents.meta_agent.anthropic") as mock_ma:

        # Setup all mock clients to return appropriate responses
        def setup_mock(mock_module):
            client = MagicMock()
            mock_module.Anthropic.return_value = client
            return client

        clients = [setup_mock(m) for m in [mock_ba, mock_orch, mock_sr, mock_ca, mock_cs, mock_fc, mock_ma]]

        # Route responses based on prompt content
        def smart_response(**kwargs):
            prompt_text = ""
            messages = kwargs.get("messages", [])
            system = kwargs.get("system", "")
            if messages:
                prompt_text = messages[0].get("content", "")

            if "break it down into 4" in prompt_text:
                return make_mock_response(SPLIT_RESPONSE)
            elif "quality assurance editor" in prompt_text:
                return make_mock_response(REVIEW_RESPONSE)
            elif "split the research into two" in prompt_text:
                return make_mock_response(CONTEXT_SPLIT_RESPONSE)
            elif "context synthesis editor" in prompt_text or "combining two" in prompt_text:
                return make_mock_response(CONTEXT_SYNTHESIS_RESPONSE)
            elif "rigorous fact-checker" in prompt_text:
                return make_mock_response(FACT_CHECK_RESPONSE)
            elif "senior editor synthesizing" in prompt_text:
                return make_mock_response(SYNTHESIS_RESPONSE)
            elif "prompt optimization module" in prompt_text:
                return make_mock_response(USER_CORRECTION_RESPONSE)
            elif "Meta Review Agent" in prompt_text:
                return make_mock_response(META_REVIEW_RESPONSE)
            else:
                return make_mock_response(AGENT_ANALYSIS)

        for client in clients:
            client.messages.create.side_effect = smart_response

        from agents.orchestrator import Orchestrator
        orch = Orchestrator()

        # Phase 1: run_analysis
        progress_calls = []
        def track_progress(agent_type, result):
            progress_calls.append(agent_type.value)

        state = orch.run_analysis("US Economy 2026", progress_callback=track_progress)

        check("State has topic", state["topic"] == "US Economy 2026")
        check("State has sub_topics", len(state["sub_topics"]) == 4)
        check("State has agent_results", len(state["agent_results"]) > 0)
        check("State has fact_check", state["fact_check"] is not None)
        check("State has synthesis", isinstance(state["synthesis"], str) and len(state["synthesis"]) > 0)
        check("State has supplementary", "research" in state["supplementary"])
        check("State has context_detail", "us" in state.get("context_detail", {}))
        check("State has meta_reviews list", state["meta_reviews"] == [])
        check("State has correction_ids list", state["correction_ids"] == [])

        # Verify agents ran
        agent_types_in_results = {r.agent_type.value for r in state["agent_results"]}
        check("Facts agent ran", "facts" in agent_types_in_results)
        check("Perspectives agent ran", "perspectives" in agent_types_in_results)
        check("Timeline agent ran", "timeline" in agent_types_in_results)
        check("Context synthesis ran", "context_synthesis" in agent_types_in_results)

        check("Research supplementary ran", state["supplementary"]["research"] is not None)
        check("Gov docs supplementary ran", state["supplementary"]["government"] is not None)

        # Progress callback fired
        check("Progress tracked agents", len(progress_calls) > 0)

        # Phase 2: run_meta_review
        state = orch.run_meta_review(state, iteration=0)
        check("Meta review added", len(state["meta_reviews"]) == 1)
        check("Meta review is MetaReviewResult",
              hasattr(state["meta_reviews"][0], "critique"))
        check("Meta review has critique", len(state["meta_reviews"][0].critique) > 0)

        # Phase 3: apply_user_corrections
        state = orch.apply_user_corrections(state, "The timeline needs 2023 events")
        check("State still valid after corrections", state["topic"] == "US Economy 2026")
        check("Agent results still populated", len(state["agent_results"]) > 0)
        check("Synthesis still populated", len(state["synthesis"]) > 0)
        check("Correction IDs stored", len(state["correction_ids"]) > 0)

    cleanup_test_db()


# ── Test 7: Dashboard state machine ────────────────────────────────

def test_dashboard_helpers():
    print("\n7. Testing dashboard helper functions...")
    from models.schemas import AgentType, AgentResult, SubTopic

    # Test build_download_report doesn't crash
    from agents.meta_agent import MetaReviewResult

    mock_state = {
        "topic": "Test Topic",
        "sub_topics": [
            SubTopic(title="T1", description="D1", agent_type=AgentType.FACTS),
        ],
        "agent_results": [
            AgentResult(agent_type=AgentType.FACTS, sub_topic="Facts", content="Content", confidence=0.8),
        ],
        "fact_check": AgentResult(agent_type=AgentType.FACT_CHECKER, sub_topic="FC", content="OK", confidence=0.9),
        "synthesis": "Final synthesis",
        "supplementary": {
            "research": AgentResult(agent_type=AgentType.RESEARCH_REVIEW, sub_topic="R", content="Papers", confidence=0.8),
            "government": AgentResult(agent_type=AgentType.GOVERNMENT_DOCS, sub_topic="G", content="Docs", confidence=0.7),
        },
        "meta_reviews": [
            MetaReviewResult(critique="Good", adjustments=[], needs_rerun=False, confidence=0.9),
        ],
        "correction_ids": [],
    }

    # Import and test build_download_report
    # We can't import dashboard directly (it calls st.set_page_config at module level)
    # So we test the logic inline
    topic = mock_state["topic"]
    full_report = f"# DeepDive Analysis: {topic}\n\n"
    for r in mock_state["agent_results"]:
        full_report += f"## {r.agent_type.value.replace('_', ' ').title()} Analysis\n"
        full_report += f"Focus: {r.sub_topic}\nConfidence: {r.confidence:.0%}\n\n"
        full_report += f"{r.content}\n\n---\n\n"
    full_report += f"## Synthesis\n\n{mock_state['synthesis']}\n"

    check("Report builds without error", "# DeepDive Analysis: Test Topic" in full_report)
    check("Report includes agent results", "Facts Analysis" in full_report)
    check("Report includes synthesis", "Final synthesis" in full_report)
    check("Report includes confidence", "80%" in full_report)


# ── Test 8: End-to-end data flow validation ─────────────────────────

def test_data_flow_integrity():
    print("\n8. Testing data flow integrity...")
    from models.schemas import AgentType, SubTopic, AgentResult

    # Simulate the data transformations that happen in the pipeline
    # 1. Topic string -> SubTopics
    sub_topics_raw = json.loads(SPLIT_RESPONSE)
    sub_topics = [SubTopic(**item) for item in sub_topics_raw]
    check("JSON -> SubTopic conversion", len(sub_topics) == 4)
    check("Agent types correct", {st.agent_type for st in sub_topics} == {
        AgentType.FACTS, AgentType.CONTEXT, AgentType.PERSPECTIVES, AgentType.TIMELINE
    })

    # 2. Context split
    context_split = json.loads(CONTEXT_SPLIT_RESPONSE)
    check("Context split has us_context", "us_context" in context_split)
    check("Context split has world_context", "world_context" in context_split)
    check("US context has title", "title" in context_split["us_context"])
    check("World context has keywords", "keywords" in context_split["world_context"])

    # 3. AgentResult creation from analysis
    result = AgentResult(
        agent_type=AgentType.FACTS,
        sub_topic=sub_topics[0].title,
        content=AGENT_ANALYSIS,
        confidence=0.8,
    )
    check("AgentResult links to sub_topic", result.sub_topic == "Economic Data Points")

    # 4. Meta review JSON parsing
    meta_data = json.loads(META_REVIEW_RESPONSE)
    check("Meta review JSON has critique", "critique" in meta_data)
    check("Meta review JSON has quality", "overall_quality" in meta_data)
    check("Meta review JSON has needs_rerun", "needs_rerun" in meta_data)
    check("Meta review JSON has adjustments", "adjustments" in meta_data)

    meta_with_issues = json.loads(META_REVIEW_WITH_ISSUES)
    check("Adjustments have agent_type", all("agent_type" in a for a in meta_with_issues["adjustments"]))
    check("Adjustments have guidance", all("guidance" in a for a in meta_with_issues["adjustments"]))

    # 5. User correction JSON parsing
    corrections = json.loads(USER_CORRECTION_RESPONSE)
    check("User corrections parse", len(corrections) == 1)
    check("Correction has agent_type", corrections[0]["agent_type"] == "timeline")

    # 6. Guidance map construction (as orchestrator does it)
    adjustments = meta_with_issues["adjustments"]
    guidance_map = {a["agent_type"]: a["guidance"] for a in adjustments}
    check("Guidance map built", "facts" in guidance_map and "perspectives" in guidance_map)

    # 7. Agent type filtering (as orchestrator does it)
    primary_types = {"facts", "perspectives", "timeline"}
    agents_to_rerun = set(guidance_map.keys())
    rerun_primary = bool(agents_to_rerun & primary_types)
    check("Primary rerun detection", rerun_primary)

    context_types = {"context_us", "context_world"}
    rerun_context = bool(agents_to_rerun & context_types)
    check("Context rerun detection (none flagged)", not rerun_context)


# ── Run all tests ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("DeepDive Pipeline Logic Test")
    print("=" * 60)

    test_schemas()
    test_agent_imports()
    test_base_agent_guidance()
    test_vector_store()
    test_meta_agent()
    test_orchestrator_phases()
    test_dashboard_helpers()
    test_data_flow_integrity()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
