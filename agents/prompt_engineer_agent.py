"""
prompt_engineer_agent.py
Parser-first architecture.

Flow:
  raw_input
    → InputParser.parse()          (no LLM — pure Python)
    → ParseResult                  (mode, domain, entities, high_risk_fields, date_context)
    → PromptEngineerAgent.build()  (1 Haiku call, domain-specific instructions)
    → engineered string            (ANCHOR_EVENT: prefix when breaking/current)
"""

import re
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_HAIKU
from input_parser import InputParser, ParseResult
from prompts.loader import load, load_fmt


class PromptEngineerAgent:
    """
    Translates raw user input into a precisely scoped research prompt.

    Architecture:
      1. InputParser classifies mode + domain in pure Python (no LLM)
      2. Domain-specific LLM prompt template selected
      3. One Haiku call generates the research context
      4. ANCHOR_EVENT: prefix added in code for breaking/current topics

    The ParseResult metadata is encoded in a structured header block so
    downstream components (split_topic, orchestrator) can parse it without
    additional LLM calls.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = CLAUDE_MODEL_HAIKU
        self.parser = InputParser()

    # ── Public interface ────────────────────────────────────────────────

    def engineer_prompt(self, raw_topic: str) -> str:
        """Main entry point. Returns a fully structured engineered prompt."""
        result = self.parser.parse(raw_topic)
        research_context = self._generate_research_context(result)
        return self._format_output(result, research_context)

    def get_seed_urls(self, raw_topic: str) -> list[str]:
        """Extract URLs for pre-fetching before prompt engineering."""
        result = self.parser.parse(raw_topic)
        return result.urls

    def get_parse_result(self, raw_topic: str) -> ParseResult:
        """Expose ParseResult for orchestrator use."""
        return self.parser.parse(raw_topic)

    # ── Output formatting ───────────────────────────────────────────────

    def _format_output(self, result: ParseResult, research_context: str) -> str:
        domain_line = result.domain
        if result.subdomain:
            domain_line += f"/{result.subdomain}"

        risk_line = ", ".join(result.high_risk_fields[:6]) if result.high_risk_fields else "none"
        priority_line = ", ".join(result.search_priority[:5])

        if result.mode == "historical":
            anchor = result.clean_topic or (result.urls[0] if result.urls else "")
            return (
                f"HISTORICAL_ANCHOR: {anchor}\n"
                f"ANCHOR_YEAR: {result.anchor_year}\n"
                f"DATE_CONTEXT: {result.date_context}\n"
                f"DOMAIN: {domain_line}\n"
                f"HIGH_RISK_FIELDS: {risk_line}\n"
                f"SEARCH_PRIORITY: {priority_line}\n\n"
                f"RESEARCH_PROMPT: {research_context}"
            )

        if result.mode in ("breaking", "current"):
            anchor = result.clean_topic or (result.urls[0] if result.urls else "")
            return (
                f"ANCHOR_EVENT: {anchor}\n"
                f"DATE_CONTEXT: {result.date_context}\n"
                f"DOMAIN: {domain_line}\n"
                f"HIGH_RISK_FIELDS: {risk_line}\n"
                f"SEARCH_PRIORITY: {priority_line}\n\n"
                f"RESEARCH_PROMPT: {research_context}"
            )

        if result.mode == "recent":
            return (
                f"RECENCY_FLAG: true\n"
                f"DOMAIN: {domain_line}\n"
                f"SEARCH_PRIORITY: {priority_line}\n\n"
                f"RESEARCH_PROMPT: {research_context}"
            )

        return (
            f"DOMAIN: {domain_line}\n"
            f"SEARCH_PRIORITY: {priority_line}\n\n"
            f"RESEARCH_PROMPT: {research_context}"
        )

    # ── Research context generation ─────────────────────────────────────

    def _generate_research_context(self, result: ParseResult) -> str:
        if result.domain == "legal":
            return self._engineer_legal(result)
        if result.domain == "civil_rights":
            return self._engineer_civil_rights(result)
        if result.domain == "legislative":
            return self._engineer_legislative(result)
        if result.domain == "sociological":
            return self._engineer_sociological(result)
        if result.domain == "civic":
            return self._engineer_civic(result)
        if result.domain == "geopolitical":
            return self._engineer_geopolitical(result)

        if result.mode == "historical":
            return self._engineer_historical(result)
        if result.mode in ("breaking", "current"):
            return self._engineer_breaking_general(result)
        if result.mode == "recent":
            return self._engineer_recent_general(result)
        return self._engineer_general(result)

    # ── Domain-specific prompt templates ────────────────────────────────

    def _engineer_legal(self, r: ParseResult) -> str:
        subdomain_note = {
            "tro": (
                "This involves a TEMPORARY RESTRAINING ORDER. Critical tasks: "
                "(1) confirm exact case name, docket number, court, and assigned judge "
                "via wire services BEFORE analysis; (2) establish the Winter test standard; "
                "(3) identify what enforcement is paused and through what date."
            ),
            "scotus": (
                "This involves a SUPREME COURT RULING. Confirm vote count and justice "
                "alignment from Oyez or the official opinion; distinguish majority holding "
                "from concurrences and dicta; analyze constitutional vs. statutory grounds."
            ),
            "circuit": (
                "This involves a CIRCUIT COURT RULING. Confirm which circuit, whether "
                "en banc, and whether a circuit split exists."
            ),
            "statutory": (
                "This involves STATUTORY INTERPRETATION. Identify the specific USC "
                "section(s) and whether Loper Bright (post-Chevron) changes the "
                "deference analysis."
            ),
            "regulatory": (
                "This involves FEDERAL RULEMAKING. Identify the docket number, "
                "comment period status, and any APA procedural challenges."
            ),
        }.get(r.subdomain, "")

        recency_block = ""
        if r.mode in ("breaking", "current"):
            recency_block = (
                f"\n\nCRITICAL: {r.date_context} "
                f"Wire services (AP, Reuters) MUST be searched BEFORE legal databases. "
                f"HIGH-RISK FIELDS: {', '.join(r.high_risk_fields[:5])}. "
                f"Omit any that cannot be confirmed from wire service or court record."
            )

        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/legal_template",
            clean_topic=r.clean_topic,
            domain=r.domain,
            subdomain=r.subdomain or "general",
            mode=r.mode,
            subdomain_note=subdomain_note,
            search_priority=", ".join(r.search_priority[:3]),
            recency_days=7 if r.mode == "breaking" else 30,
            recency_block=recency_block,
        )
        return self._call(prompt)

    def _engineer_civil_rights(self, r: ParseResult) -> str:
        framework_note = {
            "first_amendment": (
                "First Amendment: forum analysis, content neutrality, "
                "government interest, and narrow tailoring."
            ),
            "equal_protection": (
                "Equal Protection: classification type, scrutiny level, "
                "compelling interest, narrow tailoring. Post-SFFA landscape."
            ),
            "fourth_amendment": (
                "Fourth Amendment: reasonable expectation of privacy, "
                "warrant exceptions, administrative search doctrine."
            ),
            "voting_rights": (
                "Voting Rights Act: Section 2 results test, Shelby County impact, "
                "Brnovich standard."
            ),
            "due_process": "Due process: liberty interests, Matthews balancing, fundamental rights.",
        }.get(r.subdomain, "Constitutional civil rights framework and enforcement statutes.")

        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/civil_rights_template",
            clean_topic=r.clean_topic,
            framework_note=framework_note,
            mode=r.mode,
            search_priority=", ".join(r.search_priority[:3]),
        )
        return self._call(prompt)

    def _engineer_legislative(self, r: ParseResult) -> str:
        stage_note = {
            "bill_introduced": (
                "NEWLY INTRODUCED bill. Focus on sponsor intent, committee "
                "assignment, companion legislation."
            ),
            "bill_pending": (
                "PENDING LEGISLATION. Track current stage, vote counts, amendments, "
                "floor schedule."
            ),
            "enacted": (
                "ENACTED LEGISLATION. Focus on implementation, agency rulemaking, "
                "legal challenges, compliance timelines."
            ),
            "amendment": (
                "LEGISLATIVE AMENDMENT. Identify what it modifies and the political "
                "context driving the change."
            ),
        }.get(r.subdomain, "")

        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/legislative_template",
            clean_topic=r.clean_topic,
            subdomain=r.subdomain or "general",
            stage_note=stage_note,
            search_priority=", ".join(r.search_priority[:3]),
        )
        return self._call(prompt)

    def _engineer_sociological(self, r: ParseResult) -> str:
        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/sociological_template",
            clean_topic=r.clean_topic,
            search_priority=", ".join(r.search_priority[:3]),
        )
        return self._call(prompt)

    def _engineer_civic(self, r: ParseResult) -> str:
        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/civic_template",
            clean_topic=r.clean_topic,
            search_priority=", ".join(r.search_priority[:3]),
        )
        return self._call(prompt)

    def _engineer_geopolitical(self, r: ParseResult) -> str:
        subdomain_note = {
            "assassination": (
                "This involves a TARGETED KILLING or ASSASSINATION. Critical tasks: "
                "(1) Verify confirmation of death from at least two independent sources "
                "(wire service + state media or official government statement) BEFORE any analysis; "
                "(2) Establish the exact strike location, time, and claiming party; "
                "(3) Identify the named official's role, chain of succession implications, "
                "and any disputed claims about the event."
            ),
            "military_conflict": (
                "This involves an ACTIVE MILITARY CONFLICT. Verify: "
                "(1) Confirmed vs. claimed territorial changes or casualty figures — "
                "distinguish official statements from battlefield claims; "
                "(2) Current ceasefire status if applicable; "
                "(3) Relevant UN Security Council resolutions or international law frameworks."
            ),
            "diplomacy": (
                "This involves a DIPLOMATIC EVENT. Verify: "
                "(1) Named officials and their confirmed titles; "
                "(2) Whether any agreement is signed, preliminary, or rumored; "
                "(3) Ratification requirements and domestic political obstacles."
            ),
            "nuclear": (
                "This involves a NUCLEAR PROGRAM development. Verify: "
                "(1) IAEA inspector access and most recent safeguards report; "
                "(2) Exact enrichment level claimed vs. confirmed; "
                "(3) Status of any active diplomatic framework (JCPOA or successor)."
            ),
            "sanctions": (
                "This involves SANCTIONS or ECONOMIC MEASURES. Verify: "
                "(1) Designating authority and legal basis; "
                "(2) Named entities and effective date; "
                "(3) Secondary sanctions exposure for third-party actors."
            ),
        }.get(r.subdomain, "")

        recency_block = ""
        if r.mode in ("breaking", "current"):
            recency_block = (
                f"\n\nCRITICAL: {r.date_context} "
                f"Wire services (AP, Reuters, AFP) and regional specialists MUST be searched FIRST. "
                f"HIGH-RISK FIELDS: {', '.join(r.high_risk_fields[:6])}. "
                f"Omit any that cannot be confirmed from a primary source. "
                f"Distinguish Israeli/US claims from Iranian/third-party confirmation."
            )

        # Build named-person block if extracted
        person_block = ""
        if r.entities.get("named_person"):
            person_block = (
                f"\nNAMED OFFICIAL: {r.entities['named_person']} "
                f"({r.entities.get('named_person_title', 'unknown title')}"
                f"{', ' + r.entities['named_person_country'] if r.entities.get('named_person_country') else ''}). "
                f"Verify full name, current title, and status from primary sources before any analysis."
            )

        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/geopolitical_template",
            clean_topic=r.clean_topic,
            date_context=r.date_context,
            subdomain=r.subdomain or "general",
            subdomain_note=subdomain_note + person_block,
            search_priority=", ".join(r.search_priority[:5]),
            high_risk_fields=(
                ", ".join(r.high_risk_fields[:6]) if r.high_risk_fields
                else "named_official_status, confirming_source, strike_location"
            ),
            recency_days=7 if r.mode == "breaking" else 30,
            recency_block=recency_block,
        )
        return self._call(prompt)

    def _engineer_historical(self, r: ParseResult) -> str:
        # Get historical subdomain high-risk fields if available
        hist_subdomain = self.parser.HISTORICAL_SUBDOMAIN_MAP.get(r.domain, {})
        high_risk = hist_subdomain.get("high_risk_fields", r.high_risk_fields)

        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/historical_template",
            clean_topic=r.clean_topic,
            anchor_year=r.anchor_year or "unknown",
            domain=r.domain,
            high_risk_fields=(
                ", ".join(high_risk[:6]) if high_risk
                else "chronological_sequence, causal_attribution, actor_names"
            ),
        )
        return self._call(prompt)

    def _engineer_breaking_general(self, r: ParseResult) -> str:
        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/breaking_general_template",
            clean_topic=r.clean_topic,
            date_context=r.date_context,
            high_risk_fields=(
                ", ".join(r.high_risk_fields[:5]) if r.high_risk_fields
                else "all specific identifiers"
            ),
        )
        return self._call(prompt)

    def _engineer_recent_general(self, r: ParseResult) -> str:
        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/recent_general_template",
            clean_topic=r.clean_topic,
            date_context=r.date_context,
            search_priority=", ".join(r.search_priority[:4]),
        )
        return self._call(prompt)

    def _engineer_general(self, r: ParseResult) -> str:
        prompt = load("prompt_engineer/preamble") + "\n" + load_fmt(
            "prompt_engineer/general_template",
            clean_topic=r.clean_topic,
            date_context=r.date_context,
            search_priority=", ".join(r.search_priority[:4]),
        )
        return self._call(prompt)

    # ── LLM call ────────────────────────────────────────────────────────

    def _call(self, prompt: str, max_tokens: int = 500) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
