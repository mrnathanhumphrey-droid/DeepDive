import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Disable web search verification for fast testing
import input_parser as ip
orig = ip.InputParser._verify_recency_via_search
ip.InputParser._verify_recency_via_search = lambda self, text: None

from input_parser import InputParser
p = InputParser()

PASS = FAIL = 0

def check(label, headline, expect_modes):
    global PASS, FAIL
    r = p.parse(headline)
    ok = r.mode in expect_modes
    icon = "PASS" if ok else "FAIL"
    print(f"{icon} [{r.mode:8}] {headline[:65]}")
    if ok: PASS += 1
    else:  FAIL += 1

check("MISS", "Chief Justice Roberts says personal criticism of judges is dangerous",   ["breaking","current","recent"])
check("MISS", "TSA agents face non-payment amid budget dispute",                        ["breaking","current","recent"])
check("MISS", "Cuba allows foreign nationals to invest in country",                     ["breaking","current","recent"])
check("MISS", "Republicans push back on new immigration executive order",               ["breaking","current","recent"])
check("MISS", "Senate Democrats oppose Trump judicial nominee",                         ["breaking","current","recent"])
check("MISS", "White House says tariff decision is final",                              ["breaking","current","recent"])
check("MISS", "Documents reveal FBI surveillance of journalist",                        ["breaking","current","recent"])
check("MISS", "Trump nominee faces bipartisan opposition in Senate",                    ["breaking","current","recent"])
check("MISS", "Biden warns of AI risks in farewell address",                            ["breaking","current","recent"])
check("MISS", "Pentagon signals readiness for Taiwan conflict",                         ["breaking","current","recent"])
check("MISS", "Iran claims successful satellite launch",                                ["breaking","current","recent"])
check("MISS", "Senate Majority Leader calls emergency session",                         ["breaking","current","recent"])
check("MISS", "NATO allies push back on US troop withdrawal plan",                      ["breaking","current","recent"])
check("MISS", "FDA warns about contaminated blood pressure medication",                  ["breaking","current","recent"])
check("MISS", "Fed signals pause on rate hikes amid cooling inflation",                 ["breaking","current","recent"])

check("OK",   "Judge temporarily halts Trump demand for race-based admissions data",    ["breaking","current","recent"])
check("OK",   "Israeli military strike targeted Iran security chief Larijani",          ["breaking","current","recent"])
check("OK",   "1 dead 1 injured during active shooter incident at Holloman air force base", ["breaking","current","recent"])
check("OK",   "College Republicans sue University of Florida president",                ["breaking","current","recent"])
check("OK",   "Senate debate voter ID bill today",                                      ["breaking","current","recent"])
check("OK",   "Trump says he will never endorse anyone who votes against Save Act",     ["breaking","current","recent"])

check("GEN",  "First Amendment implications of social media content moderation",        ["general"])
check("GEN",  "What is going to happen to the US economy if the Strait of Hormuz closes", ["general"])
check("GEN",  "Mass incarceration rates and sentencing reform policy options",          ["general"])
check("GEN",  "The case for universal healthcare reform",                               ["general"])
check("GEN",  "Immigration enforcement and Fourth Amendment due process rights",        ["general"])
check("GEN",  "The First Amendment and social media platform liability",                ["general"])
check("GEN",  "Second Amendment jurisprudence after Bruen decision",                   ["general"])
check("GEN",  "Electoral College reform and democratic representation",                 ["general"])

ip.InputParser._verify_recency_via_search = orig

print(f"\n{'='*55}")
print(f"  PASSED: {PASS}/29   FAILED: {FAIL}/29")
print(f"{'='*55}")
if FAIL:
    sys.exit(1)
