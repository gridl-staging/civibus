<!-- [scrai:start] -->
## types

| File | Summary |
| --- | --- |
| __init__.py | Campaign-finance domain type exports. |
| dark_money_models.py | IRS 527 dark money models — Form 8871 (political orgs) and Form 8872 (periodic reports).

Four record types from the IRS 527 pipe-delimited bulk file:
  - Type 1 → PoliticalOrganization527 (Form 8871 registration)
  - Type 2 → Filing8872 (Form 8872 periodic disclosure)
  - Type A → Contribution527 (Schedule A contribution)
  - Type B → Expenditure527 (Schedule B expenditure)

Field names are normalized from IRS layout doc (PolOrgsFileLayout.doc) to snake_case.
The IRS source uses "RECIEPIENT" (typo); we normalize to "recipient" in the model. |
| models.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/types/models.py. |
<!-- [scrai:end] -->
