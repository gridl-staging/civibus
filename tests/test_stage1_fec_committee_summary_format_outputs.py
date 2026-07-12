from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMMITTEE_SUMMARY_COLUMNS = (
    "Link_Image",
    "CMTE_ID",
    "CMTE_NM",
    "CMTE_TP",
    "CMTE_DSGN",
    "CMTE_FILING_FREQ",
    "CMTE_ST1",
    "CMTE_ST2",
    "CMTE_CITY",
    "CMTE_ST",
    "CMTE_ZIP",
    "TRES_NM",
    "CAND_ID",
    "FEC_ELECTION_YR",
    "INDV_CONTB",
    "PTY_CMTE_CONTB",
    "OTH_CMTE_CONTB",
    "TTL_CONTB",
    "TRANF_FROM_OTHER_AUTH_CMTE",
    "OFFSETS_TO_OP_EXP",
    "OTHER_RECEIPTS",
    "TTL_RECEIPTS",
    "TRANF_TO_OTHER_AUTH_CMTE",
    "OTH_LOAN_REPYMTS",
    "INDV_REF",
    "POL_PTY_CMTE_REF",
    "TTL_CONTB_REF",
    "OTHER_DISB",
    "TTL_DISB",
    "NET_CONTB",
    "NET_OP_EXP",
    "COH_BOP",
    "CVG_START_DT",
    "COH_COP",
    "CVG_END_DT",
    "DEBTS_OWED_BY_CMTE",
    "DEBTS_OWED_TO_CMTE",
    "INDV_ITEM_CONTB",
    "INDV_UNITEM_CONTB",
    "OTH_LOANS",
    "TRANF_FROM_NONFED_ACCT",
    "TRANF_FROM_NONFED_LEVIN",
    "TTL_NONFED_TRANF",
    "LOAN_REPYMTS_RECEIVED",
    "OFFSETS_TO_FNDRSG",
    "OFFSETS_TO_LEGAL_ACCTG",
    "FED_CAND_CONTB_REF",
    "TTL_FED_RECEIPTS",
    "SHARED_FED_OP_EXP",
    "SHARED_NONFED_OP_EXP",
    "OTHER_FED_OP_EXP",
    "TTL_OP_EXP",
    "FED_CAND_CMTE_CONTB",
    "INDT_EXP",
    "COORD_EXP_BY_PTY_CMTE",
    "LOANS_MADE",
    "SHARED_FED_ACTVY_FED_SHR",
    "SHARED_FED_ACTVY_NONFED",
    "NON_ALLOC_FED_ELECT_ACTVY",
    "TTL_FED_ELECT_ACTVY",
    "TTL_FED_DISB",
    "CAND_CNTB",
    "CAND_LOAN",
    "TTL_LOANS",
    "OP_EXP",
    "CAND_LOAN_REPYMNT",
    "TTL_LOAN_REPYMTS",
    "OTH_CMTE_REF",
    "TTL_OFFSETS_TO_OP_EXP",
    "EXEMPT_LEGAL_ACCTG_DISB",
    "FNDRSG_DISB",
    "ITEM_REF_REB_RET",
    "SUBTTL_REF_REB_RET",
    "UNITEM_REF_REB_RET",
    "ITEM_OTHER_REF_REB_RET",
    "UNITEM_OTHER_REF_REB_RET",
    "SUBTTL_OTHER_REF_REB_RET",
    "ITEM_OTHER_INCOME",
    "UNITEM_OTHER_INCOME",
    "EXP_PRIOR_YRS_SUBJECT_LIM",
    "EXP_SUBJECT_LIMITS",
    "FED_FUNDS",
    "ITEM_CONVN_EXP_DISB",
    "ITEM_OTHER_DISB",
    "SUBTTL_CONVN_EXP_DISB",
    "TTL_EXP_SUBJECT_LIMITS",
    "UNITEM_CONVN_EXP_DISB",
    "UNITEM_OTHER_DISB",
    "TTL_COMMUNICATION_COST",
    "COH_BOY",
    "COH_COY",
    "ORG_TP",
)


def test_committee_summary_fixture_parses_with_dict_reader_contract() -> None:
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "bulk" / "committee_summary_2024.csv"

    with fixture_path.open(encoding="utf-8", newline="") as fixture_file:
        reader = csv.DictReader(fixture_file)
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == COMMITTEE_SUMMARY_COLUMNS
    assert len(reader.fieldnames or ()) == 92
    assert len(rows) == 4
    assert all(len(row) == 92 for row in rows)
    assert {row["FEC_ELECTION_YR"] for row in rows} == {"2024"}
    assert rows[0]["Link_Image"] == "https://www.fec.gov/data/committee/C00879676/?cycle=2024"
    assert rows[0]["CAND_ID"] == ""
    assert rows[1]["CMTE_ID"] == rows[2]["CMTE_ID"] == "C00778423"
    assert rows[1]["CAND_ID"] == "S4TX00714"
    assert rows[2]["CAND_ID"] == "H4TX32048"
    assert rows[3]["ORG_TP"] == "T"
    assert rows[3]["FED_CAND_CONTB_REF"] == "-5"

    for row in rows:
        for value in row.values():
            assert value == value.encode("utf-8").decode("utf-8")
