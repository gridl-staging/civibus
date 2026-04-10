
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "docs" / "research" / "coverage-registry.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "research" / "jurisdiction-master.csv"

# 2020 US Census state populations (source: census.gov/2020census)
STATE_POPULATIONS_2020: dict[str, int] = {
    "AL": 5_024_279,
    "AK": 733_391,
    "AZ": 7_151_502,
    "AR": 3_011_524,
    "CA": 39_538_223,
    "CO": 5_773_714,
    "CT": 3_605_944,
    "DE": 989_948,
    "DC": 689_545,
    "FL": 21_538_187,
    "GA": 10_711_908,
    "HI": 1_455_271,
    "ID": 1_839_106,
    "IL": 12_812_508,
    "IN": 6_785_528,
    "IA": 3_190_369,
    "KS": 2_937_880,
    "KY": 4_505_836,
    "LA": 4_657_757,
    "ME": 1_362_359,
    "MD": 6_177_224,
    "MA": 7_029_917,
    "MI": 10_077_331,
    "MN": 5_706_494,
    "MS": 2_961_279,
    "MO": 6_154_913,
    "MT": 1_084_225,
    "NE": 1_961_504,
    "NV": 3_104_614,
    "NH": 1_377_529,
    "NJ": 9_288_994,
    "NM": 2_117_522,
    "NY": 20_201_249,
    "NC": 10_439_388,
    "ND": 779_094,
    "OH": 11_799_448,
    "OK": 3_959_353,
    "OR": 4_237_256,
    "PA": 13_002_700,
    "RI": 1_097_379,
    "SC": 5_118_425,
    "SD": 886_667,
    "TN": 6_910_840,
    "TX": 29_145_505,
    "UT": 3_271_616,
    "VT": 643_077,
    "VA": 8_631_393,
    "WA": 7_614_893,
    "WV": 1_793_716,
    "WI": 5_893_718,
    "WY": 576_851,
    # US Territories (2020 Census)
    "PR": 3_285_874,
    "GU": 153_836,
    "VI": 87_146,
    "AS": 49_710,
    "MP": 47_329,
}

# 2020 US Census city populations (top 100 incorporated places)
# Source: census.gov/programs-surveys/decennial-census/2020-census
CITY_POPULATIONS_2020: dict[str, int] = {
    "NY_NEW_YORK": 8_804_190,
    "CA_LOS_ANGELES": 3_898_747,
    "IL_CHICAGO": 2_746_388,
    "TX_HOUSTON": 2_304_580,
    "AZ_PHOENIX": 1_608_139,
    "PA_PHILADELPHIA": 1_603_797,
    "TX_SAN_ANTONIO": 1_434_625,
    "CA_SAN_DIEGO": 1_386_932,
    "TX_DALLAS": 1_304_379,
    "CA_SAN_JOSE": 1_013_240,
    "TX_AUSTIN": 961_855,
    "FL_JACKSONVILLE": 949_611,
    "TX_FORT_WORTH": 918_915,
    "OH_COLUMBUS": 905_748,
    "IN_INDIANAPOLIS_CITY_BALANCE": 887_642,
    "CA_SAN_FRANCISCO": 873_965,
    "NC_CHARLOTTE": 874_579,
    "TX_EL_PASO": 678_815,
    "WA_SEATTLE": 737_015,
    "CO_DENVER": 715_522,
    "DC_WASHINGTON": 689_545,
    "TN_NASHVILLEDAVIDSON_METROPOLITAN_GOVERNMENT_BALANCE": 689_447,
    "OK_OKLAHOMA_CITY": 681_054,
    "FL_MIAMI": 442_241,
    "NV_LAS_VEGAS": 641_903,
    "OR_PORTLAND": 652_503,
    "TX_ARLINGTON": 394_266,
    "CA_LONG_BEACH": 466_742,
    "VA_VIRGINIA_BEACH": 459_470,
    "GA_ATLANTA": 498_715,
    "CO_COLORADO_SPRINGS": 478_961,
    "NC_RALEIGH": 467_665,
    "FL_TAMPA": 384_959,
    "CA_OAKLAND": 433_031,
    "MN_MINNEAPOLIS": 429_954,
    "OK_TULSA": 413_066,
    "FL_ORLANDO": 307_573,
    "CA_BAKERSFIELD": 403_455,
    "CO_AURORA": 386_261,
    "CA_ANAHEIM": 350_365,
    "CA_SANTA_ANA": 310_227,
    "CA_RIVERSIDE": 314_998,
    "MO_ST_LOUIS": 301_578,
    "TX_CORPUS_CHRISTI": 317_863,
    "PA_PITTSBURGH": 302_971,
    "CA_STOCKTON": 320_804,
    "MN_ST_PAUL": 311_527,
    "OH_CLEVELAND": 372_624,
    "OH_CINCINNATI": 309_317,
    "CA_IRVINE": 307_670,
    "NC_DURHAM": 283_506,
    "FL_ST_PETERSBURG": 258_308,
    "TX_LAREDO": 255_205,
    "NE_OMAHA": 486_051,
    "NE_LINCOLN": 291_082,
    "NC_GREENSBORO": 299_035,
    "NC_WINSTONSALEM": 249_545,
    "TX_PLANO": 285_494,
    "TX_LUBBOCK": 263_648,
    "TX_IRVING": 256_684,
    "TX_GARLAND": 246_018,
    "TX_FRISCO": 200_509,
    "FL_HIALEAH": 223_109,
    "FL_CAPE_CORAL": 194_016,
    "FL_PORT_ST_LUCIE": 217_223,
    "CA_CHULA_VISTA": 275_487,
    "CA_FRESNO": 542_107,
    "CA_SACRAMENTO": 524_943,
    "OH_TOLEDO": 270_871,
    "AZ_TUCSON": 542_629,
    "AZ_MESA": 504_258,
    "AZ_CHANDLER": 275_987,
    "AZ_SCOTTSDALE": 241_361,
    "AZ_GILBERT": 267_918,
    "AZ_GLENDALE": 248_325,
    "NJ_NEWARK": 311_549,
    "NJ_JERSEY_CITY": 292_449,
    "WA_SPOKANE": 228_989,
    "WI_MILWAUKEE": 577_222,
    "WI_MADISON": 269_840,
    "MI_DETROIT": 639_111,
    "NV_HENDERSON": 320_189,
    "NV_NORTH_LAS_VEGAS": 262_527,
    "NV_RENO": 264_165,
    "KS_WICHITA": 397_532,
    "MA_BOSTON": 675_647,
    "VA_NORFOLK": 238_005,
    "VA_CHESAPEAKE": 249_422,
    "VA_RICHMOND": 226_610,
    "MO_KANSAS_CITY": 508_090,
    "IN_FORT_WAYNE": 263_886,
    "MD_BALTIMORE": 585_708,
    "TN_MEMPHIS": 633_104,
    "KY_LOUISVILLEJEFFERSON_COUNTY_METRO_GOVERNMENT_BALANCE": 633_045,
    "KY_LEXINGTONFAYETTE_URBAN_COUNTY": 322_570,
    "ID_BOISE_CITY": 235_684,
    "NM_ALBUQUERQUE": 564_559,
    "LA_NEW_ORLEANS": 383_997,
    "SC_CHARLESTON": 150_227,  # not in registry but relevant
    "AK_ANCHORAGE_MUNICIPALITY": 291_247,
    "HI_HONOLULU": 350_964,  # not in registry
}

# 2026 primary election dates (source: FVAP.gov via our research doc)
PRIMARY_DATES_2026: dict[str, str] = {
    "AR": "2026-03-03",
    "NC": "2026-03-03",
    "TX": "2026-03-03",
    "MS": "2026-03-10",
    "IL": "2026-03-17",
    "IN": "2026-05-05",
    "OH": "2026-05-05",
    "NE": "2026-05-12",
    "WV": "2026-05-12",
    "LA": "2026-05-16",
    "AL": "2026-05-19",
    "GA": "2026-05-19",
    "ID": "2026-05-19",
    "KY": "2026-05-19",
    "OR": "2026-05-19",
    "PA": "2026-05-19",
    "CA": "2026-06-02",
    "IA": "2026-06-02",
    "MT": "2026-06-02",
    "NJ": "2026-06-02",
    "NM": "2026-06-02",
    "SD": "2026-06-02",
    "ME": "2026-06-09",
    "NV": "2026-06-09",
    "ND": "2026-06-09",
    "SC": "2026-06-09",
    "DC": "2026-06-16",
    "OK": "2026-06-16",
    "MD": "2026-06-23",
    "NY": "2026-06-23",
    "UT": "2026-06-23",
    "CO": "2026-06-30",
    "AZ": "2026-07-21",
    "KS": "2026-08-04",
    "MI": "2026-08-04",
    "MO": "2026-08-04",
    "VA": "2026-08-04",
    "WA": "2026-08-04",
    "TN": "2026-08-06",
    "HI": "2026-08-08",
    "CT": "2026-08-11",
    "MN": "2026-08-11",
    "VT": "2026-08-11",
    "WI": "2026-08-11",
    "AK": "2026-08-18",
    "FL": "2026-08-18",
    "WY": "2026-08-18",
    "MA": "2026-09-01",
    "NH": "2026-09-08",
    "RI": "2026-09-08",
    "DE": "2026-09-15",
    # US Territories (delegate elections — dates from FVAP.gov)
    "GU": "2026-08-01",
    "VI": "2026-08-01",
    # PR, AS, MP primary dates TBD / not yet confirmed
}

# Known campaign finance portal URLs for non-implemented states
# Only include URLs that have been verified or are from official sources.
# "needs_investigation" means we haven't verified the current portal yet.
KNOWN_PORTAL_URLS: dict[str, str] = {
    "FEC": "https://www.fec.gov/data/",
    # Implemented states — from config.yaml files
    "CA": "https://www.sos.ca.gov/campaign-lobbying/cal-access-resources/raw-data-campaign-finance-and-lobbying-activity",
    "CO": "https://tracer.sos.colorado.gov/PublicSite/DataDownload.aspx",
    "FL": "https://dos.elections.myflorida.com/campaign-finance/contributions/",
    "GA": "https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx",
    "IN": "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/",
    "MN": "https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/",
    "NC": "https://cf.ncsbe.gov/CFTxnLkup/",
    "OH": "https://www.ohiosos.gov/campaign-finance/search/",
    "PA": "https://www.pa.gov/agencies/dos/resources/voting-and-elections-resources/campaign-finance-data",
    "TX": "https://www.ethics.state.tx.us/search/cf/",
    "WA": "https://www.pdc.wa.gov/political-disclosure-reporting-data/open-data",
    # Non-implemented states — known from PM3 audit or general knowledge
    # Only populated where we have some evidence; blank means needs investigation
    "WI": "https://campaignfinance.wi.gov",
    "IL": "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
    "NY": "https://publicreporting.elections.ny.gov/",
    "NJ": "https://www.elec.state.nj.us/publicinformation/contributions.htm",
}


def _pipeline_status(row: dict) -> str:
    """Derive human-readable pipeline status from registry row."""
    runner = row.get("runner_wired", False)
    if runner:
        return "runner_wired"
    # Check if a pipeline package exists (implemented tier OR has config/code)
    tier = row.get("tier", "")
    if "implemented" in tier:
        return "implemented_not_wired"
    if row.get("jurisdiction_type") == "municipality":
        decision = row.get("municipal_audit_decision", "")
        if decision == "covered_by_parent":
            return "covered_by_parent"
    return "none"


def _audit_method(row: dict) -> str:
    tier = row.get("tier", "")
    if row.get("runner_wired"):
        return "pipeline_development"
    if "implemented" in tier:
        return "config_review"
    evidence = row.get("evidence_summary", "")
    if "Browser-verified" in evidence or "browser-verified" in evidence:
        return "browser_verified"
    if "Stage 3 audit" in evidence or "PM3" in evidence or "HTTP probe" in evidence.lower():
        return "automated_probe_stale_urls"
    if "Inherits parent" in evidence:
        return "parent_inheritance"
    # All PM3-era rows that aren't implemented
    if row.get("evidence_date") == "2026-03-25":
        return "automated_probe_stale_urls"
    return "not_audited"


def _audit_confidence(method: str) -> str:
    """Map audit method to confidence level."""
    return {
        "pipeline_development": "high",
        "config_review": "medium",
        "browser_verified": "high",
        "automated_probe_stale_urls": "low",
        "automated_probe_current_urls": "medium",
        "parent_inheritance": "medium",
        "not_audited": "none",
    }.get(method, "none")


def _get_population(row: dict) -> "int | None":
    """Look up population for a jurisdiction."""
    jcode = row["jurisdiction_code"]
    jtype = row["jurisdiction_type"]
    if jtype == "federal":
        return 331_449_281  # US total 2020 Census
    if jtype == "state":
        return STATE_POPULATIONS_2020.get(jcode)
    if jtype == "municipality":
        return CITY_POPULATIONS_2020.get(jcode)
    return None


def _get_primary_date(row: dict) -> str:
    """Look up 2026 primary date for a jurisdiction."""
    jcode = row["jurisdiction_code"]
    jtype = row["jurisdiction_type"]
    if jtype == "state":
        return PRIMARY_DATES_2026.get(jcode, "")
    if jtype == "municipality":
        parent = row.get("parent_jurisdiction_code", "")
        return PRIMARY_DATES_2026.get(parent, "")
    if jtype == "federal":
        return "2026-11-03"  # general election
    return ""


def _get_portal_url(row: dict) -> str:
    """Look up portal URL for a jurisdiction."""
    jcode = row["jurisdiction_code"]
    jtype = row["jurisdiction_type"]
    if jtype in ("federal", "state"):
        return KNOWN_PORTAL_URLS.get(jcode, "needs_investigation")
    if jtype == "municipality":
        parent = row.get("parent_jurisdiction_code", "")
        decision = row.get("municipal_audit_decision", "")
        if decision == "covered_by_parent":
            return f"(see {parent})"
        # Independent municipalities: read portal URL from registry row
        municipal_url = row.get("municipal_portal_url")
        if municipal_url:
            return municipal_url
        return "needs_investigation"
    return ""


def generate() -> None:
    """Generate the master jurisdiction CSV."""
    with open(REGISTRY_PATH) as f:
        registry = json.load(f)

    rows = registry["rows"]

    # Sort: federal first, then states by population desc, then municipalities by population desc
    def sort_key(r: dict) -> tuple:
        pop = _get_population(r) or 0
        type_order = {"federal": 0, "state": 1, "municipality": 2}
        return (type_order.get(r["jurisdiction_type"], 9), -pop)

    rows.sort(key=sort_key)

    fieldnames = [
        "jurisdiction_code",
        "name",
        "type",
        "parent_state",
        "population_2020",
        "primary_date_2026",
        "portal_url",
        "data_frequency",
        "pipeline_status",
        "tier",
        "covers_sub_jurisdictions",
        "source_count",
        "audit_method",
        "audit_confidence",
        "audit_date",
        "next_action",
        "notes",
    ]

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            method = _audit_method(row)
            writer.writerow(
                {
                    "jurisdiction_code": row["jurisdiction_code"],
                    "name": row["name"],
                    "type": row["jurisdiction_type"],
                    "parent_state": row.get("parent_jurisdiction_code", ""),
                    "population_2020": _get_population(row) or "",
                    "primary_date_2026": _get_primary_date(row),
                    "portal_url": _get_portal_url(row),
                    "data_frequency": row.get("best_update_frequency", ""),
                    "pipeline_status": _pipeline_status(row),
                    "tier": row["tier"],
                    "covers_sub_jurisdictions": row.get("covers_sub_jurisdictions", ""),
                    "source_count": row.get("source_count", ""),
                    "audit_method": method,
                    "audit_confidence": _audit_confidence(method),
                    "audit_date": row.get("evidence_date", ""),
                    "next_action": row.get("next_action", ""),
                    "notes": row.get("operational_reason", ""),
                }
            )

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
