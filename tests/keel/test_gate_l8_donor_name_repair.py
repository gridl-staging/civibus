from pathlib import Path
from typing import Any, cast

import yaml


REGRESSION_PAIRS_PATH = Path(__file__).resolve().parents[1] / "er_regression_pairs.yaml"
EXPECTED_FALSE_MERGE_EVIDENCE = {
    "fec_person_cluster_030872d9_dennis_vs_stephanie_robinson": {
        "left_entity": {
            "canonical_name": "Dennis Robinson",
            "primary_address": "Winters, CA 95694-9659",
            "employer": "NOT EMPLOYED",
            "occupation": "NOT EMPLOYED",
            "jurisdiction": "state/ca",
            "source_record_key": "4051020251191662253",
        },
        "right_entity": {
            "canonical_name": "Stephanie Robinson",
            "primary_address": "Beverly Hills, CA 90212-4516",
            "employer": "NOT EMPLOYED",
            "occupation": "NOT EMPLOYED",
            "jurisdiction": "state/ca",
            "source_record_key": "4051020251192288091",
        },
        "filing_urls": {"https://www.fec.gov/data/filings/1891326/"},
    },
    "fec_person_cluster_81136b39_linda_vs_ryan_garcia": {
        "left_entity": {
            "canonical_name": "Linda Garcia",
            "primary_address": "Arlington, TX 76001-5541",
            "employer": "NOT EMPLOYED",
            "occupation": "NOT EMPLOYED",
            "jurisdiction": "state/tx",
            "source_record_key": "4100120242066892113",
        },
        "right_entity": {
            "canonical_name": "Ryan Garcia",
            "primary_address": "Rosenberg, TX 77471-9303",
            "employer": "ROSENBERG PLUMBING SERVICE INC.",
            "occupation": "ACCOUNTANT",
            "jurisdiction": "state/tx",
            "source_record_key": "4051020251193212520",
        },
        "filing_urls": {
            "https://www.fec.gov/data/filings/1817925/",
            "https://www.fec.gov/data/filings/1891326/",
        },
    },
}


def _must_not_match_cases_by_id() -> dict[str, dict[str, Any]]:
    fixture = cast(
        dict[str, Any],
        yaml.safe_load(REGRESSION_PAIRS_PATH.read_text(encoding="utf-8")),
    )
    return {case["case_id"]: case for case in fixture["must_not_match"]}


def test_donor_name_repair_false_merge_cases_have_exact_source_evidence() -> None:
    cases_by_id = _must_not_match_cases_by_id()

    for case_id, expected in EXPECTED_FALSE_MERGE_EVIDENCE.items():
        case = cases_by_id[case_id]
        assert case["left_entity"] == expected["left_entity"]
        assert case["right_entity"] == expected["right_entity"]
        assert set(case["source_notes"]) == expected["filing_urls"]
