"""Run 250 headlines through the parser and output classification dataset."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from input_parser import InputParser
from datetime import date
import input_parser as ip

# Disable web search verification for pure linguistic classification
orig_verify = ip.InputParser._verify_recency_via_search
ip.InputParser._verify_recency_via_search = lambda self, text: None
p = ip.InputParser()

today = date(2026, 3, 18)

# (headline, source, pub_date)
H = [
    # === DEMOCRACY NOW MARCH 2026 ===
    ("Israel Says It Killed Iran's Security Chief Ali Larijani", "DemocracyNow", "2026-03-17"),
    ("Iran Says Infant and Toddler Among Latest Victims of U.S.-Israeli Strikes", "DemocracyNow", "2026-03-17"),
    ("Rocket from Lebanon Injures 7 in Northern Israel", "DemocracyNow", "2026-03-17"),
    ("Baghdad Green Zone and UAE Oil Field Hit by Iranian Drones", "DemocracyNow", "2026-03-17"),
    ("Israel Attacks on Lebanon Have Driven 1 Million from Homes", "DemocracyNow", "2026-03-17"),
    ("U.S. Allies Refuse Trump Call to Send Warships to Hormuz", "DemocracyNow", "2026-03-17"),
    ("Kushner Seeks $5 Billion for Private Equity While Serving as Negotiator", "DemocracyNow", "2026-03-17"),
    ("Leqaa Kordia Released from ICE Jail After a Year", "DemocracyNow", "2026-03-17"),
    ("Federal Judge Blocks RFK Jr Changes to Childhood Vaccinations", "DemocracyNow", "2026-03-17"),
    ("Cuba National Electricity Grid Collapses", "DemocracyNow", "2026-03-17"),
    ("Afghanistan Says Pakistan Airstrike on Kabul Killed Over 400", "DemocracyNow", "2026-03-17"),
    ("Trump Admin Approves BP $5 Billion Drilling Project", "DemocracyNow", "2026-03-17"),
    ("Voters in Illinois Head to Polls for Primary Elections", "DemocracyNow", "2026-03-17"),
    ("War on Iran Enters Third Week", "DemocracyNow", "2026-03-16"),
    ("Iran Retaliatory Strikes Kill Six U.S. Service Members in Iraq", "DemocracyNow", "2026-03-16"),
    ("Trump Urges Countries to Send Warships to Secure Hormuz", "DemocracyNow", "2026-03-16"),
    ("Israeli Troops Begin Ground Operations in Southern Lebanon", "DemocracyNow", "2026-03-16"),
    ("FCC Chair Threatens to Revoke Broadcasters Licenses over War Coverage", "DemocracyNow", "2026-03-16"),
    ("Israeli Forces Kill 16 Palestinians in Gaza and West Bank", "DemocracyNow", "2026-03-16"),
    ("Trump Reopens U.S. Embassy in Venezuela", "DemocracyNow", "2026-03-16"),
    ("Haitian Asylum Seeker Found Dead After ICE Release", "DemocracyNow", "2026-03-16"),
    ("Afghan Asylum Seeker Dies in ICE Custody", "DemocracyNow", "2026-03-16"),
    ("Anti-ICE Protesters Convicted on Terrorism Charges in Texas", "DemocracyNow", "2026-03-16"),
    ("Immigration Judge Orders Release of Palestinian Activist", "DemocracyNow", "2026-03-16"),
    ("Iran Says Strikes Have Killed 1348 Civilians", "DemocracyNow", "2026-03-12"),
    ("Senators Demand Accountability as Pentagon Admits Striking School", "DemocracyNow", "2026-03-12"),
    ("IEA Announces Record Release of Oil Reserves", "DemocracyNow", "2026-03-12"),
    ("Lebanon Death Toll Tops 630", "DemocracyNow", "2026-03-12"),
    ("Israel Strikes Gaza Marketplace Killing Palestinians", "DemocracyNow", "2026-03-12"),
    ("RSF Drone Strike in Sudan Kills 17", "DemocracyNow", "2026-03-12"),
    ("Cornyn Reverses Position on Filibuster for SAVE Act", "DemocracyNow", "2026-03-12"),
    ("New Hampshire Democrat Victory Red Flag for GOP", "DemocracyNow", "2026-03-12"),
    ("Epstein Accountant Testifies to Congress", "DemocracyNow", "2026-03-12"),
    ("Family of Six Detained at ICE Jail in Texas", "DemocracyNow", "2026-03-12"),
    ("War on Iran Enters 12th Day", "DemocracyNow", "2026-03-11"),
    ("Pentagon Considers Special Forces Deployment into Iran", "DemocracyNow", "2026-03-11"),
    ("Evidence U.S. Forces Struck Girls School in Iran", "DemocracyNow", "2026-03-11"),
    ("Israel Continues Attacks on Lebanon Killing 570", "DemocracyNow", "2026-03-11"),
    ("Iran Fires Retaliatory Missiles at Targets Across Gulf", "DemocracyNow", "2026-03-11"),
    ("Anthropic Sues Trump Admin Over Supply Chain Designation", "DemocracyNow", "2026-03-11"),
    ("Alabama Governor Commutes Death Sentence", "DemocracyNow", "2026-03-11"),
    ("Justice Department Reaches Settlement with Live Nation", "DemocracyNow", "2026-03-11"),
    ("Federal Judge Restricts ICE from Using Tear Gas on Protests", "DemocracyNow", "2026-03-11"),
    ("Trump Denies Responsibility for Bombing Girls School in Iran", "DemocracyNow", "2026-03-10"),
    ("Huge Crowds Rally in Tehran", "DemocracyNow", "2026-03-10"),
    ("State Department Orders Diplomats to Leave Saudi Arabia", "DemocracyNow", "2026-03-10"),
    ("Oil Prices Fall After Soaring to $120", "DemocracyNow", "2026-03-10"),
    ("FBI Requests Arizona Voting Records for 2020 Election", "DemocracyNow", "2026-03-10"),
    ("DOJ Releases Epstein Files", "DemocracyNow", "2026-03-10"),
    ("Video Refutes ICE Claim About Martinez Shooting", "DemocracyNow", "2026-03-10"),
    ("Two Charged with Terrorism for Bombs Outside NYC Mayor Home", "DemocracyNow", "2026-03-10"),
    ("Judge Rules Kari Lake Unlawfully Led Global Media Agency", "DemocracyNow", "2026-03-10"),
    # === DEMOCRACY NOW MARCH 3 ===
    ("Death Toll Climbs to 787 as U.S. and Israel Bomb Iran", "DemocracyNow", "2026-03-03"),
    ("No Radiation Release After Strike on Natanz Nuclear Facility", "DemocracyNow", "2026-03-03"),
    ("Israel Bombs Beirut as Soldiers Reinvade Lebanon", "DemocracyNow", "2026-03-03"),
    ("Rubio Says Israel War Plans Compelled U.S. to Join Assault", "DemocracyNow", "2026-03-03"),
    ("Pentagon Used Claude AI to Attack Iran", "DemocracyNow", "2026-03-03"),
    ("DOJ Indicts 30 over Minnesota Church Protest", "DemocracyNow", "2026-03-03"),
    ("U.S. Attorney Faces Contempt Charges for Defying Court", "DemocracyNow", "2026-03-03"),
    ("Iraqi Feminist Activist Murdered in Baghdad", "DemocracyNow", "2026-03-03"),
    # === FEBRUARY 2026 ===
    ("Mandelson Arrested Amid Epstein Probe", "DemocracyNow", "2026-02-24"),
    ("U.S. Military Strikes Boat in Caribbean Killing Three", "DemocracyNow", "2026-02-24"),
    ("Mexico on Alert After Killing of Drug Lord El Mencho", "DemocracyNow", "2026-02-24"),
    ("Russia Invasion of Ukraine Reaches Fourth Anniversary", "DemocracyNow", "2026-02-24"),
    ("Judge Blocks DOJ from Releasing Special Counsel Report", "DemocracyNow", "2026-02-24"),
    ("Former ICE Attorney Accuses Agency of Lying to Congress", "DemocracyNow", "2026-02-24"),
    ("Pentagon Killed 2 in Attack on Boat in Eastern Pacific", "DemocracyNow", "2026-02-10"),
    ("Airlines Suspend Flights as Cuba Runs Out of Jet Fuel", "DemocracyNow", "2026-02-10"),
    ("Israel Security Cabinet Expands West Bank Settlements", "DemocracyNow", "2026-02-10"),
    ("Federal Court Strikes Down California Law on Federal Agents", "DemocracyNow", "2026-02-10"),
    ("Immigration Judge Rejects Deportation of Tufts Student", "DemocracyNow", "2026-02-10"),
    ("Maxwell Pleads the Fifth in House Deposition", "DemocracyNow", "2026-02-10"),
    ("53 Dead After Migrant Boat Sinks Off Libya", "DemocracyNow", "2026-02-10"),
    ("Teachers Striking for Salary Increases in San Francisco", "DemocracyNow", "2026-02-10"),
    # === JANUARY 2026 ===
    ("Trump Threatens Tariffs on 8 European Countries over Greenland", "DemocracyNow", "2026-01-20"),
    ("Pentagon Prepares Soldiers for Deployment to Minnesota", "DemocracyNow", "2026-01-20"),
    ("Trump Calls for Regime Change in Iran", "DemocracyNow", "2026-01-20"),
    ("Israeli Forces Start Demolishing UNRWA Headquarters", "DemocracyNow", "2026-01-20"),
    ("Guatemala Declares State of Emergency", "DemocracyNow", "2026-01-20"),
    ("Sharpton Denounces ICE Killing of Renee Good at MLK Rally", "DemocracyNow", "2026-01-20"),
    ("Activist Groups Call for Nationwide Walkout", "DemocracyNow", "2026-01-20"),
    ("DOJ Looking to Weaken Gun Laws", "DemocracyNow", "2026-01-20"),
    # === DECEMBER 2025 ===
    ("15 Killed in Mass Shooting at Hanukkah Event in Australia", "DemocracyNow", "2025-12-15"),
    ("Trump Vows Retaliation After Americans Killed in Syria", "DemocracyNow", "2025-12-15"),
    ("Hamas Confirms Death of Senior Commander", "DemocracyNow", "2025-12-15"),
    ("Chile Elects Far-Right Kast as President", "DemocracyNow", "2025-12-15"),
    ("Nobel Laureate Mohammadi Arrested in Iran", "DemocracyNow", "2025-12-15"),
    ("Jimmy Lai Found Guilty in Hong Kong Security Trial", "DemocracyNow", "2025-12-15"),
    ("Belarus Releases 123 Political Prisoners", "DemocracyNow", "2025-12-15"),
    ("Omar Says Agents Asked Son for Proof of Citizenship", "DemocracyNow", "2025-12-15"),
    ("National Trust Sues to Stop White House Ballroom", "DemocracyNow", "2025-12-15"),
    ("Venezuela Condemns Trump Closing Airspace Declaration", "DemocracyNow", "2025-12-01"),
    ("Gaza Death Toll Surpasses 70000 Palestinians", "DemocracyNow", "2025-12-01"),
    ("Israeli Forces Shoot Two Palestinians in West Bank", "DemocracyNow", "2025-12-01"),
    ("Trump Halts All Asylum Applications After Guard Shooting", "DemocracyNow", "2025-12-01"),
    ("Trump Cancels Biden Executive Orders Signed by Autopen", "DemocracyNow", "2025-12-01"),
    ("Judge Dismisses Georgia Election Case Against Trump", "DemocracyNow", "2025-12-01"),
    ("Babson Student Deported to Honduras During Thanksgiving", "DemocracyNow", "2025-12-01"),
    ("4 Killed in Mass Shooting at Birthday Party in Stockton", "DemocracyNow", "2025-12-01"),
    ("Court Orders ICE to Stop Unlawful Arrest of Refugees", "IRAP", "2025-12-20"),
    ("ICE Deporting Immigrants So Fast Attorneys Scramble", "NPR", "2025-12-26"),
    # === NOVEMBER 2025 ===
    ("Israeli Airstrikes Kill 24 Despite Ceasefire", "DemocracyNow", "2025-11-24"),
    ("Airstrike Kills Hezbollah Acting Chief of Staff", "DemocracyNow", "2025-11-24"),
    ("Trump Designates Maduro as Foreign Terrorist", "DemocracyNow", "2025-11-24"),
    ("Democrats File Police Complaints After Trump Sedition Posts", "DemocracyNow", "2025-11-24"),
    ("Trump Denied Disaster Aid to Chicago After Storms", "DemocracyNow", "2025-11-24"),
    ("ICE Agents Abduct 17-Year-Old Student in Oregon", "DemocracyNow", "2025-11-24"),
    ("SCOTUS Restores Texas Map Declared Illegal Gerrymander", "DemocracyNow", "2025-11-24"),
    ("Bolsonaro Arrested After Tampering with Ankle Monitor", "DemocracyNow", "2025-11-24"),
    ("Trump Pardons Allies Who Tried to Overturn 2020 Election", "DemocracyNow", "2025-11-10"),
    ("7 Democrats Join Republicans to Pass Shutdown Bill", "DemocracyNow", "2025-11-10"),
    ("Trump Orders States to Stop Full SNAP Benefits", "DemocracyNow", "2025-11-10"),
    ("Judge Permanently Blocks Troop Deployment to Portland", "DemocracyNow", "2025-11-10"),
    ("Chicago Mayor Calls on UN to Probe Immigration Crackdown", "DemocracyNow", "2025-11-10"),
    ("Video Shows Man Having Seizure During ICE Arrest", "DemocracyNow", "2025-11-10"),
    ("Trump to Boycott G20 Hosted by South Africa", "DemocracyNow", "2025-11-10"),
    ("Federal Court Affirms Right to Bond Hearings", "ACLU", "2025-11-01"),
    # === OCTOBER 2025 ===
    ("Trump Addresses Knesset as Captives Exchanged", "DemocracyNow", "2025-10-13"),
    ("Trump Warns of More Layoffs at CDC and Education", "DemocracyNow", "2025-10-13"),
    ("Appeals Court Blocks National Guard Deployment to Chicago", "DemocracyNow", "2025-10-13"),
    ("Chicago Protesters Demand ICE Funds for Social Programs", "DemocracyNow", "2025-10-13"),
    ("60 Killed by Paramilitary Attacks in Sudan", "DemocracyNow", "2025-10-13"),
    ("Trump Threatens 100% Tariffs on China", "DemocracyNow", "2025-10-13"),
    ("8 Charged with Felonies for Assisting Outlawed Abortions", "DemocracyNow", "2025-10-13"),
    ("16 Killed as Explosion Destroys Tennessee Factory", "DemocracyNow", "2025-10-13"),
    ("Gaza Ceasefire Talks Begin in Egypt", "DemocracyNow", "2025-10-06"),
    ("Judge Blocks Guard Deployment to Oregon", "DemocracyNow", "2025-10-06"),
    ("Trump Uses Shutdown to Withhold Funding from Democratic Cities", "DemocracyNow", "2025-10-06"),
    ("Russia Fires 50 Missiles and 500 Drones at Ukraine", "DemocracyNow", "2025-10-06"),
    ("Pro-Palestinian Protests Erupt Worldwide", "DemocracyNow", "2025-10-06"),
    ("Journalist Guevara Deported After 100 Days ICE Detention", "DemocracyNow", "2025-10-06"),
    # === ACLU / SCOTUS / LEGAL ===
    ("Supreme Court Allows Discriminatory Passport Policy", "ACLU", "2026-02-15"),
    ("Supreme Court Hears Transgender Rights Arguments", "ACLU", "2026-01-15"),
    ("Supreme Court Hears Landmark Voting Rights Case", "ACLU", "2025-12-10"),
    ("Education Department Backs Down on DEI Directive", "ACLU", "2026-03-01"),
    ("ACLU Responds to Skrmetti Transgender Ruling", "ACLU", "2026-02-01"),
    ("Supreme Court Strikes Down Trump Tariffs", "NBC", "2026-02-20"),
    ("Court Allows Trump to Slash Education Workforce", "WaPo", "2026-01-10"),
    ("Supreme Court Blocks Religious Public Charter School", "AP", "2025-12-01"),
    ("Supreme Court Orders New Trial for Death Row Inmate Glossip", "AP", "2025-11-15"),
    ("Supreme Court Rules Parents Can Opt Out of LGBTQ Lessons", "AP", "2025-11-01"),
    ("Supreme Court Bars Redrawing NYC Congressional District", "CNBC", "2026-03-02"),
    ("States Sue to Block Trump Latest Tariffs", "CNBC", "2026-03-05"),
    ("Fourth Circuit Allows DEI Executive Orders to Proceed", "Law360", "2026-02-06"),
    ("Federal Court Blocks Texas Congressional Map for 2026", "NPR", "2025-11-18"),
    ("Trump Admin Seeks to Cancel Thousands of Asylum Cases", "CBS", "2026-01-15"),
    ("Court Blocks Deportation of 6000 Syrians with TPS", "AP", "2026-03-15"),
    ("16 States Enact 31 Restrictive Voting Laws", "Brennan", "2025-10-01"),
    ("SAVE America Act Passes Senate", "RollCall", "2026-03-14"),
    ("Illinois Lt Gov Stratton Wins Democratic Senate Primary", "AP", "2026-03-18"),
    ("Missouri Supreme Court Reinstates Abortion Restrictions", "MissouriInd", "2025-05-27"),
    ("Ohio Court Upholds Block on Abortion Burial Law", "ACLU", "2026-02-01"),
    ("Virginia Governor Signs Reproductive Freedom Bill", "AP", "2026-02-06"),
    ("Trump Signs Executive Order Ending DEI for Contractors", "Harvard", "2025-01-21"),
    ("EEOC and DOJ Warn DEI Programs May Violate Title VII", "DOJ", "2025-03-19"),
    ("Judge Orders Reversal of Layoffs During Shutdown", "FedNews", "2025-12-17"),
    ("Judge Dismisses Georgia Election Case Against Trump", "AP", "2025-12-01"),
    ("Trump Signs Order Defining Sex in Binary Terms", "WhiteHouse", "2025-01-20"),
    ("Supreme Court Allows Transgender Military Ban", "SCOTUSblog", "2025-05-06"),
    ("Pentagon Discharges 1000 Transgender Service Members", "Military", "2025-07-01"),
    ("Judge Blocks Transgender Military Ban as Unconstitutional", "ACLU", "2025-03-15"),
    ("Florida Leads Nation with Most Book Bans", "PEN", "2025-09-15"),
    ("ACLU Tracks 500 Anti-LGBTQ Bills in Legislatures", "ACLU", "2025-06-01"),
    ("NAACP Sues Philadelphia Over Airport Ad", "ACLU", "2025-08-01"),
    ("Trump Rolls Back Civil Rights Protections for Contractors", "CivilRights", "2025-02-01"),
    ("Supreme Court Unanimously Rules for NRA Free Speech", "ACLU", "2025-06-15"),
    ("Court Protects First Amendment Rights of Human Rights Groups", "ACLU", "2025-09-01"),
    ("Court Rules for Artists Against National Endowment", "ACLU", "2025-07-15"),
    ("Oklahoma Students Ask Court to Block Censorship Law", "ACLU", "2025-10-01"),
    ("Thousands Rally in No Kings Protests", "DemocracyNow", "2025-06-15"),
    ("Ex-Marine Candidate Arrested at Iran War Protest", "DemocracyNow", "2026-03-11"),
    ("College Republicans Sue University of Florida President", "AP", "2026-03-15"),
    ("DOJ Sues Tech Company for Race-Based Hiring", "Reuters", "2026-01-10"),
    # === AL JAZEERA ===
    ("Iran Threatens to Strike Gulf Energy Facilities", "AlJazeera", "2026-03-18"),
    ("Israel Kills Iran Intel Minister in Third Assassination", "AlJazeera", "2026-03-18"),
    ("Iran Launches Revenge Missile Attack on Israel", "AlJazeera", "2026-03-14"),
    ("Iran Holds Funerals for Officials Larijani and Soleimani", "AlJazeera", "2026-03-18"),
    ("Trump Confirms Xi Meeting Delayed as War Rages", "AlJazeera", "2026-03-17"),
    ("European Groups Join Aid Convoy to Cuba", "AlJazeera", "2026-03-18"),
    ("Pro-Israel Groups Mixed Record in Illinois Primaries", "AlJazeera", "2026-03-18"),
    ("Trump Says He May Hit Kharg Island Again Just for Fun", "AlJazeera", "2026-03-15"),
    ("Judge Blocks DOGE Access to Social Security Data", "NPR", "2026-03-05"),
    ("Federal Judge Halts HHS Vaccine Committee Decisions", "NPR", "2026-03-16"),
    ("Cuba Plunged into Island-Wide Blackout", "AP", "2026-03-17"),
    ("Pakistan Airstrike on Afghan Capital Kills Over 400", "AP", "2026-03-17"),
    ("Ukraine Sends Drone Experts to Counter Iranian Attacks", "Reuters", "2026-03-10"),
    ("Israel Accused of Resuming Starvation Policy in Gaza", "DemocracyNow", "2026-03-03"),
    ("Supreme Court Declines to Hear Death Penalty Appeal", "AP", "2025-10-01"),
    ("Idaho Abortion Campaign Collects 63000 Signatures", "Axios", "2026-01-15"),
    ("CMS Proposes Removing Orientation Questions from Medicare", "KFF", "2025-07-01"),
    ("New Jersey Judge Bars Discharge of Transgender Troops", "GLAD", "2025-04-01"),
    ("DC Appeals Court Keeps Transgender Military Ban", "Advocate", "2025-09-01"),
    ("ICE Agent Shoots Kills Woman in Minneapolis Arrest", "AP", "2026-01-20"),
]

rows = []
for headline, source, pub_date_str in H:
    r = p.parse(headline)
    pub_date = date.fromisoformat(pub_date_str)
    days_ago = (today - pub_date).days
    rows.append({
        "headline": headline,
        "source": source,
        "pub_date": pub_date_str,
        "days_ago": days_ago,
        "parser_mode": r.mode,
        "domain": r.domain,
        "subdomain": r.subdomain or "",
    })

ip.InputParser._verify_recency_via_search = orig_verify

total = len(rows)
modes = {}
domains = {}
for r in rows:
    modes[r["parser_mode"]] = modes.get(r["parser_mode"], 0) + 1
    domains[r["domain"]] = domains.get(r["domain"], 0) + 1

print(f"TOTAL HEADLINES: {total}")
print()
print("=== MODE DISTRIBUTION ===")
for m in ["breaking", "current", "recent", "general"]:
    c = modes.get(m, 0)
    print(f"  {m.upper():10} {c:3} ({c*100//total}%)")
print()
print("=== DOMAIN DISTRIBUTION ===")
for d in sorted(domains.keys(), key=lambda x: -domains[x]):
    c = domains[d]
    print(f"  {d:15} {c:3} ({c*100//total}%)")
print()
print(f"{'SOURCE':<14} {'DATE':10} {'DAYS':>4} {'MODE':>8} {'DOMAIN':>12} {'HEADLINE'}")
print("=" * 130)
for r in rows:
    print(f"{r['source']:<14} {r['pub_date']:10} {r['days_ago']:>4} {r['parser_mode'].upper():>8} {r['domain']:>12} {r['headline'][:70]}")

with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results', 'headline_classification_250.json'), 'w') as f:
    json.dump({"total": total, "modes": modes, "domains": domains, "headlines": rows}, f, indent=2)
print(f"\nDataset saved to results/headline_classification_250.json")
