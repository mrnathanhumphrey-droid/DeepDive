# Task: Audit DeepDive's Historical Events List

**STRICT SCOPE — READ FIRST:**
- This is a **research and writing task only**. Do NOT write, generate, suggest, or offer any code — no Python, no JavaScript, no JSON modifications, no helper scripts, no regex snippets, no pseudo-code.
- Do NOT attempt to process the list programmatically or "validate" it with code.
- Do NOT propose tooling for applying the changes.
- The user has a separate coding assistant (Claude Code) that handles all code work. Your role is purely to do web research and produce a markdown report with two tables.
- If you feel the urge to write a script, stop. Produce the tables by hand based on web research and reasoning.

You are auditing a curated list of named historical events used as a keyword-match signal in a multi-agent news-analysis pipeline. The list gates whether a query routes to a "historical analysis" pipeline (primary sources, scholarly consensus, causal chain, counterfactuals) vs. a "current news" pipeline (wire services, recency-first).

The match is a **case-insensitive literal substring** of the user's query. There is no fuzzy match, no stemming, no semantic similarity. If the entry is `"Watergate"`, the query `"legacy of Watergate"` matches; the query `"the break-in at the Democratic HQ"` does not.

## Do NOT edit any files. Your deliverable is this report — markdown, tables, no code.

---

## Step 1 — Read the current list

Below is the full current [`data/historical_events.json`](historical_events.json). Four categories: `us_domestic`, `international`, `economic`, `legal_landmark`.

```json
{
    "us_domestic": [
        "Declaration of Independence", "Constitutional Convention", "Bill of Rights",
        "Louisiana Purchase", "Missouri Compromise", "Trail of Tears",
        "Mexican-American War", "Compromise of 1850", "Dred Scott", "Civil War",
        "Emancipation Proclamation", "Reconstruction", "13th Amendment",
        "14th Amendment", "15th Amendment", "Plessy v Ferguson",
        "Spanish-American War", "Progressive Era", "Federal Reserve Act",
        "19th Amendment", "Prohibition", "Scopes Trial", "Great Depression",
        "New Deal", "Social Security Act", "Wagner Act", "Dust Bowl",
        "Pearl Harbor", "Manhattan Project", "GI Bill", "Taft-Hartley Act",
        "Brown v Board of Education", "Montgomery Bus Boycott",
        "Interstate Highway Act", "Little Rock Nine", "Civil Rights Act of 1957",
        "Civil Rights Act of 1964", "Voting Rights Act",
        "Voting Rights Act of 1965", "Medicare and Medicaid",
        "Immigration Act of 1965", "Hart-Celler Act", "Great Society",
        "Gulf of Tonkin", "Vietnam War", "Tet Offensive", "Fair Housing Act",
        "Stonewall Riots", "Kent State", "Pentagon Papers", "Watergate",
        "War Powers Act", "Roe v Wade", "Title IX", "Clean Air Act",
        "Clean Water Act", "EPA creation", "OPEC oil embargo", "Church Committee",
        "Three Mile Island", "Iran Hostage Crisis", "Reaganomics",
        "War on Drugs", "Iran-Contra", "Americans with Disabilities Act",
        "Clarence Thomas hearings", "Anita Hill hearings", "LA Riots",
        "Rodney King", "NAFTA", "Oklahoma City bombing", "Welfare Reform Act",
        "Clinton impeachment", "Bush v Gore", "September 11", "9/11",
        "Patriot Act", "Iraq War", "Abu Ghraib", "Hurricane Katrina",
        "Great Recession", "2008 financial crisis", "Affordable Care Act",
        "Obamacare", "Citizens United", "Shelby County v Holder",
        "Obergefell v Hodges", "Dobbs v Jackson", "January 6",
        "January 6th insurrection", "Glass-Steagall", "Dodd-Frank",
        "No Child Left Behind", "Lochner era", "Korematsu",
        "Japanese internment", "Marshall Plan", "McCarthyism", "Red Scare",
        "Bay of Pigs", "Cuban Missile Crisis"
    ],
    "international": [
        "Treaty of Westphalia", "French Revolution", "Napoleonic Wars",
        "Congress of Vienna", "Industrial Revolution", "Scramble for Africa",
        "Berlin Conference", "Boxer Rebellion", "Russo-Japanese War",
        "World War I", "Treaty of Versailles", "League of Nations",
        "Russian Revolution", "Bolshevik Revolution", "Weimar Republic",
        "Great Depression", "Rise of Fascism", "Spanish Civil War", "Anschluss",
        "Munich Agreement", "World War II", "Holocaust", "Nuremberg Trials",
        "United Nations", "Bretton Woods", "NATO formation", "Berlin Blockade",
        "Berlin Airlift", "Korean War", "Suez Crisis", "Hungarian Revolution",
        "Bandung Conference", "Non-Aligned Movement", "Cuban Missile Crisis",
        "Six-Day War", "Prague Spring", "Yom Kippur War", "Camp David Accords",
        "Iranian Revolution", "Soviet-Afghan War", "Falklands War",
        "Tiananmen Square", "Fall of the Berlin Wall", "German Reunification",
        "Dissolution of the Soviet Union", "End of the Cold War", "Cold War",
        "Maastricht Treaty", "European Union", "Rwandan Genocide",
        "Bosnian War", "Srebrenica", "Dayton Accords", "Good Friday Agreement",
        "Asian Financial Crisis", "Kosovo War", "9/11 attacks", "War on Terror",
        "Afghanistan War", "Iraq War", "Arab Spring", "Fukushima",
        "Syrian Civil War", "Crimea annexation", "Brexit",
        "Paris Climate Agreement", "COVID-19 pandemic",
        "Russian invasion of Ukraine", "Hong Kong protests", "Apartheid",
        "End of Apartheid", "Partition of India", "Chinese Revolution",
        "Cultural Revolution", "Khmer Rouge", "Iranian Revolution", "Chernobyl",
        "Velvet Revolution", "Solidarity Movement", "Decolonization",
        "Algerian War", "Balfour Declaration", "Creation of Israel",
        "Oslo Accords", "Opium Wars", "Meiji Restoration",
        "Treaty of Tordesillas", "Atlantic Slave Trade", "Haitian Revolution",
        "Monroe Doctrine", "Roosevelt Corollary"
    ],
    "economic": [
        "Gold Standard", "Bretton Woods system", "Nixon Shock", "Petrodollar",
        "Stagflation", "Volcker Shock", "Plaza Accord", "Black Monday",
        "Savings and Loan Crisis", "Dot-com bubble", "Dot-com crash",
        "Enron scandal", "2008 financial crisis", "Great Recession",
        "Eurozone crisis", "Greek debt crisis", "Quantitative easing",
        "Smoot-Hawley Tariff", "Glass-Steagall Act", "Repeal of Glass-Steagall",
        "Sherman Antitrust Act", "Clayton Act", "Federal Reserve creation",
        "Panic of 1907", "Panic of 1893", "South Sea Bubble", "Tulip Mania",
        "Marshall Plan", "OPEC formation", "Oil embargo", "WTO creation",
        "GATT", "Washington Consensus", "Chinese economic reform",
        "Deng Xiaoping reforms"
    ],
    "legal_landmark": [
        "Marbury v Madison", "McCulloch v Maryland", "Gibbons v Ogden",
        "Dred Scott v Sandford", "Plessy v Ferguson", "Lochner v New York",
        "Schenck v United States", "Korematsu v United States",
        "Brown v Board of Education", "Mapp v Ohio", "Gideon v Wainwright",
        "Miranda v Arizona", "Loving v Virginia", "Tinker v Des Moines",
        "Griswold v Connecticut", "Roe v Wade", "New York Times v Sullivan",
        "Regents v Bakke", "Bush v Gore", "Citizens United v FEC",
        "Obergefell v Hodges", "Shelby County v Holder",
        "District of Columbia v Heller", "National Federation v Sebelius",
        "Dobbs v Jackson", "West Virginia v EPA", "Chevron v NRDC",
        "Loper Bright v Raimondo", "Wickard v Filburn",
        "Heart of Atlanta Motel v United States", "United States v Nixon",
        "Texas v Johnson", "Lawrence v Texas", "Grutter v Bollinger",
        "Students for Fair Admissions v Harvard", "Hamdi v Rumsfeld",
        "Boumediene v Bush", "Riley v California"
    ]
}
```

## Step 2 — Do targeted web searches for commonly-referenced historical events

Find events that:
- Are routinely cited in policy/political/academic/news discussion
- A user might reasonably query (e.g., "legacy of X", "impact of X", "what led to X")
- Are historically significant — **recency is not a gatekeeper** (the list already contains 2022 and 2024 entries like Dobbs and Loper Bright)

Cover these sub-domains systematically:

- **US domestic**: civil rights, labor, immigration, environmental, social movements, political scandals, landmark legislation
- **International**: wars, revolutions, diplomatic milestones, colonial/post-colonial events, regional upheavals
- **Economic**: crises, trade agreements, monetary regime changes, deregulation milestones, major policy shifts
- **Legal landmarks**: Supreme Court rulings, major lower-court cases with lasting impact

Known gaps the user has flagged for particular attention:

- **Protest/social movements**: Occupy Wall Street, Tea Party, Ferguson, BLM founding, Standing Rock, MeToo, March for Our Lives, Women's March
- **2010s-era events** generally (under-represented)
- **Non-US electoral events** of US relevance (Brexit precursors, major foreign elections)
- **Labor/union milestones** (PATCO strike, UAW strikes, etc.)
- **Indigenous-rights milestones** (beyond Trail of Tears / Standing Rock)
- **LGBTQ+ rights milestones** beyond the already-listed Stonewall / Obergefell / Lawrence

## Step 3 — Produce TWO tables

### Table A: Proposed additions (gaps)

| Proposed entry | Category | Approx year | Why it belongs | Existing coverage that might catch it |
|---|---|---|---|---|

"Existing coverage" is **substring-match only**. If the proposed entry is "Ferguson protests," check whether any existing entry contains the lowercased string "ferguson" — it doesn't, so write "none." If the proposed entry is "Trump 2016 election," note that the string "2016" is not in any existing entry; write "none." Don't hedge with semantic arguments — this is literal string matching.

Aim for 30–80 proposed additions total, spread across categories.

### Table B: Within-list overlap / redundancy analysis

| Entry A | Entry B | Relationship | Keep both? | Notes |
|---|---|---|---|---|

Relationship values:
- **Synonym variant**: two spellings of the same event (e.g., `9/11` + `September 11`) → keep both
- **Substring swallow**: A is a literal substring of B, so matching B also matches A (rare but check — e.g., does "Civil Rights Act" substring-match "Civil Rights Act of 1964"? Yes it does, so "Civil Rights Act of 1964" is redundant if "Civil Rights Act" exists)
- **Parent/child event**: related but separately searchable (e.g., `Vietnam War` / `Kent State` / `Tet Offensive` / `Gulf of Tonkin` — all different events, keep all)
- **Near-duplicate**: slightly different phrasings, worth consolidating

Focus on flagging **substring swallow** cases specifically. That's where the list has actual redundancy that could be cleaned up.

### Step 4 — Summary recommendations

A short closing section:
- Total count of proposed additions
- Any cleanups to existing list (substring swallows to remove, near-duplicates to consolidate)
- Any existing entries that are **too ambiguous as substrings** and should be removed — e.g., would `"Prohibition"` false-fire on queries about "prohibition of X" in other contexts? Would `"Bill of Rights"` over-fire on non-US contexts? Be concrete.

## Output format

Return the entire report as markdown. Don't write to a file. The user will paste it back into their DeepDive session to apply changes.

Keep it thorough but structured. No hedging, no padding. If a category looks well-covered, say so in one sentence and move on.
