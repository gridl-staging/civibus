from domains.campaign_finance.jurisdictions.states.WA.scraper.relational_utils import (
    WASourceRecordKeyLedger,
)


def test_source_record_key_ledger_only_blocks_unpersisted_rejections() -> None:
    ledger = WASourceRecordKeyLedger()
    ledger.rejected_attempts.update({"rejected": 2, "eventually-persisted": 1})
    ledger.persisted.add("eventually-persisted")

    assert ledger.blocks_relational_link("rejected") is True
    assert ledger.blocks_relational_link("eventually-persisted") is False
    assert ledger.rejected_attempts_for_persisted_keys() == 1
