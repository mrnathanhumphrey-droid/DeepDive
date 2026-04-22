"""
orchestrator_patches.py
Helper functions imported by orchestrator.py for date-anchored
verification queries and domain-aware sub-topic generation.
"""

import re
from datetime import date


# ── Anchor verification helpers ─────────────────────────────────────────────

SEARCH_FAILURE_PHRASES = [
    "cannot verify", "no evidence", "could not confirm", "not found",
    "no results", "unable to verify", "no wire service", "no coverage found",
    "unverified", "cannot be confirmed", "found no", "unable to locate",
]


def _extract_date_context(engineered_topic: str) -> str:
    """Extract DATE_CONTEXT from the engineered prompt header."""
    m = re.search(r'^DATE_CONTEXT:\s*(.+)$', engineered_topic, re.MULTILINE)
    if m:
        return m.group(1).strip()
    today = date.today().strftime("%B %d, %Y")
    return f"TODAY IS {today}. Search ONLY for coverage from the past 7 days."


def _build_verify_query(anchor_event: str, date_context: str) -> str:
    """Build a date-anchored verification query for NewsFetchAgent."""
    return (
        f"{date_context} "
        f"VERIFY THIS SPECIFIC BREAKING EVENT — search only within the date window above. "
        f"Event to verify: {anchor_event}. "
        f"Search wire services first: AP, Reuters, AFP. "
        f"Return the exact headline, outlet, date, judge name if applicable, "
        f"and docket or case number if available. "
        f"If you cannot find wire service coverage within the date window, "
        f"say so explicitly — do NOT substitute a similar historical event."
    )


def _build_anchor_block(news_result, anchor_event: str) -> str:
    """Build anchor_block with success/failure guard."""
    search_succeeded = (
        news_result is not None
        and news_result.confidence > 0.3
        and not any(
            phrase in news_result.content.lower()
            for phrase in SEARCH_FAILURE_PHRASES
        )
        and len(news_result.content) > 100
    )

    if search_succeeded:
        return (
            f"\n\nVERIFIED CURRENT EVENT ANCHOR — treat as ground truth:\n"
            f"{news_result.content[:2000]}\n\n"
            f"All agents: Your analysis must be consistent with the above. "
            f"If your training knowledge contradicts it, the above takes precedence. "
            f"Do not fabricate alternative events.\n"
        )
    else:
        return (
            f"\n\nBREAKING EVENT CONTEXT — pre-verification was INCONCLUSIVE (not negative):\n"
            f"Event: '{anchor_event}'\n"
            f"Automated wire service pre-check did not return results. This is a SEARCH LIMITATION, "
            f"not evidence that the event did not occur. The story may be too recent for the "
            f"pre-check window, published by outlets not in the initial query, or indexed under "
            f"different keywords.\n\n"
            f"CRITICAL AGENT INSTRUCTIONS:\n"
            f"1. You MUST search independently using your own web search before drawing any conclusion "
            f"about whether this event occurred. Do NOT rely on the pre-check result above.\n"
            f"2. Search for: the headline text, key proper nouns, and wire service coverage (AP, Reuters, AFP, CBS, NBC, CNN)\n"
            f"3. If you find the event via your own search, treat it as confirmed and cite your source explicitly\n"
            f"4. If you cannot find it after thorough searching, write: 'Independent verification was inconclusive' — "
            f"NOT 'This event could not be confirmed' (absence of search results ≠ absence of event)\n"
            f"5. DO NOT fabricate case details, judge names, docket numbers, or ruling dates\n"
            f"6. A clearly flagged search limitation is more valuable than a premature negative conclusion\n"
        )


# ── Domain flag extraction ──────────────────────────────────────────────────

def _extract_domain_flags(engineered_topic: str) -> dict:
    """Extract parser metadata from the engineered prompt header."""
    flags = {}

    domain_m = re.search(r'^DOMAIN:\s*(.+)$', engineered_topic, re.MULTILINE)
    if domain_m:
        parts = domain_m.group(1).strip().split("/")
        flags["domain"] = parts[0].strip()
        flags["subdomain"] = parts[1].strip() if len(parts) > 1 else ""

    risk_m = re.search(r'^HIGH_RISK_FIELDS:\s*(.+)$', engineered_topic, re.MULTILINE)
    if risk_m:
        flags["high_risk_fields"] = [
            f.strip() for f in risk_m.group(1).split(",") if f.strip() != "none"
        ]

    priority_m = re.search(r'^SEARCH_PRIORITY:\s*(.+)$', engineered_topic, re.MULTILINE)
    if priority_m:
        flags["search_priority"] = [
            s.strip() for s in priority_m.group(1).split(",")
        ]

    date_m = re.search(r'^DATE_CONTEXT:\s*(.+)$', engineered_topic, re.MULTILINE)
    if date_m:
        flags["date_context"] = date_m.group(1).strip()

    return flags
