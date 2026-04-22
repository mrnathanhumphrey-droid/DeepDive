"""Regression test for the historical-mode detection gate.

Exercises weighted scoring: named event = 2 pts, marker/causal/year = 1 pt each,
threshold ≥ 2. Covers the rephrased-ambiguous entries and the new additions.

Usage: python scripts/historical_gate_regression.py
Exits 0 on pass, 1 on any failure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from input_parser import InputParser


# Each case: (query, expected_historical_bool, description)
CASES = [
    # ── Named event alone — NEW: fires on its own now ───────────────
    # Note: the match is (event_name in query). Short-form queries don't
    # match list entries stored as full forms (e.g., "Dobbs" alone does not
    # match "Dobbs v Jackson"). Use full forms or rely on marker phrasing.
    ("Watergate",                                          True,  "bare named event (list has bare 'Watergate')"),
    ("Dobbs v Jackson",                                    True,  "full case name matches"),
    ("Brown v Board of Education",                         True,  "bare case name (full form)"),
    ("Cuban Missile Crisis",                               True,  "bare event name (full form)"),

    # ── Named event + other signal — previously working ─────────────
    ("legacy of Watergate",                                True,  "marker + named event"),
    ("what caused the Iraq War",                           True,  "marker/causal + named event"),
    ("aftermath of the Dobbs v Jackson ruling",            True,  "marker + full case name"),

    # ── Previously ambiguous, now rephrased — should NOT fire ───────
    ("prohibition of torture under international law",     False, "was false-firing on 'Prohibition'; now 'Prohibition era'"),
    ("reconstruction of Ukraine after the war",            False, "was false-firing on 'Reconstruction'; now 'Reconstruction era'"),
    ("the Canadian bill of rights",                        False, "was false-firing on 'Bill of Rights'; now 'US Bill of Rights'"),
    ("our meeting is scheduled for January 6",             False, "was false-firing on bare 'January 6'; now 'January 6 insurrection'"),

    # ── New additions from the audit — should fire ──────────────────
    ("Standing Rock",                                      True,  "new entry, bare named event = 2 pts"),
    ("George Floyd protests",                              True,  "new entry"),
    ("impact of the October 7 attacks",                    True,  "new entry + marker"),
    ("Trump v United States ruling",                       True,  "new legal entry"),
    ("Moore v Harper decision",                            True,  "new legal entry"),
    ("FTX collapse aftermath",                             True,  "new econ entry + marker"),

    # ── Insufficient signals — should NOT fire ──────────────────────
    ("what happened in the 2012 election",                 False, "year alone (1 pt) — below threshold"),
    ("looking back on last year",                          False, "marker alone (1 pt) — below threshold"),
    ("this is a bare sentence with no markers",            False, "zero signals"),

    # ── Year + marker — previously working, still fires ─────────────
    ("looking back at 1965",                               True,  "marker + year = 2 pts"),
    ("legacy of the 2012 election",                        True,  "marker + year (2012 ≤ 2016)"),

    # ── Confirmed no-leaks (audit feared this, code prevents it) ────
    # Match is (event_name in query), so "ferguson shooting" does NOT
    # contain the full "plessy v ferguson" string — no false trigger.
    ("Ferguson shooting",                                  False, "no leak: 'plessy v ferguson' not contained in 'ferguson shooting'"),

    # ── Short-form aliases for high-frequency case/event names ──────
    # Detailed policy briefs typically use short forms ("Obergefell"
    # not "Obergefell v Hodges"). These aliases are in the list now.
    ("How has Obergefell affected lower courts rulings since",  True,  "canonical detailed policy query"),
    ("Dobbs created a patchwork of state laws",                 True,  "short form alias"),
    ("Post-Bruen gun litigation in federal courts",             True,  "short form alias"),
    ("Bostock and workplace discrimination law",                True,  "short form alias"),
    ("Loper Bright ends Chevron deference",                     True,  "short form alias"),
    ("five years after George Floyd, police reform stalled",    True,  "person short form for event"),

    # ── Truly ambiguous short forms still don't fire (by design) ─────
    # "McDonald" is too common a surname to add as short form for
    # McDonald v Chicago. Same for Miranda/Loving/Heller/Brown/Roe/etc.
    ("McDonald was decided in 2010",                            False, "ambiguous short form deliberately excluded"),
]


def main():
    parser = InputParser()
    failures = []
    passes = 0

    print(f"Running {len(CASES)} cases...\n")

    for query, expected, description in CASES:
        result = parser.parse(query)
        actual = (result.mode == "historical")
        status = "PASS" if actual == expected else "FAIL"

        if actual == expected:
            passes += 1
        else:
            failures.append((query, expected, actual, description, result.matched_current))

        marker = "[+]" if actual == expected else "[-]"
        expected_str = "historical" if expected else "not-historical"
        actual_str = result.mode
        print(f"  {marker} [{status}] expected={expected_str:15s}  got={actual_str:12s}  | {query[:55]}")

    print(f"\n{passes}/{len(CASES)} passed")

    if failures:
        print("\n--- FAILURES ---")
        for query, expected, actual, description, hits in failures:
            print(f"\nQuery: {query!r}")
            print(f"  Description: {description}")
            print(f"  Expected historical: {expected}")
            print(f"  Got historical:      {actual}")
            print(f"  Signals matched:     {hits}")
        sys.exit(1)

    print("\nAll regression cases pass.")
    sys.exit(0)


if __name__ == "__main__":
    main()
