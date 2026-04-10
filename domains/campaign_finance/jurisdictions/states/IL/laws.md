# Illinois Campaign Finance Law Notes

Evidence checked on 2026-03-27.

## Primary Sources

- 10 ILCS 5/9-3: political committee statement of organization
- 10 ILCS 5/9-10: disclosure timing and quarterly/A-1/B-1 reporting
- 10 ILCS 5/9-11: quarterly report contents and itemization threshold
- 10 ILCS 5/9-8.5: contribution limits
- 26 Ill. Adm. Code part 100, Appendix A, Table A: current per-cycle contribution-limit table

## Summary

- Political committees file a statement of organization within 10 business days of creation, or within 2 business days if created within 30 days before an election.
- Quarterly reports cover calendar quarters and are due by the 15th day after quarter end.
- A-1 reports cover contributions of `$1,000` or more and are due within 5 business days, or within 2 business days during the 30-day pre-election window described in 10 ILCS 5/9-10(c).
- B-1 reports cover independent expenditures of `$1,000` or more and are due within 5 business days, or within 2 business days during the 60-day pre-election window described in 10 ILCS 5/9-10(e).
- Quarterly itemization begins once a contributor's aggregate amount or value exceeds `$150` in the reporting period. Occupation and employer are additionally required for individuals contributing more than `$500` when known.

## Contribution Limits

Current Appendix A values observed on 2026-03-27:

- Candidate political committee:
  - `$6,900` from an individual
  - `$13,700` from a corporation, labor organization, or association
  - `$68,500` from a candidate political committee or political action committee
  - Political party committees are generally unlimited, but primary-cycle office-specific caps apply.
- Political action committee:
  - `$13,700` from an individual
  - `$27,400` from a corporation, labor organization, political party committee, or association
  - `$68,500` from another PAC or candidate committee

## Practical Loader Notes

- The live bulk files include both electronic and paper-entered records.
- The current loader uses the transaction files only, so it records filing linkage from `FiledDocID` but does not yet enrich filings from `FiledDocs.txt`.
