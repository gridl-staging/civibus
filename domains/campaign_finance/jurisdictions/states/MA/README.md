# Massachusetts (MA) campaign-finance jurisdiction package

## Jurisdiction overview
Massachusetts is a state-level jurisdiction (`fips: 25`) using the OCPF (Office of Campaign and Political Finance) nightly bulk ZIP downloads from Azure Blob Storage. Contributions and expenditures are combined in a single tab-delimited `report-items.txt` file, differentiated by `Record_Type_ID`.

## Data sources
- **Report Items**: per-year ZIP files at `ocpf2.blob.core.windows.net/downloads/data2/ocpf-{year}-reports.zip`
- **Filers**: `ocpf-filers.zip` (all registered committees/candidates)
- **REST API**: `api.ocpf.us` (no auth, CORS *)

## Pipeline
Download per-year ZIPs (2022-2026) → Extract report-items.txt → Parse (tab-delimited, filtered by Record_Type_ID) → Extract → Load. Record types 200-series = contributions, 300-series = expenditures.
