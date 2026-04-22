"""Merge the user's 225-account dataset into approved_twitter_accounts.json.
Deduplicates across all categories."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

user_handles = [
    "POTUS","WhiteHouse","VP","FLOTUS","PressSec","10DowningStreet","KeirStarmer",
    "Elysee","EmmanuelMacron","gouvernementFR","BundeskanzlerDE","Bundestag",
    "JustinTrudeau","MarkCarney","Canada","AlboMP","AusGovPM","JPN_PMO",
    "narendramodi","PMOIndia","MEAIndia","LulaOficial","govbr","PresidencyZA",
    "CyrilRamaphosa","IsraeliPM","IsraelMFA","MFAofChina","RussianEmbassy",
    "IndianDiplomacy","TurkishMFA","SpainMFA","ItalyMFA_EN",
    "UN","UNGeneva","UNNews_Centre","NATO","EUCouncil","EU_Commission",
    "Europarl_EN","WHO","UNICEF","WFP","UNHCR","IMFNews","WorldBank","WTO",
    "IAEA","OPCW","IntlCrimCourt","AU_Summit","ASEAN","OAS_OEA","G20org","OECD",
    "AP","Reuters","AFP","UPI","EFEAgencia","ANSAEnglish","dpa_intl","KyodoNews_intl",
    "CNN","BBCNews","nytimes","washingtonpost","WSJ","NPR","CBSNews","NBCNews",
    "ABC","MSNBC","FoxNews","PBS","TIME","TheAtlantic","Newsweek","politico",
    "thehill","axios","propublica","slate","vox",
    "BBCWorld","BBCBreaking","guardian","Telegraph","Independent","FinancialTimes",
    "thetimes","Daily_Express","MirrorPolitics","eveningstandard","MailOnline",
    "Channel4News","SkyNews","itvnews",
    "derspiegel","zeitonline","FAZ_NET","lemondefr","libe","le_Figaro",
    "ElPais","elmundoes","repubblica","CorrieredellaSera","nrc","nponieuws",
    "svtnyheter","Aftonbladet","nrknyheter","dagbladet","YLE","DRNyheder",
    "SRF","NZZaS","euronews","EURACTIV","politicoeurope",
    "AJEnglish","AJArabic","AlArabiya_Eng","skynewsarabia","Haaretz",
    "TimesofIsrael","Jerusalem_Post","arabnews","DailySabah","PressTV","RT_com",
    "SpokespersonCHN","NHK_WORLD_News","Kyodo_English","SCMPNews","HKFPnews",
    "straits_times","ChannelNewsAsia","NDTV","HindustanTimes","TheHindu",
    "IndianExpress","PakistanToday","geo_urdu",
    "ABCaustralia","smh","theage","Australian","nzherald","RNZ_News",
    "KoreaTimes","KoreaJoongAng","bangkokpost","PhilStar","jakartaglobe",
    "VietnamNews_VNS","MyanmarTimes",
    "dailymaverick","MailGuardian","TimesLIVE","NairobiBusiness","StandardKenya",
    "PunchNigeria","GuardianNigeria","Vanguard_News","APA_news","AllAfricacom",
    "EthiopianMonitor","SheggerMedia",
    "Folha","estadao","BBCBrasil","lanacion","ElUniversalMex","Reforma",
    "eltiempo","SemanaNews","elpais_america","mercopress",
    "tassagency","interfax_news","Ukrinform","kyivindependent","RFE_RL",
    "polsatnews","TVPWorld",
    "StateDept","Pentagon","DeptofDefense","DHSgov","CIA","FBI","NSAGov","USAID",
    "USTreasury","commercegov","HHSGov","CDCgov","NIH","US_FDA","EPA","USDOT",
    "USDOE","USDA","NASA","NSF","FTC","SECGov","FEMA","USCIS","CBP","ICEgov",
    "HouseGOP","HouseDemocrats","SenateGOP","SenateDems","SpeakerJohnson",
    "SenSchumer","SenMcConnell","GOPLeader","HakimJeffries",
    "GovAbbott","GovNewsom","GovRonDeSantis","GovWhitmer","GovHochul",
    "GovernorIllinois","GovPritzker","GavinNewsom","GovDeWine",
    "UKParliament","HouseofCommons","HouseofLords","FCDOGovUK","DefenceHQ",
    "HMTreasury","homeoffice","GOVUK","ukhsa","NHSuk","AusGovDFAT",
    "DeutscheWelle","France24","RTHK_enews","TVNZ","CBC","Radio_Canada",
    "VOANews","VOAfarsi","RadioFreeEurope","RFI_English","CGTN","KBSWorldService",
]

# Category mapping for new handles
CATEGORY_MAP = {
    # World leaders / heads of state
    "FLOTUS": "world_leaders", "PressSec": "us_government",
    "KeirStarmer": "world_leaders", "gouvernementFR": "world_leaders",
    "BundeskanzlerDE": "world_leaders", "MarkCarney": "world_leaders",
    "Canada": "world_leaders", "AlboMP": "world_leaders", "AusGovPM": "world_leaders",
    "CyrilRamaphosa": "world_leaders", "PresidencyZA": "world_leaders", "govbr": "world_leaders",
    # Intl orgs
    "UNGeneva": "international_orgs", "UNNews_Centre": "international_orgs",
    "EUCouncil": "international_orgs", "UNICEF": "international_orgs",
    "WFP": "international_orgs", "UNHCR": "international_orgs",
    "AU_Summit": "international_orgs", "OAS_OEA": "international_orgs",
    "G20org": "international_orgs",
    # Foreign government
    "MFAofChina": "foreign_government", "RussianEmbassy": "foreign_government",
    "IndianDiplomacy": "foreign_government", "TurkishMFA": "foreign_government",
    "SpainMFA": "foreign_government", "ItalyMFA_EN": "foreign_government",
    "SpokespersonCHN": "foreign_government", "DefenceHQ": "foreign_government",
    "HMTreasury": "foreign_government", "homeoffice": "foreign_government",
    "GOVUK": "foreign_government", "ukhsa": "foreign_government",
    "NHSuk": "foreign_government", "AusGovDFAT": "foreign_government",
    "UKParliament": "foreign_government", "HouseofCommons": "foreign_government",
    "HouseofLords": "foreign_government", "Bundestag": "foreign_government",
    "MEAIndia": "foreign_government", "PMOIndia": "foreign_government",
    # US gov agencies
    "CIA": "us_government", "NSAGov": "us_government", "commercegov": "us_government",
    "NIH": "us_government", "USDOE": "us_government", "NASA": "us_government",
    "NSF": "us_government", "Pentagon": "us_government",
    # US legislative
    "GOPLeader": "us_legislative", "HakimJeffries": "us_legislative",
    # Wire services
    "UPI": "wire_services", "EFEAgencia": "wire_services", "ANSAEnglish": "wire_services",
    "dpa_intl": "wire_services", "KyodoNews_intl": "wire_services",
    "Kyodo_English": "wire_services", "APA_news": "wire_services",
    "mercopress": "wire_services", "tassagency": "wire_services",
    "interfax_news": "wire_services", "Ukrinform": "wire_services",
}

# State governors -> new category
STATE_GOVS = [
    "GovAbbott","GovNewsom","GovRonDeSantis","GovWhitmer","GovHochul",
    "GovernorIllinois","GovPritzker","GavinNewsom","GovDeWine",
]

# Load approved
approved = json.load(open("data/approved_twitter_accounts.json"))

# Build existing set (lowercased) for dedup
existing = set()
for k, v in approved.items():
    if not k.startswith("_") and isinstance(v, list):
        existing.update(h.lower() for h in v)

# Add state governors category
if "us_state_governors" not in approved:
    approved["us_state_governors"] = []

added = 0
skipped = 0
for handle in user_handles:
    if handle.lower() in existing:
        skipped += 1
        continue

    # Determine category
    if handle in CATEGORY_MAP:
        cat = CATEGORY_MAP[handle]
    elif handle in STATE_GOVS:
        cat = "us_state_governors"
    else:
        cat = "major_news"  # Default: news org

    if cat not in approved:
        approved[cat] = []
    approved[cat].append(handle)
    existing.add(handle.lower())
    added += 1

# Deduplicate within each category
for k in approved:
    if not k.startswith("_") and isinstance(approved[k], list):
        seen = set()
        deduped = []
        for h in approved[k]:
            if h.lower() not in seen:
                seen.add(h.lower())
                deduped.append(h)
        approved[k] = deduped

# Save
with open("data/approved_twitter_accounts.json", "w") as f:
    json.dump(approved, f, indent=2)

total = sum(len(v) for k, v in approved.items() if not k.startswith("_") and isinstance(v, list))
print(f"User provided: {len(user_handles)} handles")
print(f"Already present: {skipped}")
print(f"Added: {added}")
print(f"Total approved (deduplicated): {total}")
print()
for k, v in approved.items():
    if not k.startswith("_") and isinstance(v, list):
        print(f"  {k:30} {len(v):4}")
