# 2026-07-29 Accessibility Baseline

PURPOSE: raw Stage 1 fixture-mode axe smoke evidence.

Stage 1 is measurement only. Do not treat this receipt as a threshold, ratchet, or accessibility remediation baseline.

## Stage 1 fixture axe smoke evidence

ROUTES_SCANNED: 9
ROUTES_SCANNED_NAMES: Home, Search, Candidates, Committees, Congress, Developers, Methodology, Person detail, Committee detail
KEYBOARD_PRIOR_ART: finance-visuals.spec.ts:491 and production_finance_visuals.spec.ts:177 already cover programmatic focus/Enter flows; this Stage 1 lane adds axe measurement only.
AXE_ROUTE_FINDINGS:
- Home (/): 2 violations [aria-progressbar-name, region]
- Search (/search?q=civ&entity_type=org): 2 violations [aria-progressbar-name, region]
- Candidates (/candidates): 2 violations [aria-progressbar-name, region]
- Committees (/committees): 2 violations [aria-progressbar-name, region]
- Congress (/congress): 2 violations [aria-progressbar-name, region]
- Developers (/developers): 3 violations [aria-progressbar-name, region, scrollable-region-focusable]
- Methodology (/methodology): 2 violations [aria-progressbar-name, region]
- Person detail (/person/11111111-1111-4111-8111-111111111111): 3 violations [aria-progressbar-name, heading-order, region]
- Committee detail (/committee/citizens-for-civibus): 2 violations [aria-progressbar-name, region]

<!-- stage2-accessibility-baseline:start -->
## Stage 2 committed baseline and triage

TOTAL_VIOLATIONS: 0
TOTAL_BASELINE_ENTRIES: 0
COUNTING_NOTE: TOTAL_VIOLATIONS counts axe rule results by route; TOTAL_BASELINE_ENTRIES counts the affected elements serialized as ratchet keys.
VIOLATIONS_BY_RULE:
VIOLATIONS_BY_IMPACT:
- critical: 0
- serious: 0
- moderate: 0
- minor: 0
BASELINE_ENTRIES_BY_IMPACT:
- critical: 0
- serious: 0
- moderate: 0
- minor: 0
TRIAGE: none = accepted_limitation
TRIAGE_REASON: The fresh fixture corpus has no axe violations to classify.

CHARTS_SUCCESSOR_WORK: The read-only SVG surfaces in Chart, ChartFrame, CashOnHandTrendChart, ComparisonBar, GeographyShareChart, HorizontalBarChart, MonthlyContributionsChart, OutsideSpendingChart, and ReceiptCompositionChart expose visible summaries and exact rows, but axe cannot prove screen-reader data access for SVG charts. Successor work must add automated screen-reader data-access contracts for these chart surfaces; Stage 2 adds no chart assertions or remediation markup.
<!-- stage2-accessibility-baseline:end -->

## Stage 3 axe ratchet guard

RATCHET_OWNER: `web/tests/smoke/accessibility.spec.ts`
BASELINE_OWNER: `web/tests/smoke/a11y-baseline.json`
ROUTE_CORPUS_OWNER: `web/tests/smoke/a11y-helpers.ts`, derived from `APP_SHELL.shellNavigation`

RED_TEST_COMMAND: `cd web && npm run test:smoke -- accessibility.spec.ts --reporter=line`
RED_TEST_RESULT: failed as expected after adding a temporary unnamed `<button type="button"></button>` to `web/src/routes/+layout.svelte`.
RED_TEST_OUTPUT:
```text
1 failed, 4 passed
Error: New accessibility violations found:
- /::button-name::target:["button"]
- /candidates::button-name::target:["button[type=\"button\"]"]
- /committee/citizens-for-civibus::button-name::target:["button"]
- /committees::button-name::target:["button[type=\"button\"]"]
- /congress::button-name::target:[".shell__header > button"]
- /developers::button-name::target:["button"]
- /methodology::button-name::target:["button"]
- /person/11111111-1111-4111-8111-111111111111::button-name::target:[".shell__header > button"]
- /search?q=civ&entity_type=org::button-name::target:["button[type=\"button\"]"]
```

GREEN_TEST_COMMAND_AFTER_REMOVING_SYNTHETIC_MUTATION: `cd web && npm run test:smoke -- accessibility.spec.ts --reporter=line`
GREEN_TEST_RESULT: `5 passed` for the ratchet-only green run after removing the temporary unnamed button; later Stage 3 keyboard coverage expanded the same spec to `6 passed`.

RATCHET_LIMITATION: This guard prevents newly observed axe violation keys relative to the committed baseline. It is not a WCAG conformance claim and does not prove assistive-technology behavior.

## Stage 3 keyboard reachability

KEYBOARD_TEST_OWNER: `web/tests/smoke/accessibility.spec.ts`
SHELL_HOOKS_ADDED: `shell-header`, `shell-primary-nav`, `shell-main`, `shell-footer`, `shell-footer-nav`, `shell-nav-link-*`, and `shell-footer-link-*` in `web/src/routes/+layout.svelte`.
KEYBOARD_TRAVERSAL_RESULT: Starting from a cold loaded Home route, real `Tab` key presses reached the shell primary navigation links in order: Home, Search, Candidates, Committees, Congress, Developers, Methodology.
SKIP_LINK_DISPOSITION: No `shell-skip-link` exists in `web/src/routes/+layout.svelte`; the smoke test asserts `getByTestId("shell-skip-link")` has count `0` as a triaged finding instead of adding presentation markup without an app-shell screen spec.
FOCUS_VISIBILITY_PROBE: The Home primary nav link is checked with `toHaveCSS("outline-style", /^(auto|solid)$/)` while focused. This is a representative CSS check, not full visible-focus coverage.
KEYBOARD_LIMITATION: This test does not prove full keyboard accessibility, WCAG conformance, or assistive-technology behavior.

## Remediation disposition

REMEDIATION_COMPLETE: aria-progressbar-name | routes=Home, Search, Candidates, Committees, Congress, Developers, Methodology, Person detail, Committee detail | owner=web/src/lib/navigation/NavigationProgress.svelte | evidence=`cd web && npm run test:smoke -- accessibility.spec.ts --reporter=line` reports zero serious `aria-progressbar-name` violations while preserving the route corpus at `ROUTES_SCANNED: 9`.
REMEDIATION_COMPLETE: scrollable-region-focusable | routes=Developers | owner=web/src/routes/developers/+page.svelte | evidence=all eight emitted curl and sample-response `<pre>` blocks have `tabindex="0"`, the render contract asserts all eight, and the fixture axe scan reports zero `scrollable-region-focusable` violations.
SUCCESSOR_REMEDIATION: heading-order | routes=Person detail | owner=web/src/routes/person/[id]/+page.svelte | exit=`cd web && npm run test:smoke -- accessibility.spec.ts --reporter=line` reports zero moderate `heading-order` violations for the Person detail route without removing the person money-at-a-glance content assertion.
INCIDENTAL_CLEARANCE: region | routes=Home, Search, Candidates, Committees, Congress, Developers, Methodology, Person detail, Committee detail | owner=web/src/lib/navigation/NavigationProgress.svelte | evidence=making the visual route-transition strip decorative removed it from the accessibility tree, so the regenerated baseline contains zero `region` entries without a separate moderate-finding remediation.

## Historical proposed ROADMAP row

HISTORICAL_NOTE: The row below records the pre-remediation Stage 1 proposal. Its "Current accessibility smoke baseline" counts are the original 24-entry measurement, not the regenerated baseline recorded at lines 23-44.

| P1 | L9 accessibility remediation and chart data-access assertions | Current accessibility smoke baseline is locked with ten serious and ten moderate axe rule results, covering 24 affected-element ratchet entries, in `docs/live-state/2026_07_29_accessibility_baseline.md`; do not treat this as WCAG conformance. Remediate the existing axe findings through the named owners only, then add separate automated chart data-access assertions for SVG chart surfaces because axe does not prove screen-reader access to chart data. | `cd web && npm run test:smoke -- accessibility.spec.ts --reporter=line` reports zero serious violations across the nine-route corpus, and a separate automated chart data-access assertion proves screen-reader-reachable chart data for the chart surfaces named in the accessibility receipt. |

## Non-Claims

NON_CLAIM: axe_is_not_wcag_conformance
The fixture-mode axe scan is an automated defect detector and regression guard, not a claim that Civibus conforms to WCAG.

NON_CLAIM: assistive_technology_testing_not_performed
This lane did not run screen readers or other assistive-technology workflows, so it cannot claim real user-agent behavior beyond the automated browser checks recorded here.

NON_CLAIM: axe_does_not_resolve_svg_chart_data_access
The axe result does not prove whether SVG chart data is reachable to screen-reader users; successor work needs a separate automated assertion for that chart data-access contract.

## ACCESSIBILITY BASELINE VERDICT: BASELINE_LOCKED
