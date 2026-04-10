# Ohio (OH) campaign-finance jurisdiction package

## Purpose
This README is the operator-facing entry point for the Ohio package.

- Structured machine-readable metadata lives in `config.yaml`.
- Portal evidence, blocker history, file-pattern inventory, and open hypotheses live in `data_semantics.md`.

## Current downloader contract
The checked-in Ohio downloader remains HTTP-first and currently does not model the live portal contract accurately:

- `download_oh_csv()` still assumes page 73 can be fetched directly via `httpx` and that the listing contains static `*.CSV` links.
- Live March 24, 2026 evidence shows the protected portal behaves differently:
  - raw HTTP and headless automation can return `403`/challenge pages,
  - headed real Chrome can reach the search app and, in at least one successful session, the FTP page,
- the FTP listing is real, but download actions resolve through APEX page 72 `P72_GETID=...` routes rather than simple static CSV URLs.
- `run_oh_refresh(..., download=True)` still propagates the checked-in downloader failure path to the CLI entrypoint, and `main()` still emits the existing CLI error envelope.

Ohio is currently documented-and-deferred. Do not treat Ohio download mode as verified live ingestion, and do not keep Ohio on the critical launch path while easier weekly/daily states remain available.

## Operator workflow
1. Choose ingestion mode:
   - Local path mode (`--path`) for known local CSVs.
   - Download mode (`--download`) only when upstream portal access is verified in `data_semantics.md`.
2. Before claiming downloader success, read `data_semantics.md` for the latest verified portal behavior, live download-path evidence, and unresolved external risks.
3. For any future re-investigation, use `scraper/probe.py` to capture page HTML, screenshots, classification, cookies, and discovered page-72 download actions from a real browser session before changing downloader logic.
4. Keep structured values in `config.yaml` limited to machine-consumed metadata (URLs, cadence, coverage, field mappings, known issues, verification dates). If source file patterns, headers, or blocker status change, update `data_semantics.md` in the same change.
5. After any Ohio doc or config edit, run `make validate-configs`; when source metadata or downloader expectations change, rerun the focused OH scraper tests before claiming success.

## Links
- Structured config: `domains/campaign_finance/jurisdictions/states/OH/config.yaml`
- Evidence log: `domains/campaign_finance/jurisdictions/states/OH/data_semantics.md`
- Probe harness: `domains/campaign_finance/jurisdictions/states/OH/scraper/probe.py`
