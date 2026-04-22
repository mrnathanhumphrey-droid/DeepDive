"""Test citation block extraction and confidence scoring."""
from agents.base_agent import BaseAgent

# Test extraction from typical agent output
test_content = '''Here is my analysis of the topic.

The SPR currently holds approximately 395 million barrels.

```json
{
  "agent": "facts_agent",
  "citations": [
    {"claim_summary": "SPR holds 395M barrels", "source_title": "EIA Weekly Petroleum Status Report", "source_org": "EIA", "source_date": "2024-03", "identifier": "none", "identifier_confirmed": true, "status": "verified"}
  ],
  "removed_claims": [
    {"claim_summary": "SPR capacity is 714M barrels as current inventory", "reason": "Conflated capacity with inventory", "status": "fabrication_risk"}
  ]
}
```'''

prose, citations, removed = BaseAgent._extract_citation_block(test_content)

checks = 0
passed = 0

def check(name, condition):
    global checks, passed
    checks += 1
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")

print("1. Testing citation block extraction...")
check("Prose preserved", "analysis" in prose)
check("JSON block stripped from prose", "```json" not in prose)
check("Citations extracted", len(citations) == 1)
check("Removed claims extracted", len(removed) == 1)
check("Citation status correct", citations[0]["status"] == "verified")
check("Removed reason present", removed[0]["reason"] == "Conflated capacity with inventory")

print("\n2. Testing no-block case...")
prose2, cit2, rem2 = BaseAgent._extract_citation_block("Just plain text with no block")
check("No-block returns original", prose2 == "Just plain text with no block")
check("No-block empty citations", cit2 == [])
check("No-block empty removed", rem2 == [])

print("\n3. Testing malformed JSON block...")
bad = '```json\n{this is not valid json}\n```'
prose3, cit3, rem3 = BaseAgent._extract_citation_block(bad)
check("Malformed returns original content", len(prose3) > 0)
check("Malformed empty citations", cit3 == [])

print("\n4. Testing confidence scoring...")
agent = BaseAgent.__new__(BaseAgent)
score_verified = agent._estimate_confidence("test", citations)
check("Verified citation score = 1.0", score_verified == 1.0)

score_fab = agent._estimate_confidence("test", removed)
check("Fabrication risk score < 0.5", score_fab < 0.5)

score_none = agent._estimate_confidence("This might possibly be unclear", None)
check("Hedge-word fallback works", score_none < 1.0)

score_empty = agent._estimate_confidence("test", [])
check("Empty citations uses hedge fallback", score_empty == 1.0)  # no hedge words in "test"

print("\n5. Testing AgentResult with citation fields...")
from models.schemas import AgentResult, AgentType
result = AgentResult(
    agent_type=AgentType.FACTS,
    sub_topic="test",
    content="test content",
    confidence=0.9,
    citations=[{"claim_summary": "test", "status": "verified"}],
    removed_claims=[{"claim_summary": "bad", "status": "fabrication_risk"}],
)
check("AgentResult has citations", len(result.citations) == 1)
check("AgentResult has removed_claims", len(result.removed_claims) == 1)
check("Citations survive serialization", result.model_dump()["citations"][0]["status"] == "verified")

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {checks - passed} failed out of {checks} checks")
print(f"{'='*50}")
