"""
input_parser.py
Pure Python — no LLM calls, no network, ~2ms execution.
Classifies user input and produces a ParseResult that shapes every
downstream prompt, sub-topic, and search query.

Sits between the raw input and PromptEngineerAgent in the pipeline:
    raw_input → InputParser → ParseResult → PromptEngineerAgent → ...
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


# ── Output dataclass ────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """Structured output of the InputParser."""

    # ── Temporal classification ──
    mode: str = "general"
    # breaking | current | recent | historical | general

    # ── Historical pipeline fields ──
    anchor_year: int = 0  # extracted year of the historical anchor event

    # ── Domain classification ──
    domain: str = "general"
    domain_scores: dict = field(default_factory=dict)
    secondary_domain: str = ""
    subdomain: str = ""

    # ── Input type ──
    is_headline: bool = False
    is_question: bool = False

    # ── Extracted entities ──
    entities: dict = field(default_factory=dict)

    # ── Verification risk flags ──
    high_risk_fields: list = field(default_factory=list)

    # ── Date context for search queries ──
    date_context: str = ""

    # ── Search strategy ──
    search_priority: list = field(default_factory=list)

    # ── URLs extracted from input ──
    urls: list = field(default_factory=list)

    # ── Cleaned topic (URLs stripped) ──
    clean_topic: str = ""

    # ── Matched markers (debugging/transparency) ──
    matched_breaking: list = field(default_factory=list)
    matched_current: list = field(default_factory=list)
    matched_domain: list = field(default_factory=list)


# ── Marker sets ─────────────────────────────────────────────────────────────


import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"

def _load(name: str):
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


# ── Marker sets ──────────────────────────────────────────────────────────────


class InputParser:
    """
    Classifies raw user input into mode + domain without any LLM calls.
    Keyword sets and configuration are loaded from data/ JSON files.
    A lightweight Haiku second-pass fires for ambiguous headlines only.

    Usage:
        parser = InputParser()
        result = parser.parse("Judge temporarily halts Trump demand...")
        # result.mode == "breaking"
        # result.domain == "legal"
        # result.subdomain == "tro"
    """

    URL_PATTERN = re.compile(r'https?://[^\s\)\"\']+'  )

    # ── Loaded from data/ at class definition time ───────────────────────────
    AMBIGUOUS_SINGLE_WORDS    = set(_load("ambiguous_single_words.json"))
    BREAKING_MARKERS          = set(_load("breaking_markers.json"))
    BREAKING_VERBS            = set(_load("breaking_verbs.json"))
    LEGAL_CONTEXT_WORDS       = set(_load("legal_context_words.json"))
    CURRENT_MARKERS           = set(_load("current_markers.json"))
    RECENT_MARKERS            = set(_load("recent_markers.json"))
    LEGAL_MARKERS             = set(_load("legal_markers.json"))
    CIVIL_RIGHTS_MARKERS      = set(_load("civil_rights_markers.json"))
    LEGISLATIVE_MARKERS       = set(_load("legislative_markers.json"))
    SOCIOLOGICAL_MARKERS      = set(_load("sociological_markers.json"))
    CIVIC_MARKERS             = set(_load("civic_markers.json"))
    GEOPOLITICAL_MARKERS      = set(_load("geopolitical_markers.json"))
    HEADLINE_VERBS            = set(_load("headline_verbs.json"))
    QUESTION_STARTERS         = set(_load("question_starters.json"))

    # Historical pipeline markers
    HISTORICAL_MARKERS        = set(_load("historical_markers.json"))
    HISTORICAL_CAUSAL_MARKERS = set(_load("historical_causal_markers.json"))
    HISTORICAL_EVENTS         = _load("historical_events.json")
    HISTORICAL_SUBDOMAIN_MAP  = _load("historical_subdomain_map.json")

    # Historical mode activation — weighted scoring.
    # Named events carry more weight because they are the strongest single
    # signal a user is asking about a specific historical event. A bare named
    # event ("Watergate") now fires historical on its own; all prior 2-signal
    # combinations (marker+year, marker+causal, year+causal) still fire.
    HIST_SCORE_NAMED_EVENT = 2
    HIST_SCORE_MARKER      = 1
    HIST_SCORE_CAUSAL      = 1
    HIST_SCORE_YEAR        = 1
    HIST_ACTIVATION_THRESHOLD = 2

    # Flatten all historical event names into a single set for fast lookup
    _ALL_HISTORICAL_EVENTS = set()
    for _category in HISTORICAL_EVENTS.values():
        if isinstance(_category, list):
            _ALL_HISTORICAL_EVENTS.update(e.lower() for e in _category)

    LEGAL_SUBDOMAIN_MAP           = _load("legal_subdomain_map.json")
    CIVIL_RIGHTS_SUBDOMAIN_MAP    = _load("civil_rights_subdomain_map.json")
    GEOPOLITICAL_SUBDOMAIN_MAP    = _load("geopolitical_subdomain_map.json")
    HIGH_RISK_FIELDS_BY_SUBDOMAIN = _load("high_risk_fields_by_subdomain.json")
    SEARCH_PRIORITY_BY_DOMAIN     = _load("search_priority_by_domain.json")

    # Single-word time anchors — immediately elevate mode to at least "current"
    # regardless of question/statement threshold. These express temporal immediacy.
    TIME_ANCHOR_MARKERS = {
        "today", "tonight", "tomorrow", "yesterday",
        "this morning", "right now", "just now",
    }

    # Named foreign officials: title patterns that trigger person extraction
    FOREIGN_OFFICIAL_TITLES = {
        "president", "prime minister", "foreign minister", "defense minister",
        "supreme leader", "security chief", "intelligence chief", "commander",
        "general", "admiral", "chancellor", "secretary general", "envoy",
        "ambassador", "ayatollah", "minister", "chief of staff",
    }

    # ── Public interface ─────────────────────────────────────────────────────

    def parse(self, raw_input: str) -> ParseResult:
        """Main entry point. Returns a ParseResult with no LLM calls."""
        result = ParseResult()

        # Step 1: Extract URLs
        result.urls = self.URL_PATTERN.findall(raw_input)
        result.clean_topic = self.URL_PATTERN.sub("", raw_input).strip()
        result.clean_topic = re.sub(r"\s{2,}", " ", result.clean_topic).strip()

        if not result.clean_topic and result.urls:
            result.clean_topic = self._topic_from_url(result.urls[0])

        # Step 1b: News outlet URL — force at least mode="current"
        NEWS_OUTLET_DOMAINS = {
            "apnews.com", "reuters.com", "afp.com", "bbc.com", "bbc.co.uk",
            "nbcnews.com", "cbsnews.com", "abcnews.go.com", "abcnews.com",
            "nytimes.com", "wsj.com", "washingtonpost.com", "theguardian.com",
            "independent.co.uk", "politico.com", "thehill.com", "axios.com",
            "npr.org", "pbs.org", "cnn.com", "foxnews.com", "msnbc.com",
            "bloomberg.com", "aljazeera.com", "france24.com", "dw.com",
            "euronews.com", "sbs.com.au", "cbc.ca", "globeandmail.com",
            "rollcall.com", "huffpost.com", "propublica.org", "jurist.org",
        }
        if result.urls:
            from urllib.parse import urlparse
            for _url in result.urls:
                _host = urlparse(_url).netloc.lstrip("www.")
                if any(_host == d or _host.endswith("." + d)
                       for d in NEWS_OUTLET_DOMAINS):
                    result._news_url_detected = True
                    break

        lower = result.clean_topic.lower()
        words = lower.split()

        # Step 2: Detect input type (question vs statement vs headline)
        result.is_question = self._is_question(lower, words)
        result.is_headline = self._is_headline(lower, words, result.clean_topic)

        # Step 2b: Historical detection (runs before temporal classification)
        # Weighted scoring: named event = 2 pts, others = 1 pt, threshold = 2.
        # A bare named event ("Watergate") now fires historical on its own; all
        # prior 2-signal combinations still fire. If historical, skip
        # breaking/current/recent.
        hist_score = 0
        hist_markers_hit = []

        # Signal: Historical marker phrases (1 pt)
        hist_phrase_hits = self._match_markers(lower, self.HISTORICAL_MARKERS)
        if hist_phrase_hits:
            hist_score += self.HIST_SCORE_MARKER
            hist_markers_hit.extend(hist_phrase_hits)

        # Signal: Causal/ripple language (1 pt)
        hist_causal_hits = self._match_markers(lower, self.HISTORICAL_CAUSAL_MARKERS)
        if hist_causal_hits:
            hist_score += self.HIST_SCORE_CAUSAL
            hist_markers_hit.extend(hist_causal_hits)

        # Signal: Named historical event (2 pts — strongest single hint)
        current_year = date.today().year
        anchor_year_candidate = 0
        for event_name in self._ALL_HISTORICAL_EVENTS:
            if event_name in lower:
                hist_score += self.HIST_SCORE_NAMED_EVENT
                hist_markers_hit.append(f"named_event:{event_name}")
                yr_match = re.search(r'\b(1[0-9]{3}|20[0-1][0-9])\b', event_name)
                if yr_match:
                    anchor_year_candidate = int(yr_match.group(1))
                break

        # Signal: explicit year >=10 years ago (1 pt)
        year_matches = re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', lower)
        for yr_str in year_matches:
            yr = int(yr_str)
            if yr <= current_year - 10:
                if not anchor_year_candidate or yr < anchor_year_candidate:
                    anchor_year_candidate = yr
                hist_score += self.HIST_SCORE_YEAR
                hist_markers_hit.append(f"historical_year:{yr}")
                break  # one year signal is enough

        # Activate historical mode when score clears the threshold
        if hist_score >= self.HIST_ACTIVATION_THRESHOLD:
            result.mode = "historical"
            result.anchor_year = anchor_year_candidate
            result.matched_current = hist_markers_hit
            # Skip to domain classification — no breaking/current/recent logic
        else:
            # Reset anchor_year if not historical
            anchor_year_candidate = 0

        # Step 3: Temporal classification (skipped if historical mode already set)
        if result.mode != "historical":

            # Regex: catch any numeric vote tally pattern (e.g., "218-210", "51-48", "7-2")
            vote_tally = re.search(r'\b\d{1,3}-\d{1,3}\b', lower)
            result.matched_breaking = self._match_markers(lower, self.BREAKING_MARKERS)
            if vote_tally:
                result.matched_breaking.append(f"vote_tally:{vote_tally.group()}")
            # Breaking verbs only count if paired with a proper noun
            if not result.matched_breaking:
                verb_hits = [v for v in self.BREAKING_VERBS if self._word_boundary_match(v, lower)]
                if verb_hits and self._has_proper_noun(result.clean_topic):
                    result.matched_breaking = verb_hits

            result.matched_current = self._match_markers(lower, self.CURRENT_MARKERS)
            recent_hits = self._match_markers(lower, self.RECENT_MARKERS)

            # Dynamic year matching — current year and previous year trigger "recent"
            # without hardcoding years in the JSON file
            for yr in range(current_year - 1, current_year + 1):
                if self._word_boundary_match(str(yr), lower):
                    recent_hits.append(f"year:{yr}")

            # Questions bias toward general unless explicit temporal markers
            if result.is_question:
                if result.matched_breaking and len(result.matched_breaking) >= 2:
                    result.mode = "breaking"
                elif result.matched_current and len(result.matched_current) >= 2:
                    result.mode = "current"
                elif recent_hits:
                    result.mode = "recent"
                else:
                    result.mode = "general"
            else:
                if result.matched_breaking:
                    result.mode = "breaking"
                elif result.matched_current:
                    result.mode = "current"
                elif recent_hits:
                    result.mode = "recent"
                else:
                    result.mode = "general"

        # Step 3a: Time anchor floor — words like "today", "tonight", "right now"
        # express temporal immediacy and elevate mode to at least "current".
        # Does NOT affect breaking threshold — only prevents general fallthrough.
        if result.mode == "general":
            time_hits = self._match_markers(lower, self.TIME_ANCHOR_MARKERS)
            if time_hits:
                result.mode = "current"
                result.matched_current.extend(time_hits)

        # Step 3b: Haiku second pass for implicit-recency headlines
        # Also fires for questions with time signals (demoted one tier).
        if self._needs_llm_classify(result):
            llm_mode = self._llm_classify_temporal(result.clean_topic)
            if llm_mode:
                # Questions get demoted one tier: breaking→current, current→recent
                if result.is_question:
                    demotion = {"breaking": "current", "current": "recent", "recent": "recent"}
                    llm_mode = demotion.get(llm_mode, llm_mode)

                # Only upgrade — never downgrade from a mode already assigned
                MODE_RANK = {"general": 0, "recent": 1, "current": 2, "breaking": 3}
                if MODE_RANK.get(llm_mode, 0) > MODE_RANK.get(result.mode, 0):
                    result.mode = llm_mode

                if llm_mode == "breaking":
                    result.matched_breaking.append(f"llm_classify:{llm_mode}")
                elif llm_mode in ("current", "recent"):
                    result.matched_current.append(f"llm_classify:{llm_mode}")
            elif result.mode == "general" and not result.is_question:
                # Step 3b-fallback: LLM unavailable or returned None.
                # For confirmed headlines with a proper noun or known institution,
                # apply a conservative "current" floor.
                lower_ct = result.clean_topic.lower()
                has_hl_verb = self._has_headline_verb(lower_ct)
                has_known_subject = self._is_known_subject_first_word(result.clean_topic)
                if result.is_headline and (has_hl_verb or has_known_subject) and (
                    self._has_proper_noun(result.clean_topic)
                    or has_known_subject
                ):
                    result.mode = "current"
                    result.matched_current.append("headline_floor:proper_noun")

        # Step 3c: Enforce news-URL floor — mode cannot be "general"
        # if a recognized news outlet URL was in the input.
        if getattr(result, "_news_url_detected", False) and result.mode == "general":
            result.mode = "current"
            result.matched_current.append("news_url_domain_detected")

        # Step 3d: Two-phase verification — for high-urgency classifications,
        # run one web search to confirm the story's actual publication date.
        # Prevents over-classification of old stories as breaking.
        # Only fires for "breaking" mode (the most aggressive classification).
        if result.mode == "breaking" and not result.is_question:
            verified_mode = self._verify_recency_via_search(result.clean_topic)
            if verified_mode:
                MODE_RANK = {"general": 0, "recent": 1, "current": 2, "breaking": 3}
                # Only demote — never promote from a search result
                if MODE_RANK.get(verified_mode, 0) < MODE_RANK.get(result.mode, 3):
                    result.mode = verified_mode
                    result.matched_current.append(f"recency_verified:{verified_mode}")

        # Step 4: Domain classification with ambiguity handling
        result.domain_scores = self._score_domains(lower)
        sorted_domains = sorted(result.domain_scores.items(), key=lambda x: -x[1])
        result.domain = sorted_domains[0][0] if sorted_domains[0][1] > 0 else "general"
        if len(sorted_domains) > 1 and sorted_domains[1][1] > 0:
            # Secondary domain if within 60% of primary score
            if sorted_domains[1][1] >= sorted_domains[0][1] * 0.6:
                result.secondary_domain = sorted_domains[1][0]
        result.matched_domain = self._top_domain_matches(lower, result.domain)

        # Step 5: Subdomain
        result.subdomain = self._detect_subdomain(lower, result.domain)

        # Step 6: Entity extraction
        result.entities = self._extract_entities(result.clean_topic, result.domain)

        # Step 7: High-risk fields
        result.high_risk_fields = self._get_high_risk_fields(
            result.subdomain, result.domain, result.entities
        )

        # Step 8: Date context
        result.date_context = self._build_date_context(result.mode, result)

        # Step 9: Search priority
        result.search_priority = self.SEARCH_PRIORITY_BY_DOMAIN.get(
            result.domain, self.SEARCH_PRIORITY_BY_DOMAIN["general"]
        )

        return result

    # ── Input type detection ────────────────────────────────────────────

    def _is_question(self, lower: str, words: list) -> bool:
        """Detect research questions vs statements/headlines."""
        if "?" in lower:
            return True
        if words and words[0] in self.QUESTION_STARTERS:
            return True
        return False

    def _is_headline(self, lower: str, words: list, original: str = "") -> bool:
        """Detect pasted news headlines."""
        if len(words) < 4 or len(words) > 30:
            return False
        if "?" in lower:
            return False
        # Headlines use specific news verbs
        if any(self._word_boundary_match(v, lower) for v in self.HEADLINE_VERBS):
            return True
        # Multiple proper nouns suggest a headline (need original case)
        if original and self._has_proper_noun(original):
            skip = {"The", "A", "An", "In", "On", "At", "For", "And", "Or",
                    "But", "With", "From", "To", "By", "Of"}
            orig_words = original.split()
            caps = sum(1 for w in orig_words[1:] if w[0:1].isupper() and w not in skip)
            if caps >= 2:
                return True
        # Catch headlines starting with known acronym institutions
        KNOWN_ACRONYMS = {
            "tsa", "fbi", "doj", "cia", "sec", "cdc", "dhs", "ice", "irs",
            "nato", "un", "eu", "who", "dod", "epa", "fda", "ftc", "fed",
            "gop", "doge", "cms", "hhs", "atf", "nsa", "dea",
        }
        if words and words[0].lower() in KNOWN_ACRONYMS:
            return True
        # Catch country/institution-subject headlines with present-tense verbs
        KNOWN_GEO_SUBJECTS = {
            "cuba", "iran", "russia", "china", "israel", "ukraine", "taiwan",
            "north korea", "south korea", "nato", "congress", "senate",
            "house", "supreme court", "white house", "pentagon", "kremlin",
        }
        two_word_start = " ".join(words[:2])
        if words[0] in KNOWN_GEO_SUBJECTS or two_word_start in KNOWN_GEO_SUBJECTS:
            if any(self._word_boundary_match(v, lower) for v in self.BREAKING_VERBS):
                return True
        return False

    def _has_proper_noun(self, text: str) -> bool:
        """Check if text contains capitalized proper nouns (not sentence-start)."""
        words = text.split()
        if len(words) < 2:
            return False
        skip = {"The", "A", "An", "In", "On", "At", "For", "And", "Or",
                "But", "With", "From", "To", "By", "Of", "Is", "Are",
                "Was", "Were", "Has", "Have", "Had", "Will", "Would",
                "Could", "Should", "May", "Might", "Can", "Do", "Does"}
        caps = sum(1 for w in words[1:] if w[0:1].isupper() and w not in skip)
        return caps >= 1

    # Known institution/country subjects for the deterministic fallback floor
    _KNOWN_SUBJECTS = {
        "cuba", "iran", "russia", "china", "israel", "ukraine", "taiwan",
        "syria", "turkey", "india", "pakistan", "venezuela", "mexico",
        "canada", "france", "germany", "japan", "brazil", "korea",
        "congress", "senate", "house", "scotus", "pentagon", "kremlin",
        "nato", "un", "eu", "who", "imf", "fed", "doj", "fbi", "cia",
        "sec", "cdc", "dhs", "ice", "irs", "tsa", "epa", "fda", "ftc",
        "dod", "gop", "doge", "cms", "hhs", "atf", "nsa", "dea",
        "white house", "supreme court", "trump", "biden", "administration",
    }

    def _is_known_subject_first_word(self, text: str) -> bool:
        """Return True if the headline starts with a known institution, country,
        or prominent actor — even in lowercase."""
        if not text:
            return False
        lower = text.lower()
        words = lower.split()
        if not words:
            return False
        first = words[0]
        first2 = " ".join(words[:2]) if len(words) >= 2 else ""
        return first in self._KNOWN_SUBJECTS or first2 in self._KNOWN_SUBJECTS

    # ── Marker matching ─────────────────────────────────────────────────

    def _match_markers(self, text: str, markers: set) -> list:
        """Match markers using word boundaries for single words,
        substring for multi-word phrases."""
        hits = []
        for marker in markers:
            if self._marker_in_text(marker, text):
                hits.append(marker)
        return hits

    def _marker_in_text(self, marker: str, text: str) -> bool:
        """Word-boundary-aware matching. Multi-word = substring.
        Single-word = word boundary to avoid 'act' matching 'actually'."""
        if " " in marker:
            return marker in text
        return self._word_boundary_match(marker, text)

    def _word_boundary_match(self, word: str, text: str) -> bool:
        """Check if word appears as a whole word in text."""
        return bool(re.search(rf'\b{re.escape(word)}\b', text))

    # ── Domain scoring ──────────────────────────────────────────────────

    def _score_domains(self, lower: str) -> dict:
        """Score each domain with ambiguity handling.

        Multi-word markers: +2 points
        Unambiguous single-word markers: +1 point
        Ambiguous single-word markers: +1 only if domain already has an unambiguous hit
        Multi-word subsumes single: if "supreme court" matches, "court" doesn't add +1
        Context combos: ambiguous word + breaking verb = unambiguous signal
        """
        domains = {
            "legal": self.LEGAL_MARKERS,
            "civil_rights": self.CIVIL_RIGHTS_MARKERS,
            "legislative": self.LEGISLATIVE_MARKERS,
            "sociological": self.SOCIOLOGICAL_MARKERS,
            "civic": self.CIVIC_MARKERS,
            "geopolitical": self.GEOPOLITICAL_MARKERS,
        }

        # Pre-check: do breaking verbs appear? If so, legal context words
        # become unambiguous
        has_breaking_verb = any(
            self._word_boundary_match(v, lower) for v in self.BREAKING_VERBS
        )
        legal_context_boost = (
            has_breaking_verb and
            any(self._word_boundary_match(w, lower) for w in self.LEGAL_CONTEXT_WORDS)
        )

        scores = {}

        for domain, markers in domains.items():
            multi = {m for m in markers if " " in m}
            single = {m for m in markers if " " not in m}

            # Score multi-word first
            multi_hits = [m for m in multi if m in lower]
            multi_score = len(multi_hits) * 2

            # Track which single words are subsumed by multi-word hits
            subsumed = set()
            for mh in multi_hits:
                for word in mh.split():
                    subsumed.add(word)

            # Score single-word markers
            has_unambiguous = multi_score > 0

            # Context combo boost for legal domain
            if domain == "legal" and legal_context_boost:
                has_unambiguous = True

            single_score = 0
            for s in single:
                if s in subsumed:
                    continue
                if not self._word_boundary_match(s, lower):
                    continue
                if s in self.AMBIGUOUS_SINGLE_WORDS:
                    if has_unambiguous:
                        single_score += 1
                else:
                    single_score += 1
                    has_unambiguous = True

            # Add the context combo as a base point for legal
            if domain == "legal" and legal_context_boost and multi_score == 0:
                single_score += 2  # "judge" + "halts" = strong legal signal

            scores[domain] = multi_score + single_score

        # General gets 0 — it's the fallback
        scores["general"] = 0
        return scores

    def _top_domain_matches(self, lower: str, domain: str) -> list:
        """Return top matched markers for the winning domain."""
        marker_set = {
            "legal": self.LEGAL_MARKERS,
            "civil_rights": self.CIVIL_RIGHTS_MARKERS,
            "legislative": self.LEGISLATIVE_MARKERS,
            "sociological": self.SOCIOLOGICAL_MARKERS,
            "civic": self.CIVIC_MARKERS,
            "geopolitical": self.GEOPOLITICAL_MARKERS,
        }.get(domain, set())
        return [m for m in marker_set if self._marker_in_text(m, lower)][:8]

    # ── Subdomain detection ─────────────────────────────────────────────

    def _detect_subdomain(self, lower: str, domain: str) -> str:
        subdomain_map = {}
        if domain == "legal":
            subdomain_map = self.LEGAL_SUBDOMAIN_MAP
        elif domain == "civil_rights":
            subdomain_map = self.CIVIL_RIGHTS_SUBDOMAIN_MAP
        elif domain == "legislative":
            return self._detect_legislative_subdomain(lower)
        elif domain == "geopolitical":
            subdomain_map = self.GEOPOLITICAL_SUBDOMAIN_MAP

        for subdomain, markers in subdomain_map.items():
            if any(m in lower for m in markers):
                return subdomain
        return ""

    def _detect_legislative_subdomain(self, lower: str) -> str:
        if any(w in lower for w in ["introduced", "introduces", "new bill"]):
            return "bill_introduced"
        if any(w in lower for w in ["passed", "floor vote", "committee vote"]):
            return "bill_pending"
        if any(w in lower for w in ["enacted", "signed into law", "public law"]):
            return "enacted"
        if any(w in lower for w in ["amendment", "amend"]):
            return "amendment"
        return ""

    # ── Entity extraction ───────────────────────────────────────────────

    def _extract_entities(self, text: str, domain: str) -> dict:
        """Extract named entities from original (not lowered) text."""
        entities = {}
        lower = text.lower()

        # Bill numbers (H.R. XXXX or S. XXXX)
        bill = re.search(r'\b[Hh]\.?[Rr]\.?\s*(\d+)\b|\b[Ss]\.?\s*(\d{2,})\b', text)
        if bill:
            entities["bill_number"] = bill.group(0).strip()

        # Year references
        year = re.search(r'\b(202[0-9])\b', text)
        if year:
            entities["year_referenced"] = year.group(1)

        # Court level
        if "supreme court" in lower or "scotus" in lower:
            entities["jurisdiction"] = "SCOTUS"
        elif "circuit" in lower:
            m = re.search(r'(\w+)\s+circuit', lower)
            entities["jurisdiction"] = f"{m.group(1).title()} Circuit" if m else "Circuit Court"
        elif "district court" in lower or "district judge" in lower or "federal judge" in lower:
            entities["jurisdiction"] = "Federal District Court"

        # Named person extraction — handles multiple patterns
        self._extract_judge_name(text, entities)

        # Foreign official extraction for geopolitical topics
        if domain == "geopolitical" and "named_person" not in entities:
            self._extract_foreign_official(text, entities)

        # Action type
        for action_kw in ["halts", "blocks", "bars", "orders", "rules",
                          "overturns", "overrides", "reverses", "revokes",
                          "rescinds", "reinstates", "vacates", "remands",
                          "affirms", "dismisses", "strikes down", "upholds",
                          "suspends", "seizes", "closes", "signs", "vetoes",
                          "sentences", "defunds", "ousts", "rejects"]:
            if self._word_boundary_match(action_kw, lower):
                entities["action"] = action_kw
                break

        return entities

    def _extract_judge_name(self, text: str, entities: dict):
        """Extract judge/justice names with multiple pattern support."""
        patterns = [
            # "Chief Justice Roberts", "Justice Sotomayor"
            (r'\b(?:[Cc]hief\s+)?[Jj]ustice\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', "justice"),
            # "U.S. District Judge John Smith", "Federal Judge Smith"
            (r'\b(?:[Uu]\.?[Ss]\.?\s+)?(?:[Dd]istrict\s+|[Ff]ederal\s+|[Mm]agistrate\s+)?[Jj]udge\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*[a-z]+)*)', "judge"),
        ]

        non_name_words = {
            "temporarily", "blocks", "halts", "rules", "orders", "says",
            "grants", "finds", "denies", "dismisses", "allows", "rejects",
            "issues", "the", "a", "an", "in", "on", "for", "to", "of",
            "who", "that", "has", "had", "was", "is",
        }

        for pattern, role in patterns:
            match = re.search(pattern, text)
            if match:
                raw_name = match.group(1).strip()
                # Clean trailing non-name words
                words = raw_name.split()
                clean = []
                for w in words:
                    if w.lower().rstrip(".") in non_name_words:
                        break
                    clean.append(w)
                name = " ".join(clean).strip()
                if len(name) >= 2 and name[0].isupper():
                    entities["named_person"] = name
                    entities["named_person_type"] = role
                    return

        # If "judge" appears but no name extracted, flag for verification
        if re.search(r'\bjudge\b', text, re.IGNORECASE):
            entities["judge_in_input"] = True

    def _extract_foreign_official(self, text: str, entities: dict):
        """Extract foreign heads of state and senior officials.

        Strategy:
        1. Possessive-title pattern (e.g., "Iran's security chief Larijani")
        2. Title + Name pattern (e.g., "Prime Minister Netanyahu")
        3. Standalone capitalised proper noun after a geopolitical verb
        """
        # Pattern 1: possessive + title + name
        poss_title = re.search(
            r"(\w+'s)\s+([a-z]+(?:\s+[a-z]+){0,2})\s+([A-Z][a-z]{1,20})",
            text
        )
        if poss_title:
            country = poss_title.group(1).rstrip("'s")
            title   = poss_title.group(2)
            name    = poss_title.group(3)
            if any(t in title for t in self.FOREIGN_OFFICIAL_TITLES):
                entities["named_person"]        = name
                entities["named_person_type"]   = "foreign_official"
                entities["named_person_title"]  = title
                entities["named_person_country"] = country.title()
                return

        # Pattern 2: title + name (e.g., "Prime Minister Netanyahu")
        for title in sorted(self.FOREIGN_OFFICIAL_TITLES, key=len, reverse=True):
            pattern = rf'\b{re.escape(title)}\s+([A-Z][a-z]{{1,20}}(?:\s+[A-Z][a-z]{{1,20}})?)'
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if name[0].isupper():
                    entities["named_person"]       = name
                    entities["named_person_type"]  = "foreign_official"
                    entities["named_person_title"] = title
                    return

        # Pattern 3: standalone surname near a geopolitical verb
        geo_verbs = {
            "targeted", "killed", "assassinated", "struck", "eliminated",
            "arrested", "captured", "detained", "wounded", "injured",
        }
        words = text.split()
        for i, w in enumerate(words):
            if w.lower().rstrip(",") in geo_verbs:
                for j in range(i + 1, min(i + 6, len(words))):
                    candidate = words[j].strip(",'\".")
                    if len(candidate) >= 3 and candidate[0].isupper() and candidate.isalpha():
                        entities["named_person"]       = candidate
                        entities["named_person_type"]  = "foreign_official"
                        entities["named_person_title"] = "unknown"
                        return

    # ── High-risk fields ────────────────────────────────────────────────

    def _get_high_risk_fields(self, subdomain: str, domain: str,
                               entities: dict) -> list:
        base = list(self.HIGH_RISK_FIELDS_BY_SUBDOMAIN.get(subdomain, []))

        if entities.get("named_person"):
            if "named_person_verification" not in base:
                base.insert(0, "named_person_verification")

        if domain == "legal" and not base:
            base = ["judge_name", "court", "docket_number", "ruling_date"]

        if domain == "geopolitical" and not base:
            base = [
                "confirmation_of_death",
                "named_official_status",
                "confirming_source",
                "strike_location",
                "government_confirmation",
            ]

        return base

    # ── Date context ────────────────────────────────────────────────────

    def _build_date_context(self, mode: str, result: ParseResult = None) -> str:
        from datetime import timedelta
        today = date.today()
        today_str = today.strftime("%B %d, %Y")
        today_iso = today.isoformat()

        # Check if time anchors are present in the text — tighten breaking to 48 hours
        has_time_anchor = False
        if result:
            lower_text = result.clean_topic.lower()
            has_time_anchor = bool(self._match_markers(lower_text, self.TIME_ANCHOR_MARKERS))

        if mode == "breaking":
            if has_time_anchor:
                boundary = (today - timedelta(hours=48)).isoformat()
                return (
                    f"TODAY IS {today_str} ({today_iso}). "
                    f"LIVE EVENT — search ONLY for coverage from the past 48 hours. "
                    f"Date boundary: {boundary} to {today_iso}."
                )
            boundary = (today - timedelta(days=7)).isoformat()
            return (
                f"TODAY IS {today_str} ({today_iso}). "
                f"Search ONLY for coverage published in the past 7 days. "
                f"Date boundary: {boundary} to {today_iso}."
            )
        if mode == "current":
            boundary = (today - timedelta(days=30)).isoformat()
            return (
                f"TODAY IS {today_str} ({today_iso}). "
                f"Prioritize coverage from the past 30 days. "
                f"Date boundary: {boundary} to {today_iso}."
            )
        if mode == "recent":
            boundary = (today - timedelta(days=730)).isoformat()
            return (
                f"TODAY IS {today_str} ({today_iso}). "
                f"Prioritize sources from the past 24 months. "
                f"Date boundary: {boundary} to {today_iso}."
            )
        if mode == "historical":
            anchor_year = result.anchor_year if result else 0
            if anchor_year:
                return (
                    f"TODAY IS {today_str} ({today_iso}). "
                    f"HISTORICAL ANALYSIS — anchor year is approximately {anchor_year}. "
                    f"Primary sources from the anchor era ({anchor_year - 5} to {anchor_year + 5}) "
                    f"are the highest-priority sources. Established scholarship spanning "
                    f"{anchor_year} to present provides the analytical framework. "
                    f"Modern sources (past 12 months) are used ONLY for connecting the "
                    f"historical record to present-day conditions."
                )
            return (
                f"TODAY IS {today_str} ({today_iso}). "
                f"HISTORICAL ANALYSIS — anchor year not specified. "
                f"Prioritize primary sources from the era of the event, "
                f"established scholarship, and modern retrospective analysis."
            )
        # General — soft recency floor rather than no guidance
        boundary = (today - timedelta(days=365)).isoformat()
        return (
            f"TODAY IS {today_str} ({today_iso}). "
            f"Prefer sources from the past 12 months where available. "
            f"Date boundary (soft): {boundary} to {today_iso}."
        )

    # ── URL helper ──────────────────────────────────────────────────────

    def _has_headline_verb(self, lower: str) -> bool:
        """Check if text contains any headline-style action verb."""
        return any(self._word_boundary_match(v, lower) for v in self.HEADLINE_VERBS)

    def _has_time_signal(self, result: ParseResult) -> bool:
        """Check if the input has any explicit time signal — time anchor hits
        or current marker hits. Used to allow questions through the LLM gate."""
        return bool(result.matched_current) or bool(
            self._match_markers(result.clean_topic.lower(), self.TIME_ANCHOR_MARKERS)
        )

    def _verify_recency_via_search(self, text: str) -> str | None:
        """Two-phase verification: search for the headline and extract the
        publication date. Returns the empirically correct mode, or None
        if the search fails.

        Only demotes — if the story is confirmed recent, returns None
        (letting the existing 'breaking' stand). Only returns a lower mode
        if evidence shows the story is older than 7 days.

        Uses Sonnet (not Haiku) because web_search tool requires it."""
        try:
            import anthropic
            from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

            if not ANTHROPIC_API_KEY:
                return None

            client = anthropic.Anthropic(
                api_key=ANTHROPIC_API_KEY,
                timeout=10.0,
            )
            today = date.today()
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": (
                    f"TODAY IS {today.isoformat()}. "
                    f"Search for this headline and find the publication date "
                    f"of the most recent matching article. "
                    f"Respond with EXACTLY one line: DATE: YYYY-MM-DD\n"
                    f"If not found: DATE: UNKNOWN\n\n"
                    f"Headline: {text[:150]}"
                )}],
            )
            raw = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw += block.text

            # Try strict format first
            m = re.search(r'DATE:\s*(\d{4}-\d{2}-\d{2})', raw)
            if m:
                pub_date = date.fromisoformat(m.group(1))
            else:
                # Try ISO date anywhere in response
                iso = re.search(r'\b(202[4-9]-\d{2}-\d{2})\b', raw)
                if iso:
                    pub_date = date.fromisoformat(iso.group(1))
                else:
                    # Try natural language date (e.g., "November 7, 2025")
                    import datetime as _dt
                    nat = re.search(
                        r'((?:January|February|March|April|May|June|July|August|'
                        r'September|October|November|December)\s+\d{1,2},?\s+202[4-9])',
                        raw
                    )
                    if nat:
                        clean = nat.group(1).replace(",", "")
                        pub_date = _dt.datetime.strptime(clean, "%B %d %Y").date()
                    else:
                        return None
            days_ago = (today - pub_date).days

            if days_ago <= 7:
                return None  # Confirmed recent — keep breaking
            elif days_ago <= 30:
                return "current"
            elif days_ago <= 730:
                return "recent"
            else:
                return "general"

        except Exception as e:
            logger.debug("Recency verification search failed: %s", e)
            return None

    def _count_proper_nouns(self, text: str) -> int:
        """Count proper nouns (capitalized words not at sentence start)."""
        words = text.split()
        if len(words) < 2:
            return 0
        skip = {"The", "A", "An", "In", "On", "At", "For", "And", "Or",
                "But", "With", "From", "To", "By", "Of", "Is", "Are",
                "Was", "Were", "Has", "Have", "Had", "Will", "Would",
                "Could", "Should", "May", "Might", "Can", "Do", "Does",
                "After", "Before", "During", "About", "Into", "Over",
                "Between", "Through", "Against", "Without", "Within"}
        return sum(1 for w in words[1:] if w[0:1].isupper() and w not in skip)

    def _needs_llm_classify(self, result: ParseResult) -> bool:
        """Decide if this ambiguous input warrants a Haiku second pass.
        Fires when mode is still "current" or "general" and:
        - Statements: proper noun + headline verb (original rule)
        - Questions: allowed through if they have at least one time signal
        - High-proper-noun inputs (3+): fire even without headline verb
          to catch analytical/descriptive headlines about specific events."""
        if result.mode not in ("general", "current"):
            return False
        lower = result.clean_topic.lower()
        if result.is_question:
            return self._has_time_signal(result)
        # Confirmed headline — always route through LLM to catch passive framing
        if result.is_headline:
            return True
        # Original gate: proper noun + headline verb
        if (self._has_proper_noun(result.clean_topic)
                and self._has_headline_verb(lower)):
            return True
        # Loosened gate: 3+ proper nouns even without a headline verb
        if self._count_proper_nouns(result.clean_topic) >= 3:
            return True
        return False

    def _llm_classify_temporal(self, text: str) -> str | None:
        """Lightweight Haiku call to classify implicit-recency inputs.
        Returns 'breaking', 'current', 'recent', or None on failure."""
        try:
            import anthropic
            from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_HAIKU
            from prompts.loader import load

            if not ANTHROPIC_API_KEY:
                return None

            client = anthropic.Anthropic(
                api_key=ANTHROPIC_API_KEY,
                timeout=3.0,  # hard 3s cap
            )
            response = client.messages.create(
                model=CLAUDE_MODEL_HAIKU,
                max_tokens=10,
                system=load("agents/temporal_classifier_system_prompt"),
                messages=[{"role": "user", "content": text}],
            )
            label = response.content[0].text.strip().lower()
            if label in ("breaking", "current", "recent", "general"):
                return label if label != "general" else None
            return None
        except Exception as e:
            logger.debug("Haiku temporal classify failed: %s", e)
            return None

    def _topic_from_url(self, url: str) -> str:
        from urllib.parse import urlparse
        path = urlparse(url).path
        segments = [s for s in path.strip("/").split("/") if s and not s.isdigit()]
        if not segments:
            return ""
        slug = segments[-1]
        slug = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", slug)
        text = slug.replace("-", " ").replace("_", " ").strip()
        # Title-case so proper noun detection works for URL-only inputs
        # (URL slugs are lowercase, which defeats _has_proper_noun)
        return text.title()


# ── Convenience function ────────────────────────────────────────────────────

_parser = InputParser()


def parse_input(raw_input: str) -> ParseResult:
    """Module-level convenience function."""
    return _parser.parse(raw_input)


# ── Test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "Judge temporarily halts Trump demand for race-based admissions data from universities",
        "First Amendment implications of social media content moderation by federal agencies",
        "Senate committee advances Voting Rights Act amendment with bipartisan support",
        "Mass incarceration rates and sentencing reform policy options",
        "https://www.reuters.com/world/us-judge-blocks-trump-forcing-colleges-disclose-data-race-2026-03-13/",
        "Supreme Court ruled on affirmative action in Students for Fair Admissions v. Harvard",
        "Immigration enforcement and Fourth Amendment due process rights",
        "President signs executive order restricting transgender athletes in school sports",
        "What are the policy implications of the Chevron deference doctrine?",
        "The case for universal healthcare reform",
        "Strike a balance between economic growth and environmental protection",
    ]

    for t in tests:
        r = parse_input(t)
        print(f"INPUT:    {t[:80]}")
        print(f"  mode:        {r.mode} {'(question)' if r.is_question else '(headline)' if r.is_headline else ''}")
        print(f"  domain:      {r.domain}{f' / {r.subdomain}' if r.subdomain else ''}"
              f"{f'  [also: {r.secondary_domain}]' if r.secondary_domain else ''}")
        print(f"  entities:    {r.entities}")
        print(f"  high_risk:   {r.high_risk_fields[:4]}")
        print(f"  scores:      {r.domain_scores}")
        print()