import json
import logging
import re

logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor
from agents.base_agent import BaseAgent
from agents.facts_agent import FactsAgent
from agents.context_agent import ContextSplittingAgent
from agents.us_context_agent import USContextAgent
from agents.world_context_agent import WorldContextAgent
from agents.context_synthesis_agent import ContextSynthesisAgent
from agents.perspectives_agent import PerspectivesAgent
from agents.timeline_agent import TimelineAgent
from agents.split_reviewer_agent import SplitReviewerAgent
from agents.fact_checker_agent import FactCheckerAgent
from agents.research_review_agent import ResearchReviewAgent
from agents.government_docs_agent import GovernmentDocsAgent
from agents.meta_agent import MetaAgent
from agents.prompt_engineer_agent import PromptEngineerAgent
from agents.source_extractor_agent import SourceExtractorAgent
from agents.source_classifier_agent import SourceClassifierAgent
from agents.economics_data_agent import EconomicsDataAgent
from agents.economics_policy_agent import EconomicsPolicyAgent
from agents.news_fetch_agent import NewsFetchAgent
from agents.historical_anchor_agent import HistoricalAnchorAgent
from agents.era_context_agent import EraContextAgent
from agents.primary_source_agent import PrimarySourceAgent
from agents.causal_chain_agent import CausalChainAgent
from agents.modern_impact_agent import ModernImpactAgent
from agents.scholarly_consensus_agent import ScholarlyConsensusAgent
from agents.counterfactual_agent import CounterfactualAgent
from agents.ripple_timeline_agent import RippleTimelineAgent
from agents.orchestrator_patches import (
    _extract_date_context,
    _build_verify_query,
    _build_anchor_block,
    _extract_domain_flags,
)
from models.schemas import AgentType, SubTopic, AgentResult, AnalysisReport
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_HAIKU, MAX_CONCURRENT_AGENTS
import anthropic
from prompts.loader import load_fmt
from services.resolution_chain import ResolutionChain


class Orchestrator:
    """Orchestrates the multi-agent analysis pipeline.

    The pipeline is split into phases so the dashboard can pause for
    user interaction between meta review and correction re-runs:

    Phase 1: run_analysis()      — split, review, dispatch all agents, fact-check, synthesize
    Phase 2: run_meta_review()   — meta agent reviews everything, returns critique
    Phase 3: apply_user_corrections() — user feedback → optimized adjustments → re-run → store
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL
        self.facts_agent = FactsAgent()
        self.context_splitter = ContextSplittingAgent()
        self.us_context_agent = USContextAgent()
        self.world_context_agent = WorldContextAgent()
        self.context_synthesizer = ContextSynthesisAgent()
        self.perspectives_agent = PerspectivesAgent()
        self.timeline_agent = TimelineAgent()
        self.split_reviewer = SplitReviewerAgent()
        self.fact_checker = FactCheckerAgent()
        self.research_review_agent = ResearchReviewAgent()
        self.government_docs_agent = GovernmentDocsAgent()
        self.meta_agent = MetaAgent()
        self.prompt_engineer = PromptEngineerAgent()
        self.source_extractor = SourceExtractorAgent()
        self.source_classifier = SourceClassifierAgent()
        self.news_fetch_agent = NewsFetchAgent()
        # Twitter agent — instantiated lazily (requires API key)
        self._twitter_agent = None
        # Resolution chain — instantiated lazily after twitter agent is available
        self._resolution_chain = None
        # Conditional economics pipeline — agents instantiated lazily
        self._economics_data_agent = None
        self._economics_policy_agent = None
        # Historical pipeline agents — instantiated lazily
        self._historical_anchor_agent = None
        self._era_context_agent = None
        self._primary_source_agent = None
        self._causal_chain_agent = None
        self._modern_impact_agent = None
        self._scholarly_consensus_agent = None
        self._counterfactual_agent = None
        self._ripple_timeline_agent = None

    ECONOMICS_KEYWORDS = {
        "economy", "economic", "economics", "gdp", "inflation", "recession",
        "fiscal", "monetary", "trade", "tariff", "tariffs", "tax", "taxes",
        "taxation", "budget", "deficit", "debt", "spending", "stimulus",
        "austerity", "subsidy", "subsidies", "price", "pricing", "cost",
        "market", "markets", "wages", "wage", "employment", "unemployment",
        "labor", "capital", "investment", "productivity", "growth", "inequality",
        "poverty", "wealth", "income", "cbo", "fed", "federal reserve",
        "interest rate", "supply chain", "sanctions", "currency", "dollar",
        "stock", "bond", "commodity", "housing", "rent", "mortgage",
        "privatization", "nationalization", "deregulation", "antitrust",
        "monopoly", "oligopoly", "minimum wage", "universal basic income",
        "ubi", "industrial policy", "free trade", "protectionism",
    }

    def _detect_economics(self, topic: str, sub_topics: list[SubTopic] = None) -> bool:
        """Detect whether the topic requires detailed economic analysis.
        Handles both single-word and multi-word keyword matching."""
        combined = topic.lower()
        if sub_topics:
            for st in sub_topics:
                combined += f" {st.title.lower()} {st.description.lower()} "
                combined += " ".join(kw.lower() for kw in st.keywords)

        # Split keywords into single-word (fast set intersection) and
        # multi-word (substring match)
        single_word_keywords = {
            kw for kw in self.ECONOMICS_KEYWORDS if " " not in kw
        }
        multi_word_keywords = {
            kw for kw in self.ECONOMICS_KEYWORDS if " " in kw
        }

        combined_words = set(combined.split())
        single_matches = len(combined_words & single_word_keywords)
        multi_matches = sum(1 for kw in multi_word_keywords if kw in combined)

        # Require at least 2 keyword matches to avoid false positives
        return (single_matches + multi_matches) >= 2

    @property
    def twitter_agent(self):
        if self._twitter_agent is None:
            try:
                from agents.twitter_fetch_agent import TwitterFetchAgent
                self._twitter_agent = TwitterFetchAgent()
                logger.info("[twitter] Agent initialized successfully")
            except (ValueError, ImportError) as e:
                logger.warning("[twitter] Agent failed to initialize: %s", e)
                self._twitter_agent = False  # Distinguish "failed" from "not yet tried"
        return self._twitter_agent if self._twitter_agent else None

    @property
    def resolution_chain(self):
        if self._resolution_chain is None:
            self._resolution_chain = ResolutionChain(
                twitter_agent=self.twitter_agent,
                news_fetch_agent=self.news_fetch_agent,
            )
        return self._resolution_chain

    @property
    def economics_data_agent(self):
        if self._economics_data_agent is None:
            self._economics_data_agent = EconomicsDataAgent()
        return self._economics_data_agent

    @property
    def economics_policy_agent(self):
        if self._economics_policy_agent is None:
            self._economics_policy_agent = EconomicsPolicyAgent()
        return self._economics_policy_agent

    # ── Historical pipeline agent properties ──────────────────────────

    def _get_historical_agent(self, attr_name, agent_class):
        val = getattr(self, attr_name)
        if val is None:
            val = agent_class()
            setattr(self, attr_name, val)
        return val

    @property
    def historical_anchor_agent(self):
        return self._get_historical_agent("_historical_anchor_agent", HistoricalAnchorAgent)

    @property
    def era_context_agent(self):
        return self._get_historical_agent("_era_context_agent", EraContextAgent)

    @property
    def primary_source_agent(self):
        return self._get_historical_agent("_primary_source_agent", PrimarySourceAgent)

    @property
    def causal_chain_agent(self):
        return self._get_historical_agent("_causal_chain_agent", CausalChainAgent)

    @property
    def modern_impact_agent(self):
        return self._get_historical_agent("_modern_impact_agent", ModernImpactAgent)

    @property
    def scholarly_consensus_agent(self):
        return self._get_historical_agent("_scholarly_consensus_agent", ScholarlyConsensusAgent)

    @property
    def counterfactual_agent(self):
        return self._get_historical_agent("_counterfactual_agent", CounterfactualAgent)

    @property
    def ripple_timeline_agent(self):
        return self._get_historical_agent("_ripple_timeline_agent", RippleTimelineAgent)

    def _is_historical_topic(self, topic: str) -> bool:
        """True for HISTORICAL topics that use the historical pipeline."""
        return "HISTORICAL_ANCHOR:" in topic

    def _extract_anchor_year(self, topic: str) -> int:
        """Extract anchor year from engineered topic header."""
        m = re.search(r'ANCHOR_YEAR:\s*(\d{4})', topic)
        return int(m.group(1)) if m else 0

    # ── Phase 1: Full initial analysis ──────────────────────────────

    def _is_anchored_topic(self, topic: str) -> bool:
        """True for BREAKING/CURRENT topics that need pre-verification news fetch."""
        return "ANCHOR_EVENT:" in topic

    def _is_recency_flagged(self, topic: str) -> bool:
        """True for RECENT topics — news fetch runs in parallel but with
        explicit recency instruction."""
        return "RECENCY_FLAG:" in topic

    # ── Fix 1: Recency probe ──────────────────────────────────────────
    def _recency_probe(self, search_text: str) -> dict:
        """Fast check: is this story from the last 7 days, 30 days, or older?
        Uses a single Haiku call with web search to find the story's age.
        Returns {"recency": "live"|"week"|"month"|"older"|"unknown",
                 "newest_date": str or None}"""
        try:
            from datetime import date as _date
            today = _date.today()
            response = self.client.messages.create(
                model=CLAUDE_MODEL_HAIKU,
                max_tokens=80,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": (
                    f"TODAY IS {today.isoformat()}. "
                    f"Search for this headline and tell me ONLY the publication date "
                    f"of the most recent matching article. "
                    f"Respond with EXACTLY one line in this format: "
                    f"DATE: YYYY-MM-DD\n"
                    f"If you cannot find it, respond: DATE: UNKNOWN\n\n"
                    f"Headline: {search_text[:150]}"
                )}],
            )
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            # Parse the date
            import re as _re
            m = _re.search(r'DATE:\s*(\d{4}-\d{2}-\d{2})', text)
            if m:
                from datetime import timedelta
                pub_date = _date.fromisoformat(m.group(1))
                days_ago = (today - pub_date).days
                if days_ago <= 2:
                    return {"recency": "live", "newest_date": m.group(1)}
                elif days_ago <= 7:
                    return {"recency": "week", "newest_date": m.group(1)}
                elif days_ago <= 30:
                    return {"recency": "month", "newest_date": m.group(1)}
                else:
                    return {"recency": "older", "newest_date": m.group(1)}
        except Exception as _e:
            body = getattr(_e, "body", None) or str(_e)
            status = getattr(_e, "status_code", "?")
            logger.warning(
                "[orchestrator recency probe] web_search call failed (status=%s): %.500s",
                status, str(body)
            )
        return {"recency": "unknown", "newest_date": None}

    def _demote_mode_from_probe(self, topic: str, probe: dict) -> str:
        """Given a recency probe result, adjust the engineered topic's
        DATE_CONTEXT line to match the actual story age."""
        from datetime import date as _date, timedelta
        today = _date.today()
        today_str = today.strftime("%B %d, %Y")
        today_iso = today.isoformat()

        recency = probe.get("recency", "unknown")
        newest = probe.get("newest_date", "")

        if recency == "live":
            new_context = (
                f"TODAY IS {today_str} ({today_iso}). "
                f"LIVE EVENT — search for coverage from the past 48 hours. "
                f"Story published: {newest}. "
                f"Date boundary: {(today - timedelta(hours=48)).isoformat()} to {today_iso}."
            )
            new_mode = "breaking"
        elif recency == "week":
            new_context = (
                f"TODAY IS {today_str} ({today_iso}). "
                f"Search for coverage from the past 7 days. "
                f"Story published: {newest}. "
                f"Date boundary: {(today - timedelta(days=7)).isoformat()} to {today_iso}."
            )
            new_mode = "breaking"
        elif recency == "month":
            boundary = (today - timedelta(days=30)).isoformat()
            new_context = (
                f"TODAY IS {today_str} ({today_iso}). "
                f"Prioritize coverage from the past 30 days. "
                f"Story published: {newest}. "
                f"Date boundary: {boundary} to {today_iso}."
            )
            new_mode = "current"
        elif recency == "older":
            boundary = (today - timedelta(days=730)).isoformat()
            new_context = (
                f"TODAY IS {today_str} ({today_iso}). "
                f"This story is from {newest}. "
                f"Prioritize sources from around that period and any subsequent developments. "
                f"Date boundary: {boundary} to {today_iso}."
            )
            new_mode = "recent"
        else:
            return topic  # unknown — don't modify

        # Replace DATE_CONTEXT line in the engineered topic
        import re as _re
        if "DATE_CONTEXT:" in topic:
            topic = _re.sub(
                r'^DATE_CONTEXT:.*$', f'DATE_CONTEXT: {new_context}',
                topic, count=1, flags=_re.MULTILINE
            )
        return topic

    # ── Fix 2: Retroactive temporal adjustment from news_fetch ────────
    def _extract_recency_from_news(self, news_result) -> str:
        """Analyze news_fetch result to determine the actual recency of the story.
        Returns a temporal note to inject into synthesis/fact-checker."""
        if not news_result or not news_result.content:
            return ""

        from datetime import date as _date, timedelta
        import re as _re
        today = _date.today()
        content = news_result.content

        # Look for dates in the news content (YYYY-MM-DD or Month DD, YYYY)
        iso_dates = _re.findall(r'\b(202[5-9]-\d{2}-\d{2})\b', content)
        month_dates = _re.findall(
            r'((?:January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+\d{1,2},?\s+202[5-9])', content
        )

        all_dates = []
        for d in iso_dates:
            try:
                all_dates.append(_date.fromisoformat(d))
            except ValueError:
                pass
        for d in month_dates:
            try:
                import datetime
                clean = d.replace(",", "")
                parsed = datetime.datetime.strptime(clean, "%B %d %Y").date()
                all_dates.append(parsed)
            except ValueError:
                pass

        if not all_dates:
            return ""

        newest = max(all_dates)
        days_ago = (today - newest).days

        if days_ago <= 7:
            return (
                f"\n\nTEMPORAL NOTE: News search confirms this is a CURRENT story. "
                f"Most recent coverage dated {newest.isoformat()} ({days_ago} days ago). "
                f"Treat as breaking/current event.\n"
            )
        elif days_ago <= 30:
            return (
                f"\n\nTEMPORAL NOTE: News search found coverage dated {newest.isoformat()} "
                f"({days_ago} days ago). This is a RECENT but not breaking story. "
                f"Frame as ongoing/developing rather than breaking news.\n"
            )
        elif days_ago <= 365:
            return (
                f"\n\nTEMPORAL NOTE: The most recent coverage found is from {newest.isoformat()} "
                f"({days_ago} days ago). This story is NOT current — it is from several months ago. "
                f"Do NOT frame as breaking news. Analyze as a historical/recent event and note "
                f"what has happened since.\n"
            )
        else:
            return (
                f"\n\nTEMPORAL NOTE: The most recent coverage found is from {newest.isoformat()} "
                f"(over {days_ago // 365} year(s) ago). This is a HISTORICAL topic. "
                f"Do not present as current. Focus on legacy, outcomes, and subsequent developments.\n"
            )

    def _extract_anchor(self, topic: str) -> str:
        """Extract ONLY the clean event text from ANCHOR_EVENT, stripping all
        subsequent metadata header lines (DATE_CONTEXT, DOMAIN, HIGH_RISK_FIELDS,
        SEARCH_PRIORITY) so the verify query contains a terse, searchable phrase
        rather than a metadata blob."""
        if "ANCHOR_EVENT:" not in topic:
            return ""
        parts = topic.split("ANCHOR_EVENT:", 1)
        raw = parts[1].split("RESEARCH_PROMPT:", 1)[0] if "RESEARCH_PROMPT:" in parts[1] else parts[1]
        # Take only the first non-empty line — that's the event headline.
        # All subsequent lines are metadata keys (DATE_CONTEXT:, DOMAIN:, etc.)
        for line in raw.splitlines():
            line = line.strip()
            if line and not re.match(r'^[A-Z_]+:', line):
                return line
        # Fallback: first line regardless
        return raw.splitlines()[0].strip() if raw.strip() else ""

    def _extract_research_prompt(self, topic: str) -> str:
        """Extract just the RESEARCH_PROMPT portion for agents that don't need
        the full anchored/flagged format."""
        if "RESEARCH_PROMPT:" in topic:
            return topic.split("RESEARCH_PROMPT:", 1)[1].strip()
        if "RECENCY_FLAG:" in topic:
            return topic.split("RECENCY_FLAG:", 1)[1].strip()
        return topic

    def _looks_like_headline(self, text: str) -> bool:
        """Detect if user input looks like a pasted news headline rather than
        a research question or broad topic.

        Headline signals: short (5-25 words), no question mark, contains a verb
        in present tense or past tense news style, mentions a specific actor/entity.
        """
        words = text.split()
        if len(words) < 4 or len(words) > 30:
            return False
        # Questions are research prompts, not headlines
        if "?" in text:
            return False

        lower = text.lower()
        # Headlines use specific news verbs
        headline_verbs = {
            # Present tense
            "halts", "blocks", "signs", "passes", "rejects", "approves",
            "fires", "quits", "dies", "wins", "loses", "strikes", "bans",
            "orders", "warns", "reveals", "launches", "suspends", "overturns",
            "rules", "grants", "denies", "files", "sues", "charges", "arrests",
            "vetoes", "condemns", "announces", "proposes", "demands", "seizes",
            "raids", "sanctions", "imposes", "lifts", "extends", "delays",
            "confirms", "nominates", "impeaches", "indicts", "acquits",
            "convicts", "sentences", "pardons", "extradites", "deports",
            # Civic / political / legal additions
            "resigns", "accuses", "pleads", "testifies", "subpoenas",
            "endorses", "expels", "censures", "investigates", "probes",
            "slams", "unveils", "defeats", "withdraws", "elects",
            "hires", "settles", "appeals", "dismisses", "reinstates",
            # Past tense
            "halted", "blocked", "signed", "passed", "rejected", "approved",
            "fired", "died", "struck", "banned", "ordered", "warned",
            "revealed", "launched", "suspended", "overturned", "ruled",
            "granted", "denied", "filed", "sued", "charged", "arrested",
            "vetoed", "condemned", "announced", "proposed", "demanded",
            "seized", "raided", "sanctioned", "imposed", "lifted",
            "resigned", "accused", "pleaded", "testified", "subpoenaed",
            "endorsed", "expelled", "censured", "investigated", "probed",
            "slammed", "unveiled", "defeated", "withdrew", "elected",
            "hired", "settled", "appealed", "dismissed", "reinstated",
            # Temporal/salience markers
            "temporarily", "permanently", "emergency", "breaking",
        }
        if any(v in lower.split() for v in headline_verbs):
            return True

        # Capitalized proper nouns suggest a headline about a specific entity
        caps = sum(1 for w in words[1:] if w[0].isupper() and w not in {"The", "A", "An", "In", "On", "At", "For", "And", "Or", "But", "With", "From", "To", "By"})
        if caps >= 2:
            return True

        return False

    def _search_headline_as_evidence(self, headline: str,
                                      progress_callback=None) -> list[dict]:
        """Search for an exact news headline using the tiered resolution chain,
        then fall back to Claude web_search if earlier tiers fail.

        Resolution chain order:
          1. Failure cache (instant)
          2. RSS wire feeds (sub-second)
          3. Twitter reverse-anchor (seconds)
          4. Gemini grounded (seconds — independent Google Search index)
          5. GDELT (seconds)
          6. Claude web_search (existing path — Google-backed)
        """
        if progress_callback:
            progress_callback(
                AgentType.NEWS_FETCH,
                AgentResult(
                    agent_type=AgentType.NEWS_FETCH,
                    sub_topic="Searching for headline source...",
                    content=f"Looking up: {headline[:100]}",
                    confidence=0.0,
                )
            )

        # Detect domain for targeted resolution (Twitter tier uses this)
        _parse_result = getattr(self, "last_parse_result", None)
        domain = _parse_result.domain if _parse_result else "general"

        # ── Run resolution chain (tiers 1-5) ──────────────────────────
        chain_result = self.resolution_chain.resolve(
            headline, domain=domain, skip_web_search=True
        )

        if chain_result.resolved:
            logger.info("[headline] Resolved via %s (confidence=%.2f, %dms, tried=%s)",
                        chain_result.tier, chain_result.confidence,
                        chain_result.elapsed_ms, chain_result.tiers_tried)
            if progress_callback:
                progress_callback(
                    AgentType.NEWS_FETCH,
                    AgentResult(
                        agent_type=AgentType.NEWS_FETCH,
                        sub_topic=f"Found via {chain_result.tier}: {chain_result.title[:80]}",
                        content=chain_result.content or chain_result.summary,
                        confidence=chain_result.confidence,
                    )
                )
            return [chain_result.to_evidence(headline)]

        # ── Tier 6: Claude web_search (existing path) ─────────────────
        logger.info("[headline] Chain exhausted (tried %s), falling back to web_search",
                    chain_result.tiers_tried)

        from datetime import date
        today = date.today().strftime("%B %d, %Y")

        try:
            result = self.news_fetch_agent.analyze(
                headline,
                (
                    f"TODAY IS {today}. The user pasted this exact headline as their search input:\n"
                    f'"{headline}"\n\n'
                    f"TASK: Search for this SPECIFIC story. Find the original article or wire "
                    f"service report that matches this headline. Return:\n"
                    f"1. The outlet that published it and the date\n"
                    f"2. The key facts from the article (who, what, when, where)\n"
                    f"3. Any corroborating coverage from other outlets\n\n"
                    f"Search strategy (try ALL of these, not just the first):\n"
                    f"1. Search for the exact headline text\n"
                    f"2. Search for key proper nouns + verbs (e.g. 'FBI agents sue termination')\n"
                    f"3. Search with outlet names: AP, Reuters, CBS, NBC, CNN + key terms\n"
                    f"4. Search for related legal filings if the headline mentions lawsuits or courts\n\n"
                    f"This is a HEADLINE LOOKUP, not a broad topic search. "
                    f"Do NOT conclude the event didn't happen just because one search query returned nothing — "
                    f"try multiple query formulations before giving up."
                ),
                []
            )

            if progress_callback:
                progress_callback(AgentType.NEWS_FETCH, result)

            search_hard_fail_phrases = [
                "no evidence of this event",
                "this event does not appear to have occurred",
                "could not find any coverage",
                "no results were found for this",
                "unable to locate any articles",
            ]
            if (result and result.confidence > 0.2
                    and len(result.content) > 100
                    and not any(p in result.content.lower() for p in search_hard_fail_phrases)):
                # Record success in failure cache for future lookups
                self.resolution_chain.cache.record_success(
                    headline, f"headline_search:{headline[:80]}", result.content[:2000]
                )
                return [{
                    "url": f"headline_search:{headline[:80]}",
                    "content": result.content[:5000],
                    "status": "headline_verified",
                    "injected_by": "headline_lookup",
                    "original_headline": headline,
                    "resolution_tier": "web_search",
                    "tiers_tried": chain_result.tiers_tried + ["web_search"],
                }]
            else:
                # Record failure — cache will manage retry backoff
                self.resolution_chain.cache.record_failure(
                    headline, tier="web_search"
                )
        except Exception:
            self.resolution_chain.cache.record_failure(headline, tier="web_search_error")

        return []

    def _extract_and_prefetch_urls(self, raw_topic: str,
                                    progress_callback=None) -> tuple[str, list[dict]]:
        """Extract URLs from user input and fetch them as seed evidence
        BEFORE the Prompt Engineer runs. If no URLs found, check if the input
        looks like a pasted headline and search for it directly.
        Returns (clean_topic, evidence_list)."""
        import re
        urls = re.findall(r'https?://[^\s\)\"\']+', raw_topic)

        if not urls:
            # No URLs — check if this looks like a pasted headline
            if self._looks_like_headline(raw_topic):
                evidence = self._search_headline_as_evidence(
                    raw_topic, progress_callback
                )
                return raw_topic, evidence
            return raw_topic, []

        clean_topic = re.sub(r'https?://[^\s\)\"\']+', '', raw_topic).strip()
        prefetched = []

        if progress_callback:
            progress_callback(
                AgentType.NEWS_FETCH,
                AgentResult(
                    agent_type=AgentType.NEWS_FETCH,
                    sub_topic=f"Fetching {len(urls)} URL(s) from input...",
                    content="Pre-fetching user-supplied sources",
                    confidence=0.0,
                )
            )

        for url in urls:
            evidence = self._fetch_url_as_evidence(url)
            prefetched.append(evidence)

        return clean_topic, prefetched

    def run_analysis(self, topic: str, progress_callback=None) -> dict:
        """Run the complete analysis pipeline up to (but not including) meta review.

        Step 0: Extract URLs from input and prefetch as seed evidence.
        For current event topics (anchored): runs news fetch FIRST to verify the
        anchor event, then injects verified news into all primary agent prompts.

        Returns a state dict that the dashboard stores in session_state.
        """
        # Step 0: Extract and prefetch any URLs in the raw input
        clean_topic, seed_evidence = self._extract_and_prefetch_urls(
            topic, progress_callback
        )
        # Merge in any URL evidence pre-fetched during engineer_prompt()
        # These are tagged injected_by='headline_lookup' and take priority —
        # they contain real article content fetched before the URL was stripped.
        prefetched_url_ev = getattr(self, "_prefetched_url_evidence", [])
        if prefetched_url_ev:
            for ev in prefetched_url_ev:
                if not any(e.get("url") == ev.get("url") for e in seed_evidence):
                    seed_evidence.insert(0, ev)  # insert at front — highest priority
            self._prefetched_url_evidence = []
        # Also pick up any URLs registered during engineer_prompt()
        pending = getattr(self, "_pending_seed_urls", [])
        if pending:
            for url in pending:
                if not any(e.get("url") == url for e in seed_evidence):
                    evidence = self._fetch_url_as_evidence(url)
                    seed_evidence.append(evidence)
            self._pending_seed_urls = []

        if clean_topic != topic:
            topic = clean_topic

        # ── Historical pipeline branch ──────────────────────────────────
        if self._is_historical_topic(topic):
            return self._run_historical_pipeline(
                topic, seed_evidence, progress_callback
            )

        is_anchored = self._is_anchored_topic(topic)
        anchor_event = self._extract_anchor(topic) if is_anchored else ""
        news_result = None
        anchor_block = ""

        # If headline lookup already found verified evidence, build an anchor block
        # from it so all agents see the sourced article content as ground truth
        headline_evidence = [e for e in seed_evidence if e.get("injected_by") == "headline_lookup"]
        if headline_evidence:
            he = headline_evidence[0]
            fetch_status = he.get("status", "")
            source_line = ""
            if "url_fetched" in fetch_status:
                source_line = f"Fetch method: {fetch_status} | URL: {he.get('url', '')}\n"
            anchor_block = (
                f"\n\nVERIFIED SOURCE — treat as ground truth for this analysis:\n"
                f"Original headline: {he.get('original_headline', '')}\n"
                f"{source_line}"
                f"{he['content'][:2500]}\n\n"
                f"All agents: Your analysis must be grounded in the above verified content. "
                f"Do NOT search for or speculate about whether this event occurred — "
                f"it is confirmed. Do NOT fabricate alternative details. "
                f"If your training knowledge conflicts with the above, the above takes precedence.\n"
            )

        # For anchored topics: run news fetch BEFORE primary agents
        if is_anchored and anchor_event and not headline_evidence:
            if progress_callback:
                progress_callback(
                    AgentType.NEWS_FETCH,
                    AgentResult(
                        agent_type=AgentType.NEWS_FETCH,
                        sub_topic="Verifying anchor event...",
                        content="Searching wire services for the specific event",
                        confidence=0.0,
                    )
                )

            # Use patch helpers for date-anchored verification
            date_context = _extract_date_context(topic)
            verify_query = _build_verify_query(anchor_event, date_context)

            news_result = self.news_fetch_agent.analyze(
                topic, verify_query, []
            )

            if progress_callback:
                progress_callback(AgentType.NEWS_FETCH, news_result)

            # Use patch helper for anchor block with success/failure guard
            anchor_block = _build_anchor_block(news_result, anchor_event)

            # Supplement with Twitter verification for breaking topics
            if self.twitter_agent and anchor_event:
                try:
                    domain_flags = _extract_domain_flags(topic)
                    twitter_domain = domain_flags.get("domain", "general")
                    twitter_hits = self.twitter_agent.fetch_breaking_verification(
                        anchor_event, domain=twitter_domain, hours_back=48
                    )
                    if twitter_hits:
                        twitter_summary = "\n".join(
                            f"- @{t['author_username']}: {t['text'][:150]}"
                            for t in twitter_hits[:5]
                        )
                        anchor_block += (
                            f"\n\nTWITTER/X VERIFICATION ({len(twitter_hits)} posts from verified accounts):\n"
                            f"{twitter_summary}\n"
                        )
                except Exception as e:
                    logger.warning("[twitter] Verification failed for '%s' (domain=%s): %s",
                                   anchor_event[:80], twitter_domain, e)

        # Fix 1: Recency probe for non-anchored breaking topics
        # Before dispatching agents, check if the story is actually recent.
        # If stale, demote the mode and widen the date window.
        _parse_result = getattr(self, "last_parse_result", None)
        if (not is_anchored and not headline_evidence
                and _parse_result and _parse_result.mode == "breaking"):
            _probe_text = (
                _parse_result.clean_topic[:150]
                if _parse_result.clean_topic
                else self._extract_anchor(topic) or topic[:150]
            )
            probe = self._recency_probe(_probe_text)
            if probe["recency"] in ("month", "older"):
                topic = self._demote_mode_from_probe(topic, probe)
                if progress_callback:
                    progress_callback(
                        AgentType.NEWS_FETCH,
                        AgentResult(
                            agent_type=AgentType.NEWS_FETCH,
                            sub_topic=f"Recency check: story is {probe['recency']} ({probe.get('newest_date', '?')})",
                            content=f"Adjusted search window — story published {probe.get('newest_date', 'unknown date')}",
                            confidence=0.0,
                        )
                    )

        # Split topic
        sub_topics = self.split_topic(topic)
        sub_topics = self.review_split(topic, sub_topics)

        # Dispatch all agents concurrently
        context_st = next(
            (st for st in sub_topics if st.agent_type == AgentType.CONTEXT), None
        )

        # Collect all keywords for news search
        all_keywords = []
        for st in sub_topics:
            all_keywords.extend(st.keywords)

        with ThreadPoolExecutor(max_workers=4) as executor:
            primary_future = executor.submit(
                self._run_primary_agents, topic, sub_topics, progress_callback,
                corrective_guidance={
                    at.value: anchor_block for at in [AgentType.FACTS, AgentType.PERSPECTIVES, AgentType.TIMELINE]
                } if anchor_block else None
            )
            context_future = executor.submit(
                self._run_context_pipeline, topic, context_st, progress_callback,
                corrective_guidance={
                    "context_us": anchor_block, "context_world": anchor_block
                } if anchor_block else None
            ) if context_st else None
            supplementary_future = executor.submit(
                self._run_supplementary_agents, topic, sub_topics, progress_callback
            )
            # For non-anchored topics: news runs in parallel
            if not is_anchored:
                is_recency = self._is_recency_flagged(topic)
                # Use terse clean_topic (raw user input, ≤120 chars)
                # instead of the full engineered research prompt
                _clean = getattr(self, "last_parse_result", None)
                _search_slug = (
                    _clean.clean_topic[:120]
                    if _clean and _clean.clean_topic
                    else self._extract_anchor(topic) or topic[:120]
                )
                news_query = (
                    f"Recent developments — past 30 days: {_search_slug}"
                    if is_recency
                    else f"Latest news: {_search_slug}"
                )
                news_future = executor.submit(
                    self.news_fetch_agent.analyze,
                    topic, news_query, all_keywords
                )

            primary_results = primary_future.result()
            context_result, us_result, world_result = (
                context_future.result() if context_future else (None, None, None)
            )
            supplementary = supplementary_future.result()

            if not is_anchored:
                news_result = news_future.result()

        if progress_callback and news_result:
            progress_callback(AgentType.NEWS_FETCH, news_result)

        all_results = primary_results[:]
        if context_result:
            all_results.append(context_result)

        # Conditional economics pipeline
        economics_active = self._detect_economics(topic, sub_topics)
        economics_results = {}
        if economics_active:
            economics_results = self._run_economics_pipeline(
                topic, sub_topics, progress_callback
            )

        # Fact-check
        fact_check_result = self._fact_check(topic, all_results, progress_callback)

        # Source extraction (runs BEFORE synthesis so structured source data
        # can be passed into the synthesizer)
        # Include news_result in supplementary so live URLs appear in Source Analysis
        _supplementary_with_news = dict(supplementary)
        if news_result:
            _supplementary_with_news["news"] = news_result
        source_data = self.source_extractor.extract_sources(
            topic, all_results, fact_check_result.content, "",
            _supplementary_with_news
        )

        # Fix 2: Retroactive temporal adjustment — extract actual story age
        # from news_fetch results and inject a temporal note into synthesis.
        temporal_note = self._extract_recency_from_news(news_result)

        # Source classification — verify temporal relevance of all citations
        # before they reach synthesis. Flags stale sources and computes metrics.
        _parse_result = getattr(self, "last_parse_result", None)
        _topic_mode = _parse_result.mode if _parse_result else "general"
        source_classification = self.source_classifier.classify_sources(
            topic, all_results, topic_mode=_topic_mode
        )
        source_warnings = self.source_classifier.format_warnings_for_synthesis(
            source_classification
        )
        if source_warnings:
            temporal_note = (temporal_note or "") + source_warnings

        # Synthesize (receives source data for inline attribution + news)
        synthesis = self._synthesize(
            topic, all_results, fact_check_result, source_data, news_result,
            temporal_note=temporal_note
        )

        return {
            "topic": topic,
            "sub_topics": sub_topics,
            "context_sub_topic": context_st,
            "agent_results": all_results,
            "fact_check": fact_check_result,
            "synthesis": synthesis,
            "source_data": source_data,
            "supplementary": supplementary,
            "news": news_result,
            "economics": economics_results,
            "economics_active": economics_active,
            "source_classification": source_classification,
            "context_detail": {"us": us_result, "world": world_result} if context_st else {},
            "verified_evidence": seed_evidence,
            "meta_reviews": [],
            "correction_ids": [],
        }

    # ── Historical pipeline ──────────────────────────────────────────

    def _run_historical_pipeline(self, topic: str, seed_evidence: list,
                                  progress_callback=None) -> dict:
        """Run the complete historical analysis pipeline.

        Sequencing:
          Stage 1 (gate):     HistoricalAnchorAgent — verify anchor event
          Stage 2 (parallel): EraContext + PrimarySource + ScholarlyConsensus
          Stage 3 (sequential): CausalChainAgent (needs era context)
          Stage 4 (parallel): ModernImpact + Counterfactual (need causal chain)
          Stage 5 (parallel): RippleTimeline + existing agents in historical mode
          Stage 6:            Fact-check → source extraction → synthesis
        """
        anchor_year = self._extract_anchor_year(topic)
        mode = "historical"

        # ── Stage 1: Anchor verification (sequential gate) ──────────
        if progress_callback:
            progress_callback(
                AgentType.HISTORICAL_ANCHOR,
                AgentResult(agent_type=AgentType.HISTORICAL_ANCHOR,
                            sub_topic="Verifying historical anchor event...",
                            content="Establishing foundational record",
                            confidence=0.0))

        anchor_result = self.historical_anchor_agent.analyze(
            topic, "Verify the historical anchor event",
            mode=mode, anchor_year=anchor_year)

        if progress_callback:
            progress_callback(AgentType.HISTORICAL_ANCHOR, anchor_result)

        # Gate check: if confidence is too low, halt
        if anchor_result.confidence < 0.3:
            return {
                "topic": topic,
                "mode": "historical",
                "anchor_year": anchor_year,
                "sub_topics": [],
                "agent_results": [anchor_result],
                "fact_check": None,
                "synthesis": (
                    "**Historical anchor could not be verified with sufficient confidence.**\n\n"
                    f"The anchor verification agent returned confidence {anchor_result.confidence:.2f}. "
                    "Please provide more specific information about the historical event "
                    "(exact name, year, or key actors) to enable analysis."
                ),
                "source_data": {},
                "supplementary": {},
                "news": None,
                "economics": {},
                "economics_active": False,
                "source_classification": {},
                "context_detail": {},
                "verified_evidence": seed_evidence,
                "meta_reviews": [],
                "correction_ids": [],
            }

        # Build anchor block for injection into all downstream agents
        anchor_block = (
            f"\n\nVERIFIED HISTORICAL ANCHOR — treat as foundational ground truth:\n"
            f"{anchor_result.content[:3000]}\n\n"
            f"All agents: Your analysis must be grounded in this verified anchor. "
            f"All causation flows FORWARD from this event. Do NOT imply this event "
            f"was caused by anything that came after it.\n"
        )

        all_results = [anchor_result]

        # ── Stage 2: Parallel foundation (era + primary + scholarly) ──
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_AGENTS) as executor:
            era_future = executor.submit(
                self.era_context_agent.analyze,
                topic + anchor_block,
                "Reconstruct the era at the time of the anchor event",
                mode=mode, anchor_year=anchor_year)
            primary_future = executor.submit(
                self.primary_source_agent.analyze,
                topic + anchor_block,
                "Identify key primary source documents",
                mode=mode, anchor_year=anchor_year)
            scholarly_future = executor.submit(
                self.scholarly_consensus_agent.analyze,
                topic + anchor_block,
                "Map the scholarly consensus and historiographic debate",
                mode=mode, anchor_year=anchor_year)

            era_result = era_future.result()
            primary_result = primary_future.result()
            scholarly_result = scholarly_future.result()

        for r in [era_result, primary_result, scholarly_result]:
            if progress_callback:
                progress_callback(r.agent_type, r)
            all_results.append(r)

        # ── Stage 3: Causal chain (sequential — needs era context) ──
        causal_context = (
            f"{anchor_block}\n\n"
            f"ERA CONTEXT (for causal chain grounding):\n"
            f"{era_result.content[:2000]}\n"
        )
        if progress_callback:
            progress_callback(
                AgentType.CAUSAL_CHAIN,
                AgentResult(agent_type=AgentType.CAUSAL_CHAIN,
                            sub_topic="Tracing causal chain forward...",
                            content="Mapping cause-effect from anchor to present",
                            confidence=0.0))

        causal_result = self.causal_chain_agent.analyze(
            topic + causal_context,
            "Trace cause-effect chain from anchor event to present",
            mode=mode, anchor_year=anchor_year)

        if progress_callback:
            progress_callback(AgentType.CAUSAL_CHAIN, causal_result)
        all_results.append(causal_result)

        # ── Stage 4: Modern impact + counterfactual (parallel, need chain) ──
        chain_context = (
            f"{anchor_block}\n\n"
            f"CAUSAL CHAIN (for modern impact and counterfactual grounding):\n"
            f"{causal_result.content[:2500]}\n"
        )

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_AGENTS) as executor:
            modern_future = executor.submit(
                self.modern_impact_agent.analyze,
                topic + chain_context,
                "Connect the causal chain to present-day conditions",
                mode=mode, anchor_year=anchor_year)
            counterfactual_future = executor.submit(
                self.counterfactual_agent.analyze,
                topic + anchor_block,
                "Identify pivotal decision points and alternative trajectories",
                mode=mode, anchor_year=anchor_year)
            ripple_future = executor.submit(
                self.ripple_timeline_agent.analyze,
                topic + chain_context,
                "Build annotated chronological timeline of consequences",
                mode=mode, anchor_year=anchor_year)
            # Existing agents in historical mode
            perspectives_future = executor.submit(
                self.perspectives_agent.analyze,
                topic + anchor_block,
                "Historical and evolving perspectives on the event",
                mode=mode, anchor_year=anchor_year)
            gov_docs_future = executor.submit(
                self.government_docs_agent.analyze,
                topic + anchor_block,
                "Original government documents and subsequent modifications",
                mode=mode, anchor_year=anchor_year)
            research_future = executor.submit(
                self.research_review_agent.analyze,
                topic + anchor_block,
                "Scholarly literature on the event and its consequences",
                mode=mode, anchor_year=anchor_year)

            modern_result = modern_future.result()
            counterfactual_result = counterfactual_future.result()
            ripple_result = ripple_future.result()
            perspectives_result = perspectives_future.result()
            gov_docs_result = gov_docs_future.result()
            research_result = research_future.result()

        for r in [modern_result, counterfactual_result, ripple_result,
                  perspectives_result, gov_docs_result, research_result]:
            if progress_callback:
                progress_callback(r.agent_type, r)
            all_results.append(r)

        supplementary = {
            "research": research_result,
            "government": gov_docs_result,
        }

        # ── Stage 5: Fact-check ──
        fact_check_result = self._fact_check(topic, all_results, progress_callback)

        # ── Stage 6: Source extraction + synthesis ──
        source_data = self.source_extractor.extract_sources(
            topic, all_results, fact_check_result.content, "",
            supplementary)

        source_classification = self.source_classifier.classify_sources(
            topic, all_results, topic_mode="historical")
        source_warnings = self.source_classifier.format_warnings_for_synthesis(
            source_classification)
        temporal_note = source_warnings or ""

        # Historical synthesis uses the dedicated template
        synthesis = self._synthesize_historical(
            topic, all_results, fact_check_result, source_data,
            anchor_result, temporal_note)

        # Economics pipeline (conditional, same as standard)
        economics_active = self._detect_economics(topic)
        economics_results = {}
        if economics_active:
            econ_data = self.economics_data_agent.analyze(
                topic, "Economic data analysis", mode=mode, anchor_year=anchor_year)
            econ_policy = self.economics_policy_agent.analyze(
                topic, "Economic policy analysis", mode=mode, anchor_year=anchor_year)
            economics_results = {"data": econ_data, "policy": econ_policy}
            all_results.extend([econ_data, econ_policy])

        return {
            "topic": topic,
            "mode": "historical",
            "anchor_year": anchor_year,
            "sub_topics": [],
            "agent_results": all_results,
            "fact_check": fact_check_result,
            "synthesis": synthesis,
            "source_data": source_data,
            "supplementary": supplementary,
            "news": None,
            "economics": economics_results,
            "economics_active": economics_active,
            "source_classification": source_classification,
            "context_detail": {
                "era": era_result,
                "primary_source": primary_result,
                "causal_chain": causal_result,
                "modern_impact": modern_result,
                "counterfactual": counterfactual_result,
                "scholarly_consensus": scholarly_result,
                "ripple_timeline": ripple_result,
            },
            "verified_evidence": seed_evidence,
            "meta_reviews": [],
            "correction_ids": [],
        }

    def _synthesize_historical(self, topic, all_results, fact_check_result,
                                source_data, anchor_result, temporal_note=""):
        """Synthesize historical pipeline results using the historical template."""
        combined = "\n\n---\n\n".join(
            f"## {r.agent_type.value.replace('_', ' ').title()} Agent\n{r.content}"
            for r in all_results
        )
        source_index = ""
        if source_data:
            most_ref = source_data.get("most_referenced", [])
            if most_ref:
                source_index = "Most-Referenced Sources:\n" + "\n".join(
                    f"- {s.get('name', 'Unknown')} ({s.get('type', '')})"
                    for s in most_ref[:10]
                )

        anchor_section = (
            f"## Verified Historical Anchor\n{anchor_result.content[:2000]}\n\n"
        )

        prompt = load_fmt(
            "orchestrator/synthesize_historical_prompt_template",
            topic=topic,
            anchor_section=anchor_section,
            combined=combined[:12000],
            fact_check_content=fact_check_result.content[:3000],
            source_index=source_index,
        )
        if temporal_note:
            prompt += f"\n\nTEMPORAL NOTES:\n{temporal_note}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # ── Phase 2: Meta review ────────────────────────────────────────

    def run_meta_review(self, state: dict, iteration: int = 0,
                        progress_callback=None) -> dict:
        """Run the meta agent review on current state. Returns updated state
        with meta_review added. The dashboard shows this to the user."""
        meta_result = self.meta_agent.review(
            state["topic"],
            state["agent_results"],
            state["fact_check"],
            state["synthesis"],
            state["supplementary"],
            iteration,
            economics=state.get("economics", {}),
            verified_evidence=state.get("verified_evidence", []),
        )

        if progress_callback:
            progress_callback(
                AgentType.META_REVIEW,
                AgentResult(
                    agent_type=AgentType.META_REVIEW,
                    sub_topic=f"Meta Review (Iteration {iteration + 1})",
                    content=meta_result.critique,
                    confidence=meta_result.confidence,
                )
            )

        state["meta_reviews"].append(meta_result)
        return state

    # ── Phase 3: User corrections → optimize → re-run → store ──────

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        """Extract URLs from user correction text."""
        import re
        return re.findall(r'https?://[^\s\)\"\']+', text)

    def _prefetch_url_as_anchor(self, url: str, date_context: str = "") -> dict | None:
        """Fetch a user-supplied news URL as verified anchor evidence.

        This runs BEFORE the Prompt Engineer and BEFORE any agents, so that
        all downstream agents receive the article content as ground truth rather
        than having to re-discover the story from scratch.

        Priority order:
          1. Direct HTTP fetch (works for open-access outlets)
          2. Anthropic web_search with the exact URL + date context (paywall fallback)
          3. web_search with the slug-derived headline (last resort)

        Returns a dict tagged injected_by='headline_lookup' so the existing
        anchor-block builder in run_analysis picks it up automatically.
        Returns None if all fetch strategies fail.
        """
        import httpx
        from urllib.parse import urlparse
        from datetime import date as _date

        today_str = _date.today().isoformat()
        # Derive a clean human-readable headline from the URL slug
        path = urlparse(url).path
        segments = [s for s in path.strip("/").split("/") if s and not s.isdigit()]
        slug = segments[-1] if segments else ""
        # Strip trailing date stamp (e.g. "-2026-03-13")
        import re as _re
        slug = _re.sub(r"-\d{4}-\d{2}-\d{2}$", "", slug)
        slug_headline = slug.replace("-", " ").strip()
        outlet = urlparse(url).netloc.lstrip("www.")

        # ── Strategy 1: direct HTTP ───────────────────────────────────────
        try:
            resp = httpx.get(
                url, timeout=12, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DeepDive/1.0)"},
            )
            text = resp.text
            # Strip obvious HTML tags for readability
            text = _re.sub(r"<[^>]+>", " ", text)
            text = _re.sub(r"\s{3,}", "\n", text).strip()
            if len(text) > 600:  # paywall pages are usually very short
                return {
                    "url": url,
                    "content": f"SOURCE: {outlet}\nURL: {url}\n\n{text[:5000]}",
                    "status": "url_fetched_direct",
                    "injected_by": "headline_lookup",
                    "original_headline": slug_headline.title(),
                }
        except Exception:
            pass

        # ── Strategy 2: web_search via Haiku with exact URL ───────────────
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL_HAIKU,
                max_tokens=600,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": (
                    f"TODAY IS {today_str}. "
                    f"Fetch or search for the article at this exact URL and return "
                    f"the key facts: outlet, publication date, headline, and the main "
                    f"factual content (who did what, when, where, what ruling/action).\n\n"
                    f"URL: {url}\n\n"
                    f"If the URL is paywalled, search for: \"{slug_headline}\" "
                    f"and return the same facts from any matching wire service report.\n\n"
                    f"Return plain text only — no JSON, no markdown headers."
                )}],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            ).strip()
            if text and len(text) > 150:
                return {
                    "url": url,
                    "content": f"SOURCE: {outlet}\nURL: {url}\n\n{text}",
                    "status": "url_fetched_search",
                    "injected_by": "headline_lookup",
                    "original_headline": slug_headline.title(),
                }
        except Exception:
            pass

        # ── Strategy 3: slug-only search (last resort) ────────────────────
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL_HAIKU,
                max_tokens=400,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": (
                    f"TODAY IS {today_str}. "
                    f"Search for this news story and return the outlet, date, and "
                    f"key facts in plain text:\n\"{slug_headline}\""
                )}],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            ).strip()
            if text and len(text) > 100:
                return {
                    "url": url,
                    "content": f"SOURCE: {outlet}\nURL: {url}\n\n{text}",
                    "status": "url_fetched_slug_search",
                    "injected_by": "headline_lookup",
                    "original_headline": slug_headline.title(),
                }
        except Exception:
            pass

        return None

    def _fetch_url_as_evidence(self, url: str) -> dict:
        """Fetch a user-supplied URL as verified evidence.
        Tries direct HTTP fetch first, falls back to web search for the story."""
        import httpx

        # Try direct fetch first
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0 (compatible; DeepDive/1.0)"})
            content = resp.text[:5000]
            # Check for paywall/login redirect (short content = probably blocked)
            if len(content) > 500:
                return {
                    "url": url,
                    "content": content,
                    "status": "user_verified",
                    "injected_by": "user_correction",
                }
        except Exception:
            pass

        # Direct fetch failed or hit paywall — search for same story via wire services
        try:
            # Extract a search query from the URL path
            from urllib.parse import urlparse
            path_words = urlparse(url).path.replace("-", " ").replace("/", " ").strip()
            search_query = path_words if len(path_words) > 10 else url

            result = self.news_fetch_agent.analyze(
                search_query,
                f"Find news coverage of this story (original URL: {url}): {search_query}",
                []
            )
            return {
                "url": url,
                "content": result.content[:3000],
                "status": "user_verified",
                "injected_by": "user_correction",
            }
        except Exception:
            return {
                "url": url,
                "content": f"[Could not fetch content from {url}]",
                "status": "user_supplied_unfetched",
                "injected_by": "user_correction",
            }

    def apply_user_corrections(self, state: dict, user_feedback: str,
                                progress_callback=None) -> dict:
        """Take user's free-text feedback, optimize into prompt adjustments,
        re-run flagged agents, re-do fact-check and synthesis, and store
        corrections in the vector database.

        URLs in user feedback are extracted and fetched as verified evidence
        that overrides agent outputs — they bypass the prompt optimization
        layer and inject directly into the meta review evidence layer.

        Returns updated state with new results."""
        topic = state["topic"]
        latest_review = state["meta_reviews"][-1] if state["meta_reviews"] else None
        meta_critique = latest_review.critique if latest_review else ""

        # Step 0: Extract URLs from user feedback and fetch as evidence
        urls = self._extract_urls(user_feedback)
        verified_evidence = []
        if urls:
            if progress_callback:
                progress_callback(
                    AgentType.NEWS_FETCH,
                    AgentResult(
                        agent_type=AgentType.NEWS_FETCH,
                        sub_topic=f"Fetching {len(urls)} user-supplied source(s)...",
                        content="Retrieving URLs as verified evidence",
                        confidence=0.0,
                    )
                )
            for url in urls:
                evidence = self._fetch_url_as_evidence(url)
                verified_evidence.append(evidence)

        # Store verified evidence on state for meta review access
        if verified_evidence:
            state.setdefault("verified_evidence", []).extend(verified_evidence)

        # Step 1: Optimize user feedback into targeted adjustments
        agent_summaries = [
            {"agent_type": r.agent_type.value,
             "sub_topic": r.sub_topic,
             "confidence": r.confidence}
            for r in state["agent_results"]
        ]
        adjustments = self.meta_agent.optimize_user_corrections(
            topic, meta_critique, user_feedback, agent_summaries
        )

        if not adjustments and not verified_evidence:
            # User approved or feedback didn't map to specific agents
            return state

        # If we have verified evidence but no adjustments, force a fact-check re-run
        if not adjustments and verified_evidence:
            adjustments = [{"agent_type": "facts", "guidance":
                "User provided verified source URL(s) that may contradict current analysis. "
                "Re-examine all claims against the verified evidence."}]

        # Step 2: Store corrections in vector DB
        correction_ids = self.meta_agent.store_corrections(
            topic, adjustments, user_feedback
        )
        state["correction_ids"].extend(correction_ids)

        if progress_callback:
            agent_names = ", ".join(a["agent_type"] for a in adjustments)
            progress_callback(
                AgentType.META_REVIEW,
                AgentResult(
                    agent_type=AgentType.META_REVIEW,
                    sub_topic=f"Applying corrections to: {agent_names}",
                    content=f"Re-running with optimized prompts",
                    confidence=0.0,
                )
            )

        # Step 3: Re-run flagged agents
        new_results, new_supplementary, new_us, new_world, new_economics = (
            self._rerun_flagged_agents(
                topic, state["sub_topics"], state["context_sub_topic"],
                state["agent_results"], state["supplementary"],
                adjustments, progress_callback,
                previous_economics=state.get("economics", {}),
            )
        )

        state["agent_results"] = new_results
        state["supplementary"] = new_supplementary
        if new_economics:
            state["economics"] = new_economics
        if new_us and state.get("context_detail"):
            state["context_detail"]["us"] = new_us
        if new_world and state.get("context_detail"):
            state["context_detail"]["world"] = new_world

        # Step 4: Re-run fact-check and synthesis only if primary results changed
        SYNTHESIS_AFFECTING_TYPES = {
            "facts", "perspectives", "timeline",
            "context_us", "context_world",
        }
        flagged_types = {a["agent_type"] for a in adjustments}

        if flagged_types & SYNTHESIS_AFFECTING_TYPES:
            state["fact_check"] = self._fact_check(
                topic, new_results, progress_callback
            )
            # Re-extract sources before re-synthesis
            state["source_data"] = self.source_extractor.extract_sources(
                topic, new_results, state["fact_check"].content,
                "", new_supplementary
            )
            state["synthesis"] = self._synthesize(
                topic, new_results, state["fact_check"], state["source_data"]
            )
        # If only supplementary or economics agents were corrected,
        # fact-check and synthesis are unchanged — skip the re-run

        return state

    def extract_sources(self, state: dict) -> dict:
        """Return source data from state (already extracted pre-synthesis).
        Re-extracts only if source_data is missing (backwards compatibility)."""
        if state.get("source_data"):
            return state["source_data"]
        return self.source_extractor.extract_sources(
            state["topic"],
            state["agent_results"],
            state["fact_check"].content,
            state["synthesis"],
            state["supplementary"],
        )

    def generate_tangential_topics(self, topic: str, sub_topics: list) -> dict:
        """Generate tangential topics for each sub-topic breakdown.
        Returns {agent_type_value: [{"summary": str, "search_term": str}, ...]}
        """
        sub_topic_descriptions = "\n".join(
            f"- {st.agent_type.value}: {st.title} — {st.description}"
            for st in sub_topics
        )

        prompt = load_fmt(
            "orchestrator/tangential_topics_prompt_template",
            topic=topic,
            sub_topic_descriptions=sub_topic_descriptions,
        )

        response = self.client.messages.create(
            model=CLAUDE_MODEL_HAIKU,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def approve_output(self, state: dict):
        """User approved the output. No corrections needed."""
        # Nothing to do — corrections are already stored if any were applied.
        pass

    # ── Internal agent runners ──────────────────────────────────────

    def engineer_prompt(self, raw_topic: str) -> str:
        """Extract user-supplied URLs from raw input, pre-fetch them as anchor
        evidence using web_search (handles paywalls), then pass the topic to
        the Prompt Engineer.

        URLs are fetched HERE — before the Prompt Engineer strips them from the
        input — so all downstream agents receive the article content as verified
        ground truth rather than re-discovering the story from scratch.
        """
        seed_urls = self.prompt_engineer.get_seed_urls(raw_topic)
        if seed_urls:
            # Pre-fetch every URL now, tagged as headline_lookup so the anchor
            # block builder in run_analysis picks them up automatically.
            prefetched = []
            for url in seed_urls:
                evidence = self._prefetch_url_as_anchor(url)
                if evidence:
                    prefetched.append(evidence)
                else:
                    # Fallback: register for the weaker _fetch_url_as_evidence path
                    self._pending_seed_urls = (
                        getattr(self, "_pending_seed_urls", []) + [url]
                    )
            if prefetched:
                self._prefetched_url_evidence = (
                    getattr(self, "_prefetched_url_evidence", []) + prefetched
                )
        # Store ParseResult for QC logging (not displayed in dashboard)
        self.last_parse_result = self.prompt_engineer.get_parse_result(raw_topic)
        return self.prompt_engineer.engineer_prompt(raw_topic)

    def split_topic(self, engineered_topic: str) -> list[SubTopic]:
        # Strip ANCHOR_EVENT/RECENCY_FLAG prefix so LLM sees only research content
        clean = self._extract_research_prompt(engineered_topic)

        prompt = load_fmt("orchestrator/split_topic_prompt_template", clean_topic=clean)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        data = json.loads(raw)
        return [SubTopic(**item) for item in data]

    def review_split(self, topic: str, sub_topics: list[SubTopic]) -> list[SubTopic]:
        return self.split_reviewer.review(topic, sub_topics)

    def _run_primary_agents(self, topic: str, sub_topics: list[SubTopic],
                            progress_callback=None,
                            corrective_guidance: dict = None) -> list[AgentResult]:
        corrective_guidance = corrective_guidance or {}
        results = []
        non_context = [st for st in sub_topics if st.agent_type != AgentType.CONTEXT]

        agent_map = {
            AgentType.FACTS: self.facts_agent,
            AgentType.PERSPECTIVES: self.perspectives_agent,
            AgentType.TIMELINE: self.timeline_agent,
        }

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_AGENTS) as executor:
            futures = {}
            for st in non_context:
                agent = agent_map.get(st.agent_type)
                if agent:
                    guidance = corrective_guidance.get(st.agent_type.value, "")
                    future = executor.submit(
                        agent.analyze, topic, st.title, st.keywords, guidance
                    )
                    futures[future] = st.agent_type

            for future in futures:
                result = future.result()
                results.append(result)
                if progress_callback:
                    progress_callback(futures[future], result)

        return results

    def _run_context_pipeline(self, topic: str, context_sub_topic: SubTopic,
                              progress_callback=None,
                              corrective_guidance: dict = None) -> tuple:
        corrective_guidance = corrective_guidance or {}

        context_split = self.context_splitter.split_context(
            topic, context_sub_topic.title, context_sub_topic.keywords
        )

        us_info = context_split["us_context"]
        world_info = context_split["world_context"]
        us_guidance = corrective_guidance.get("context_us", "")
        world_guidance = corrective_guidance.get("context_world", "")

        with ThreadPoolExecutor(max_workers=2) as executor:
            us_future = executor.submit(
                self.us_context_agent.analyze,
                topic, us_info["title"], us_info.get("keywords", []), us_guidance
            )
            world_future = executor.submit(
                self.world_context_agent.analyze,
                topic, world_info["title"], world_info.get("keywords", []), world_guidance
            )
            us_result = us_future.result()
            world_result = world_future.result()

        if progress_callback:
            progress_callback(AgentType.CONTEXT_US, us_result)
            progress_callback(AgentType.CONTEXT_WORLD, world_result)

        context_result = self.context_synthesizer.synthesize(topic, us_result, world_result)

        if progress_callback:
            progress_callback(AgentType.CONTEXT_SYNTHESIS, context_result)

        return context_result, us_result, world_result

    def _run_supplementary_agents(self, topic: str, sub_topics: list[SubTopic],
                                   progress_callback=None,
                                   corrective_guidance: dict = None) -> dict:
        corrective_guidance = corrective_guidance or {}
        all_keywords = []
        for st in sub_topics:
            all_keywords.extend(st.keywords)

        research_guidance = corrective_guidance.get("research_review", "")
        gov_guidance = corrective_guidance.get("government_docs", "")

        with ThreadPoolExecutor(max_workers=2) as executor:
            research_future = executor.submit(
                self.research_review_agent.analyze,
                topic, f"Peer-Reviewed Research: {topic}", all_keywords, research_guidance
            )
            gov_future = executor.submit(
                self.government_docs_agent.analyze,
                topic, f"Government Documents: {topic}", all_keywords, gov_guidance
            )
            research_result = research_future.result()
            gov_result = gov_future.result()

        if progress_callback:
            progress_callback(AgentType.RESEARCH_REVIEW, research_result)
            progress_callback(AgentType.GOVERNMENT_DOCS, gov_result)

        return {"research": research_result, "government": gov_result}

    def _run_economics_pipeline(self, topic: str, sub_topics: list[SubTopic],
                                progress_callback=None,
                                corrective_guidance: dict = None) -> dict:
        """Conditionally run economics data and policy agents in parallel."""
        corrective_guidance = corrective_guidance or {}
        all_keywords = []
        for st in sub_topics:
            all_keywords.extend(st.keywords)

        data_guidance = corrective_guidance.get("economics_data", "")
        policy_guidance = corrective_guidance.get("economics_policy", "")

        with ThreadPoolExecutor(max_workers=2) as executor:
            data_future = executor.submit(
                self.economics_data_agent.analyze,
                topic, f"Economic Data & Indicators: {topic}",
                all_keywords, data_guidance
            )
            policy_future = executor.submit(
                self.economics_policy_agent.analyze,
                topic, f"Economic Policy Analysis: {topic}",
                all_keywords, policy_guidance
            )
            data_result = data_future.result()
            policy_result = policy_future.result()

        if progress_callback:
            progress_callback(AgentType.ECONOMICS_DATA, data_result)
            progress_callback(AgentType.ECONOMICS_POLICY, policy_result)

        return {"data": data_result, "policy": policy_result}

    def _fact_check(self, topic: str, results: list[AgentResult],
                    progress_callback=None) -> AgentResult:
        fact_check_result = self.fact_checker.review(topic, results)
        if progress_callback:
            progress_callback(AgentType.FACT_CHECKER, fact_check_result)
        return fact_check_result

    def _synthesize(self, topic: str, results: list[AgentResult],
                    fact_check_result: AgentResult,
                    source_data: dict = None,
                    news_result: AgentResult = None,
                    temporal_note: str = "") -> str:
        MAX_AGENT_CHARS_SYNTHESIS = 4000  # ~1000 tokens per agent — broader source coverage

        sections = []
        for r in results:
            content_preview = r.content[:MAX_AGENT_CHARS_SYNTHESIS]
            if len(r.content) > MAX_AGENT_CHARS_SYNTHESIS:
                content_preview += "\n... [truncated for synthesis — full content available in agent tabs]"

            # Append structured citation summary so synthesis has source data
            # even after prose truncation
            citation_note = ""
            if r.citations:
                verified = [c for c in r.citations if c.get("status") == "verified"]
                unverified = [c for c in r.citations if c.get("status") == "plausible_unverified"]
                if verified:
                    citation_note += "\n\n**Verified Sources:**\n"
                    for c in verified[:25]:
                        summary = c.get("claim_summary", c.get("event_summary", c.get("metric", "")))
                        source = c.get("source_title", c.get("attributed_to", c.get("publishing_agency", "")))
                        citation_note += f"- {summary} — {source}\n"
                if unverified:
                    citation_note += "\n**Unverified Claims (use with hedging):**\n"
                    for c in unverified[:15]:
                        summary = c.get("claim_summary", c.get("event_summary", ""))
                        citation_note += f"- {summary}\n"
            if r.removed_claims:
                citation_note += "\n**Removed (fabrication risk — do NOT include):**\n"
                for c in r.removed_claims[:10]:
                    summary = c.get("claim_summary", c.get("event_summary", c.get("metric", "")))
                    citation_note += f"- {summary}: {c.get('reason', '')}\n"

            sections.append(
                f"## {r.agent_type.value.replace('_', ' ').title()} Analysis\n"
                f"**Focus:** {r.sub_topic}\n"
                f"**Confidence:** {r.confidence:.0%}\n\n"
                f"{content_preview}{citation_note}"
            )

        combined = "\n\n---\n\n".join(sections)

        # Breaking news section — prepended for highest attention priority
        news_section = ""
        if news_result and news_result.content:
            news_preview = news_result.content[:2000]
            # Use temporal_note to adjust the framing — if the story is old,
            # don't label it "BREAKING NEWS"
            if temporal_note and ("NOT current" in temporal_note or "HISTORICAL" in temporal_note):
                news_section = f"""
## NEWS CONTEXT
{news_preview}
{temporal_note}
---

"""
            else:
                news_section = f"""
## BREAKING NEWS — HIGHEST RECENCY PRIORITY
{news_preview}
{temporal_note}
SYNTHESIS INSTRUCTION: If any item above contradicts or updates a claim in the
analysis below, the news item takes precedence. Flag the contradiction explicitly
rather than silently resolving it. Do not omit developments from the past 72 hours.

---

"""
        elif temporal_note:
            # No news result but we have temporal context to inject
            news_section = f"{temporal_note}\n---\n\n"

        prompt = load_fmt(
            "orchestrator/synthesize_prompt_template",
            topic=topic,
            news_section=news_section,
            combined=combined,
            fact_check_content=fact_check_result.content,
            source_index=self._format_source_index(source_data) if source_data else "No structured source data available.",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    @staticmethod
    def _format_source_index(source_data: dict) -> str:
        """Format source extraction data as a concise index for the synthesizer."""
        lines = []
        most_ref = source_data.get("most_referenced", [])
        if most_ref:
            lines.append("**Most-Referenced Sources (use for inline attribution):**")
            for s in most_ref[:10]:
                agents = ", ".join(s.get("referenced_by", []))
                lines.append(f"- {s.get('name', '')} ({s.get('type', '')}) — "
                           f"cited by: {agents}")
        singular = source_data.get("singular_critical", [])
        if singular:
            lines.append("\n**Singular Critical Sources (flag if unverified):**")
            for s in singular[:8]:
                lines.append(f"- {s.get('name', '')} — sole source for: "
                           f"{s.get('claim', '')} [{s.get('agent', '')}]")
        return "\n".join(lines) if lines else "No sources extracted."

    def _rerun_flagged_agents(self, topic: str, sub_topics: list[SubTopic],
                               context_sub_topic, previous_results: list[AgentResult],
                               previous_supplementary: dict,
                               adjustments: list[dict],
                               progress_callback=None,
                               previous_economics: dict = None) -> tuple:
        guidance_map = {a["agent_type"]: a["guidance"] for a in adjustments}
        agents_to_rerun = set(guidance_map.keys())

        primary_types = {"facts", "perspectives", "timeline"}
        context_types = {"context_us", "context_world"}
        supplementary_types = {"research_review", "government_docs"}
        economics_types = {"economics_data", "economics_policy"}

        rerun_primary = bool(agents_to_rerun & primary_types)
        rerun_context = bool(agents_to_rerun & context_types)
        rerun_supplementary = bool(agents_to_rerun & supplementary_types)
        rerun_economics = bool(agents_to_rerun & economics_types)

        new_results = list(previous_results)
        new_supplementary = dict(previous_supplementary)
        new_economics = dict(previous_economics) if previous_economics else {}
        us_result = None
        world_result = None

        if rerun_primary:
            primary_guidance = {k: v for k, v in guidance_map.items() if k in primary_types}
            flagged_sub_topics = [
                st for st in sub_topics if st.agent_type.value in primary_guidance
            ]

            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_AGENTS) as executor:
                agent_map = {
                    AgentType.FACTS: self.facts_agent,
                    AgentType.PERSPECTIVES: self.perspectives_agent,
                    AgentType.TIMELINE: self.timeline_agent,
                }
                futures = {}
                for st in flagged_sub_topics:
                    agent = agent_map.get(st.agent_type)
                    if agent:
                        guidance = primary_guidance.get(st.agent_type.value, "")
                        future = executor.submit(
                            agent.analyze, topic, st.title, st.keywords, guidance
                        )
                        futures[future] = st.agent_type

                for future in futures:
                    result = future.result()
                    new_results = [
                        r for r in new_results if r.agent_type != futures[future]
                    ]
                    new_results.append(result)
                    if progress_callback:
                        progress_callback(futures[future], result)

        if rerun_context and context_sub_topic:
            context_result, us_result, world_result = self._run_context_pipeline(
                topic, context_sub_topic, progress_callback,
                corrective_guidance=guidance_map
            )
            new_results = [
                r for r in new_results if r.agent_type != AgentType.CONTEXT_SYNTHESIS
            ]
            new_results.append(context_result)

        if rerun_supplementary:
            new_supplementary = self._run_supplementary_agents(
                topic, sub_topics, progress_callback,
                corrective_guidance=guidance_map
            )

        if rerun_economics:
            new_economics = self._run_economics_pipeline(
                topic, sub_topics, progress_callback,
                corrective_guidance=guidance_map
            )

        return new_results, new_supplementary, us_result, world_result, new_economics
