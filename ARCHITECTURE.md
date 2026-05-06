# DeepDive: Architecture and Design Rationale

**Author:** Nathan Humphrey
**Repository:** github.com/mrnathanhumphrey-droid/DeepDive
**Document date:** May 6, 2026

---

## Purpose of this document

This document records the architectural design and reasoning behind DeepDive, a multi-agent research tool for breaking news and policy analysis. The repository at github.com/mrnathanhumphrey-droid/DeepDive contains the implementation. This document explains the design decisions: what each component does, why it exists, and what failure mode it addresses.

The document is dated and authored. The repository is public and timestamped via GitHub commit history. Together they establish the architectural pattern described below as publicly documented original work as of the date above.

---

## Problem statement

LLM-based research tools have a hallucination problem. A single language model asked to research a topic will produce confident, plausible, often-wrong output. The errors are not random — they are systematic in three ways: (1) the model confabulates specific facts (dates, names, statistics) when its training data is sparse on the topic, (2) the model anchors on whichever source it sees first and doesn't cross-check against other sources, and (3) the model has no mechanism to learn from being wrong because each session starts fresh.

Existing solutions partially address each failure mode. Retrieval-augmented generation (RAG) addresses confabulation by grounding output in retrieved documents, but introduces dependence on the retrieval source's accuracy. Fact-checking layers cross-check claims, but typically only against one or two sources. Feedback mechanisms allow corrections in-session, but the corrections evaporate when the session ends.

DeepDive's architecture is designed to address all three failure modes simultaneously, in a system that learns persistently across sessions and degrades gracefully when individual sources fail.

---

## Architectural overview

DeepDive uses a 27-agent pipeline organized in three phases:

**Phase 1 — `run_analysis`:** Topic input is parsed by a deterministic Python classifier (`input_parser.py`) that categorizes the topic as breaking, current, recent, general, or historical. The classifier is pure Python with no LLM involvement, by design (see "Design decision 1" below). The topic is then routed to one of two pipelines: a 19-agent breaking/current/recent/general pipeline, or a 19+8-agent pipeline for topics with historical components. Agents run in parallel (4 workers) and produce structured outputs that feed into a fact-check synthesis.

**Phase 2 — `run_meta_review`:** A MetaAgent reads stored corrections from a local ChromaDB vector store of past user feedback, critiques the Phase 1 outputs against patterns of past errors, and returns a list of agents to re-run with adjusted prompts.

**Phase 3 — `apply_user_corrections`:** User feedback on the synthesized brief is stored as a correction pattern in ChromaDB. The flagged agents re-run with the corrections incorporated. The pattern is persisted for future sessions on similar topics.

---

## Headline resolution chain

Within Phase 1, breaking-news topics go through a five-tier escalation chain before agent dispatch. Each tier is attempted in order; the chain falls through to the next tier when the current tier returns insufficient results.

1. **Failure cache.** The system maintains a cache of topics that have failed resolution recently. If a topic matches a recent failure, the chain skips the failed tier and starts at the next one. This prevents repeated futile lookups against sources that are temporarily down or that consistently fail on certain topic types.

2. **RSS wire feeds.** Direct fetches from authoritative wire services. Wire copy is the closest thing to a reliable primary source for breaking news because it is written by professional journalists with editorial review under deadline.

3. **Twitter / X reverse-anchor lookup.** For breaking news that hasn't reached wire services yet, Twitter often has primary-source posts (officials, witnesses, authoritative accounts) before traditional media catches up. The reverse-anchor lookup searches for tweets that match the topic shape.

4. **Gemini grounded search.** Gemini's web-grounded search is used as a second-opinion cross-check independent of the Anthropic ecosystem. Using a different LLM provider for cross-verification eliminates same-model bias in the resolution.

5. **GDELT.** The Global Database of Events, Language, and Tone is a structured database of news events with machine-readable metadata. For topics that have entered news coverage but where wire feeds and social media are noisy, GDELT provides cleaner structured access.

6. **(Fallback) Claude web search.** The native Claude web search tool is the final fallback when none of the above resolve the topic.

The chain is the load-bearing anti-hallucination mechanism. A topic that fails resolution at one tier may resolve at another. The system never confabulates a resolution — if all tiers fail, the topic is reported as unresolvable rather than synthesized from training data.

---

## Design decisions and rationale

### Design decision 1: The classifier is pure Python, not an LLM

The decision to classify topics into breaking/current/recent/historical mode using a pure-Python classifier rather than an LLM-based classifier is deliberate. LLM-based classifiers cascade errors: a misclassification at the routing stage sends the topic to the wrong pipeline, which then produces output that is internally consistent but addresses the wrong question. Pure-Python classification with explicit rules and JSON marker files (in `data/`) makes the routing decision auditable, deterministic, and debuggable. When a routing error occurs, it can be traced to a specific marker rule and corrected directly.

### Design decision 2: Multi-tier escalation rather than single-source

Single-source research tools fail when their source fails. Multi-source tools that query all sources in parallel produce conflict-resolution problems: which source wins when they disagree? The multi-tier escalation chain is a third path. Each tier is attempted in order of decreasing source authority. The first tier that returns sufficient results is used. This means tier-1 sources (wire feeds) are preferred when available, but the system gracefully degrades to tier-5 sources (Claude web search) when authoritative sources don't have the information yet. The fallthrough is explicit and traceable: every output records which tier resolved it.

### Design decision 3: Cross-provider verification

Tier 4 uses Gemini grounded search rather than another Anthropic-ecosystem tool. The decision is to ensure that at least one tier in the chain is independent of the primary LLM provider. Same-model verification is weak verification: an LLM cross-checking its own output is biased toward agreement. Using Gemini as the second-opinion tier ensures that at least one verification step is genuinely independent.

### Design decision 4: Separate pipelines for breaking and historical

Topics with historical components require different verification machinery than purely current topics. A topic referencing a court arraignment from three years ago needs primary-source historical verification (court records, archived news), causal-chain analysis to connect past events to present implications, and counterfactual analysis to assess what-if alternatives. The 8 additional historical agents (anchor verification, era context, causal chain, scholarly consensus, counterfactuals, ripple timeline, modern impact, primary sources) handle this. Running both pipelines on a hybrid topic and synthesizing the outputs allows the system to handle topics that contain both current and historical components without compromising verification quality on either.

### Design decision 5: Persistent correction learning

Single-session correction loops evaporate when the session ends. A user who corrects an error in session 1 will see the same error in session 2 because the correction wasn't preserved. The MetaAgent + ChromaDB architecture stores corrections as embedded patterns indexed by topic similarity. When a future topic is similar to a topic with a stored correction, the MetaAgent retrieves the correction pattern and uses it to bias agent prompts away from the previous error. The learning is persistent across sessions and across user accounts (ChromaDB is local and per-deployment).

This is the part that genuinely shuts down the hallucination problem at the system level. Single-shot LLM error modes are not eliminated, but they are not repeated. Errors made once become signal for future runs.

### Design decision 6: Parallel agent dispatch with structured outputs

Agents run in parallel rather than serially. Each agent produces structured Pydantic-typed output (defined in `models/schemas.py`). Parallel dispatch means the pipeline's wall-clock latency is dominated by the slowest agent, not by the sum of all agents. Structured output means the synthesis step can compose agent outputs without parsing free text, which would reintroduce hallucination risk. The combination produces a 27-agent pipeline that completes in time comparable to a single-agent system because the agents work simultaneously.

---

## Verification example

A real demonstration of the system's behavior: on the day of the White House Correspondents' Dinner in 2026, the topic was submitted to DeepDive within hours of the event. Twelve hours after the event, the system produced a full structured brief on the topic. The brief included a timeline component that referenced a related arraignment date with the date stated correctly. Date references are a known weak spot for LLM-based research tools because language models confabulate plausible-but-wrong dates with high confidence. Getting the date right at 12-hour latency means the system's primary-source resolution and cross-checking machinery worked correctly: the date was retrieved from an authoritative source rather than confabulated, and was cross-verified before synthesis. This is a falsifiable verification of the architecture's behavior on a real topic.

---

## What this document is for

Three uses:

First, this document records the architectural pattern under the author's name and date so that future readers can identify the original source of the design. The repository commit history establishes when the implementation existed; this document establishes the design rationale. Together they form a public record of the work.

Second, this document lets future contributors understand why the system is built this way. Each design decision has a stated rationale that addresses a specific failure mode. Future modifications can be evaluated against the original reasoning.

Third, this document is a portfolio artifact. The architectural reasoning shown here is the load-bearing thing — anyone can write code, but few can articulate why their architecture is built the way it is, what failure modes each component addresses, and what alternatives were considered. That reasoning is what distinguishes engineering from coding.

---

## Status

Friends-and-family beta as of May 2026. Not open for issues. The design described here is implemented and operational. The system is deployed via Fly.io with optional Cloudflare Access front-end for non-technical testers.

---

— Nathan Humphrey, Annapolis, MD
