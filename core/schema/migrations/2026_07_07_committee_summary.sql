-- Add cf.committee_summary for official FEC per-cycle committee totals.
-- Canonical base-schema copy: domains/campaign_finance/schema/tables.sql

CREATE TABLE IF NOT EXISTS cf.committee_summary (
    id                                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    committee_id                            UUID NOT NULL REFERENCES cf.committee(id),
    cycle                                   INTEGER NOT NULL,
    link_image                              TEXT,
    committee_name                          TEXT,
    committee_type                          TEXT,
    committee_designation                   TEXT,
    committee_filing_frequency              TEXT,
    committee_street_1                      TEXT,
    committee_street_2                      TEXT,
    committee_city                          TEXT,
    committee_state                         TEXT,
    committee_zip                           TEXT,
    treasurer_name                          TEXT,
    individual_contributions                NUMERIC(14,2),
    party_committee_contributions           NUMERIC(14,2),
    other_committee_contributions           NUMERIC(14,2),
    total_contributions                     NUMERIC(14,2),
    transfers_from_other_authorized_committees NUMERIC(14,2),
    offsets_to_operating_expenditures       NUMERIC(14,2),
    other_receipts                          NUMERIC(14,2),
    total_receipts                          NUMERIC(14,2),
    transfers_to_other_authorized_committees NUMERIC(14,2),
    other_loan_repayments                   NUMERIC(14,2),
    individual_refunds                      NUMERIC(14,2),
    political_party_committee_refunds       NUMERIC(14,2),
    total_contribution_refunds              NUMERIC(14,2),
    other_disbursements                     NUMERIC(14,2),
    total_disbursements                     NUMERIC(14,2),
    net_contributions                       NUMERIC(14,2),
    net_operating_expenditures              NUMERIC(14,2),
    cash_on_hand_beginning_of_period        NUMERIC(14,2),
    coverage_start_date                     DATE,
    cash_on_hand                            NUMERIC(14,2),
    coverage_end_date                       DATE,
    debts_owed_by_committee                 NUMERIC(14,2),
    debts_owed_to_committee                 NUMERIC(14,2),
    individual_itemized_contributions       NUMERIC(14,2),
    individual_unitemized_contributions     NUMERIC(14,2),
    other_loans                             NUMERIC(14,2),
    transfers_from_nonfederal_account       NUMERIC(14,2),
    transfers_from_nonfederal_levin         NUMERIC(14,2),
    total_nonfederal_transfers              NUMERIC(14,2),
    loan_repayments_received                NUMERIC(14,2),
    offsets_to_fundraising                  NUMERIC(14,2),
    offsets_to_legal_accounting             NUMERIC(14,2),
    federal_candidate_contribution_refunds  NUMERIC(14,2),
    total_federal_receipts                  NUMERIC(14,2),
    shared_federal_operating_expenditures   NUMERIC(14,2),
    shared_nonfederal_operating_expenditures NUMERIC(14,2),
    other_federal_operating_expenditures    NUMERIC(14,2),
    total_operating_expenditures            NUMERIC(14,2),
    federal_candidate_committee_contributions NUMERIC(14,2),
    independent_expenditures                NUMERIC(14,2),
    coordinated_expenditures_by_party_committee NUMERIC(14,2),
    loans_made                              NUMERIC(14,2),
    shared_federal_activity_federal_share   NUMERIC(14,2),
    shared_federal_activity_nonfederal      NUMERIC(14,2),
    nonallocated_federal_election_activity  NUMERIC(14,2),
    total_federal_election_activity         NUMERIC(14,2),
    total_federal_disbursements             NUMERIC(14,2),
    candidate_contributions                 NUMERIC(14,2),
    candidate_loans                         NUMERIC(14,2),
    total_loans                             NUMERIC(14,2),
    operating_expenditures                  NUMERIC(14,2),
    candidate_loan_repayments               NUMERIC(14,2),
    total_loan_repayments                   NUMERIC(14,2),
    other_committee_refunds                 NUMERIC(14,2),
    total_offsets_to_operating_expenditures NUMERIC(14,2),
    exempt_legal_accounting_disbursements   NUMERIC(14,2),
    fundraising_disbursements               NUMERIC(14,2),
    itemized_refunds_rebates_returns        NUMERIC(14,2),
    subtotal_refunds_rebates_returns        NUMERIC(14,2),
    unitemized_refunds_rebates_returns      NUMERIC(14,2),
    itemized_other_refunds_rebates_returns  NUMERIC(14,2),
    unitemized_other_refunds_rebates_returns NUMERIC(14,2),
    subtotal_other_refunds_rebates_returns  NUMERIC(14,2),
    itemized_other_income                   NUMERIC(14,2),
    unitemized_other_income                 NUMERIC(14,2),
    expenditures_prior_years_subject_to_limits NUMERIC(14,2),
    expenditures_subject_to_limits          NUMERIC(14,2),
    federal_funds                           NUMERIC(14,2),
    itemized_convention_expenditures_disbursements NUMERIC(14,2),
    itemized_other_disbursements            NUMERIC(14,2),
    subtotal_convention_expenditures_disbursements NUMERIC(14,2),
    total_expenditures_subject_to_limits    NUMERIC(14,2),
    unitemized_convention_expenditures_disbursements NUMERIC(14,2),
    unitemized_other_disbursements          NUMERIC(14,2),
    total_communication_cost                NUMERIC(14,2),
    cash_on_hand_beginning_of_year          NUMERIC(14,2),
    cash_on_hand_close_of_year              NUMERIC(14,2),
    source_record_id                        UUID REFERENCES core.source_record(id),
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_committee_summary_coverage_order
        CHECK (coverage_start_date IS NULL OR coverage_end_date IS NULL OR coverage_start_date <= coverage_end_date)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_committee_summary_committee_cycle
    ON cf.committee_summary (committee_id, cycle);
CREATE INDEX IF NOT EXISTS idx_committee_summary_committee_id
    ON cf.committee_summary (committee_id);
CREATE INDEX IF NOT EXISTS idx_committee_summary_cycle
    ON cf.committee_summary (cycle);
CREATE INDEX IF NOT EXISTS idx_committee_summary_source_record_id
    ON cf.committee_summary (source_record_id);

DROP TRIGGER IF EXISTS trg_committee_summary_updated_at ON cf.committee_summary;
CREATE TRIGGER trg_committee_summary_updated_at
    BEFORE UPDATE ON cf.committee_summary
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();
