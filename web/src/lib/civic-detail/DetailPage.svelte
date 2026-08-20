<script lang="ts">
  import { navigating } from "$app/stores";
  import type { MapLayerVisibility, MapPageLevel } from "$lib/config/app";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import RegionMap, { type RegionMapGeometryByLevel } from "$lib/region-map/RegionMap.svelte";
  import {
    buildCandidacyDetailPresentation,
    buildContestDetailPresentation,
    buildOfficeDetailPresentation,
    buildOfficeholdingDetailPresentation,
    type CandidacyDetailPresentation,
    type ContestDetailPresentation,
    type OfficeDetailPresentation,
    type OfficeholdingDetailPresentation
  } from "$lib/civic-detail/presentation";
  import {
    CIVIC_ROUTE_PREFIXES,
    type CandidacyDetailResponse,
    type ContestCandidateMoneyResponse,
    type ContestDetailResponse,
    type OfficeDetailResponse,
    type OfficeholdingDetailResponse
  } from "$lib/civic-detail/contract";

  function isCivicNavigation(nav: { to?: { url?: URL } | null } | null): boolean {
    const pathname = nav?.to?.url?.pathname;
    if (!pathname) return false;
    return CIVIC_ROUTE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  }

  export let entityType: "office" | "contest" | "candidacy" | "officeholding";
  export let data:
    | OfficeDetailResponse
    | ContestDetailResponse
    | CandidacyDetailResponse
    | OfficeholdingDetailResponse;
  // One batched money response for the whole race, or null when the scoreboard
  // could not be loaded. Never a per-candidate map: the old shape let a single
  // failed fetch masquerade as one candidate simply having no data.
  export let contestCandidateMoney: ContestCandidateMoneyResponse | null = null;
  export let contestSelectedCycle: number | null = null;
  export let contestMap:
    | {
        pageLevel: MapPageLevel;
        layerVisibility: MapLayerVisibility;
        geometryByLevel: RegionMapGeometryByLevel;
        stateCode: string | null;
      }
    | null = null;

  let officeViewModel: OfficeDetailPresentation | null = null;
  let contestViewModel: ContestDetailPresentation | null = null;
  let candidacyViewModel: CandidacyDetailPresentation | null = null;
  let officeholdingViewModel: OfficeholdingDetailPresentation | null = null;

  $: {
    officeViewModel = null;
    contestViewModel = null;
    candidacyViewModel = null;
    officeholdingViewModel = null;

    if (entityType === "office") {
      officeViewModel = buildOfficeDetailPresentation(data as OfficeDetailResponse);
    } else if (entityType === "contest") {
      contestViewModel = buildContestDetailPresentation(data as ContestDetailResponse, {
        candidateMoney: contestCandidateMoney,
        selectedCycle: contestSelectedCycle
      });
    } else if (entityType === "candidacy") {
      candidacyViewModel = buildCandidacyDetailPresentation(data as CandidacyDetailResponse);
    } else if (entityType === "officeholding") {
      officeholdingViewModel = buildOfficeholdingDetailPresentation(data as OfficeholdingDetailResponse);
    }
  }
</script>

{#snippet caveatBanner(warningText: string)}
  <section
    class="detail__panel caveat-banner"
    role="note"
    aria-label="Data coverage warning"
  >
    <h3>Data coverage warning</h3>
    <p>{warningText}</p>
  </section>
{/snippet}

<section class="card detail" aria-label={`${entityType} detail`}>
  {#if isCivicNavigation($navigating)}
    <SkeletonPanel label={`${entityType} detail loading`} lines={2} />
  {:else if entityType === "office" && officeViewModel}
    <header class="detail__header">
      <h2>{officeViewModel.title}</h2>
      <p class="detail__type">office</p>
    </header>

    {#each officeViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Office facts</h3>
          <dl class="detail__rows">
            {#each officeViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={officeViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        <section class="detail__panel">
          <h3>Key metrics</h3>
          <dl class="detail__rows">
            {#each officeViewModel.keyMetricRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "records"}
        {#if officeViewModel.currentHolderCard || officeViewModel.currentHolderEmptyMessage}
          <section class="detail__panel">
            <h3>Current holder</h3>
            {#if officeViewModel.currentHolderCard === null}
              <p>{officeViewModel.currentHolderEmptyMessage}</p>
            {:else}
              <dl class="detail__rows">
                <div class="detail__row">
                  <dt>Person</dt>
                  <dd>
                    {#if officeViewModel.currentHolderCard.personHref}
                      <a href={officeViewModel.currentHolderCard.personHref}>
                        {officeViewModel.currentHolderCard.personName}
                      </a>
                    {:else}
                      {officeViewModel.currentHolderCard.personName}
                    {/if}
                  </dd>
                </div>
                <div class="detail__row">
                  <dt>Status</dt>
                  <dd>{officeViewModel.currentHolderCard.holderStatus}</dd>
                </div>
                <div class="detail__row">
                  <dt>Term start</dt>
                  <dd>{officeViewModel.currentHolderCard.validFrom}</dd>
                </div>
                <div class="detail__row">
                  <dt>Term end</dt>
                  <dd>{officeViewModel.currentHolderCard.validThrough}</dd>
                </div>
                <div class="detail__row">
                  <dt>Officeholding record</dt>
                  <dd>
                    <a href={officeViewModel.currentHolderCard.officeholdingHref}>
                      View officeholding detail
                    </a>
                  </dd>
                </div>
              </dl>
              {#if officeViewModel.currentHolderCard.termEndEmphasis}
                <p>{officeViewModel.currentHolderCard.termEndEmphasis}</p>
              {/if}
            {/if}
          </section>
        {/if}

        <section class="detail__panel">
          <h3>Current officeholders</h3>
          {#if officeViewModel.officeholderRows.length === 0}
            <p>{officeViewModel.officeholderEmptyMessage}</p>
          {:else}
            <div class="detail__table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Officeholding record</th>
                    <th>Holder status</th>
                  </tr>
                </thead>
                <tbody>
                  {#each officeViewModel.officeholderRows as row (row.id)}
                    <tr>
                      <td>
                        {#if row.personHref}
                          <a href={row.personHref}>{row.personName}</a>
                        {:else}
                          {row.personName}
                        {/if}
                      </td>
                      <td>
                        <a
                          href={row.officeholdingHref}
                          aria-label={row.linkAriaLabel}
                        >
                          View officeholding detail
                        </a>
                      </td>
                      <td>{row.holderStatus}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        <section class="detail__panel">
          <h3>Officeholding timeline</h3>
          {#if officeViewModel.timelineRows.length === 0}
            <p>{officeViewModel.timelineEmptyMessage}</p>
          {:else}
            <div class="detail__table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Officeholding record</th>
                    <th>Status</th>
                    <th>Term start</th>
                    <th>Term end</th>
                  </tr>
                </thead>
                <tbody>
                  {#each officeViewModel.timelineRows as row (row.officeholdingId)}
                    <tr>
                      <td>
                        {#if row.personHref}
                          <a href={row.personHref}>{row.personName}</a>
                        {:else}
                          {row.personName}
                        {/if}
                      </td>
                      <td><a href={row.officeholdingHref}>View officeholding detail</a></td>
                      <td>{row.holderStatus}</td>
                      <td>{row.validFrom}</td>
                      <td>{row.validThrough}</td>
                    </tr>
                    {#if row.termEndEmphasis}
                      <tr>
                        <td colspan={5}>{row.termEndEmphasis}</td>
                      </tr>
                    {/if}
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        <section class="detail__panel">
          <h3>Elections for this office</h3>
          {#if officeViewModel.recentContestRows.length === 0}
            <p>{officeViewModel.recentContestEmptyMessage}</p>
          {:else}
            <div class="detail__table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Contest</th>
                    <th>Election date</th>
                    <th>Election type</th>
                    <th>Filing deadline</th>
                    <th>Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {#each officeViewModel.recentContestRows as row (row.contestId)}
                    <tr>
                      <td><a href={row.contestHref}>{row.contestName}</a></td>
                      <td>{row.electionDate}</td>
                      <td>{row.electionType}</td>
                      <td>{row.filingDeadline}</td>
                      <td>{row.candidateCoverageNote ?? "Complete"}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        {#if contestMap !== null}
          <section class="detail__panel">
            <h3>District map context</h3>
            <RegionMap
              pageLevel={contestMap.pageLevel}
              stateCode={contestMap.stateCode}
              layerVisibility={contestMap.layerVisibility}
              geometryByLevel={contestMap.geometryByLevel}
              highlightedFeatureId={officeViewModel.selectedElectoralDivisionId}
            />
          </section>
        {/if}
      {:else if sectionKey === "caveats" && officeViewModel.incompleteDataWarning}
        {@render caveatBanner(officeViewModel.incompleteDataWarning)}
      {/if}
    {/each}
  {:else if entityType === "contest" && contestViewModel}
    <header class="detail__header">
      <h2>{contestViewModel.title}</h2>
      <p class="detail__type">contest</p>
      <p><a href={contestViewModel.officeHref}>View office record</a></p>
    </header>

    {#each contestViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Contest facts</h3>
          <dl class="detail__rows">
            {#each contestViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={contestViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        <section class="detail__panel">
          <h3>Key metrics</h3>
          <dl class="detail__rows">
            {#each contestViewModel.keyMetricRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "records"}
        <section class="detail__panel" data-testid="contest-results-panel">
          <h3>Results</h3>
          {#if contestViewModel.resultWinnerPersonName}
            <dl class="detail__rows">
              <div class="detail__row">
                <dt>Winner</dt>
                <dd>
                  {#if contestViewModel.resultWinnerPersonHref}
                    <a href={contestViewModel.resultWinnerPersonHref}>
                      {contestViewModel.resultWinnerPersonName}
                    </a>
                  {:else}
                    {contestViewModel.resultWinnerPersonName}
                  {/if}
                </dd>
              </div>
              <div class="detail__row">
                <dt>Winning candidacy</dt>
                <dd>
                  {#if contestViewModel.resultWinnerCandidacyHref}
                    <a href={contestViewModel.resultWinnerCandidacyHref}>View candidacy detail</a>
                  {:else}
                    —
                  {/if}
                </dd>
              </div>
            </dl>
          {:else}
            <p>{contestViewModel.resultEmptyMessage}</p>
          {/if}
        </section>

        <section class="detail__panel">
          <h3>Candidacies</h3>
          {#if contestViewModel.candidacyRows.length === 0}
            <p>{contestViewModel.candidacyEmptyMessage}</p>
          {:else}
            <div class="detail__table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Candidacy record</th>
                    <th>Party</th>
                    <th>Status</th>
                    <th>Incumbent/challenger</th>
                  </tr>
                </thead>
                <tbody>
                  {#each contestViewModel.candidacyRows as row (row.id)}
                    <tr>
                      <td>
                        {#if row.personHref}
                          <a href={row.personHref}>{row.personName}</a>
                        {:else}
                          {row.personName}
                        {/if}
                      </td>
                      <td>
                        <a
                          href={row.candidacyHref}
                          aria-label={row.linkAriaLabel}
                        >
                          View candidacy detail
                        </a>
                      </td>
                      <td>{row.party}</td>
                      <td>{row.status}</td>
                      <td>{row.incumbentChallenge}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        <section class="detail__panel" data-testid="race-money-scoreboard">
          <h3>Money in this race</h3>
          {#if contestViewModel.raceMoneySummary}
            <!-- Answer-first summary: the one line a reader (or an extraction
                 model) should be able to take away without scrolling. -->
            <p class="detail__race-summary" data-testid="race-money-summary">
              <!-- Two sentences on the fundraising half too, for the same
                   reason as outside spending below: when no candidate in the
                   race has loaded fundraising there is no figure to put in the
                   sentence, and "$0.00 raised" is a measurement nobody took. -->
              {#if contestViewModel.raceMoneySummary.fundraisingKnown}
                Across {contestViewModel.raceMoneySummary.candidateCount} candidates in the
                {contestViewModel.raceMoneySummary.selectedCycle} cycle, Civibus has loaded
                {contestViewModel.raceMoneySummary.totalRaised} raised.
              {:else}
                Across {contestViewModel.raceMoneySummary.candidateCount} candidates in the
                {contestViewModel.raceMoneySummary.selectedCycle} cycle, Civibus has not loaded
                fundraising filings for this race, so the amount raised is not available — not
                zero.
              {/if}
              <!-- Two sentences, not one interpolated figure: when outside
                   spending was never loaded there is no number to put in the
                   sentence, and forcing one there is the whole defect. -->
              {#if contestViewModel.raceMoneySummary.outsideSpendingKnown}
                Outside groups spent {contestViewModel.raceMoneySummary.totalOutsideSupport}
                supporting and {contestViewModel.raceMoneySummary.totalOutsideOppose} opposing
                candidates in this race.
              {:else}
                Civibus has not loaded independent-expenditure filings for this race in this
                cycle, so outside spending is not available — not zero.
              {/if}
            </p>
            {#if contestViewModel.raceMoneySummary.incompleteNote}
              <p class="detail__caveat" data-testid="race-money-incomplete-note">
                {contestViewModel.raceMoneySummary.incompleteNote}
              </p>
            {/if}
            {#if contestViewModel.raceMoneySummary.outsideSpendingNote}
              <p class="detail__caveat" data-testid="race-outside-spending-incomplete-note">
                {contestViewModel.raceMoneySummary.outsideSpendingNote}
              </p>
            {/if}
          {/if}

          {#if contestViewModel.financeRows.length === 0}
            <p>{contestViewModel.financeEmptyMessage}</p>
          {:else}
            <div class="detail__table-scroll" data-testid="race-money-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Candidate</th>
                    <th scope="col">Party</th>
                    <th scope="col">Status</th>
                    <th scope="col">Money</th>
                    <th scope="col">Outside spending</th>
                  </tr>
                </thead>
                <tbody>
                  {#each contestViewModel.financeRows as financeRow (financeRow.personId)}
                    <tr data-testid="race-money-row">
                      <th scope="row">
                        {#if financeRow.candidateHref}
                          <a href={financeRow.candidateHref}>{financeRow.personName}</a>
                        {:else if financeRow.personHref}
                          <a href={financeRow.personHref}>{financeRow.personName}</a>
                        {:else}
                          {financeRow.personName}
                        {/if}
                      </th>
                      <td>{financeRow.party}</td>
                      <td>{financeRow.incumbentChallenge}</td>
                      <td>
                        {#if financeRow.moneyUnavailableMessage}
                          <!-- Unknown coverage renders as copy, never as a figure.
                               Publishing $0.00 here would assert something false
                               about a real campaign. -->
                          <span data-testid="race-money-unavailable"
                            >{financeRow.moneyUnavailableMessage}</span
                          >
                        {:else}
                          <dl class="detail__rows">
                            {#each financeRow.financeFacts as fact (fact.label)}
                              <div class="detail__row">
                                <dt>{fact.label}</dt>
                                <dd>{fact.value}</dd>
                              </div>
                            {/each}
                          </dl>
                        {/if}
                      </td>
                      <td>
                        <dl class="detail__rows">
                          {#each financeRow.outsideSpendingFacts as fact (fact.label)}
                            <div class="detail__row">
                              <dt>{fact.label}</dt>
                              <dd>{fact.value}</dd>
                            </div>
                          {/each}
                        </dl>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>

        {#if contestMap !== null}
          <section class="detail__panel">
            <h3>District map context</h3>
            <RegionMap
              pageLevel={contestMap.pageLevel}
              stateCode={contestMap.stateCode}
              layerVisibility={contestMap.layerVisibility}
              geometryByLevel={contestMap.geometryByLevel}
              highlightedFeatureId={contestViewModel.selectedElectoralDivisionId}
            />
          </section>
        {/if}
      {:else if sectionKey === "caveats" && contestViewModel.candidateListWarning}
        {@render caveatBanner(contestViewModel.candidateListWarning)}
      {/if}
    {/each}
  {:else if entityType === "candidacy" && candidacyViewModel}
    <header class="detail__header">
      <h2>{candidacyViewModel.title}</h2>
      <p class="detail__type">candidacy</p>
      <p><a href={candidacyViewModel.contestHref}>View contest record</a></p>
    </header>

    {#if candidacyViewModel.personHref}
      <section class="detail__panel">
        <p><a href={candidacyViewModel.personHref}>View person record</a></p>
      </section>
    {/if}

    {#each candidacyViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Candidacy facts</h3>
          <dl class="detail__rows">
            {#each candidacyViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={candidacyViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        <section class="detail__panel">
          <h3>Key metrics</h3>
          <dl class="detail__rows">
            {#each candidacyViewModel.keyMetricRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "caveats" && candidacyViewModel.statusEmptyMessage}
        {@render caveatBanner(candidacyViewModel.statusEmptyMessage)}
      {/if}
    {/each}
  {:else if entityType === "officeholding" && officeholdingViewModel}
    <header class="detail__header">
      <h2>{officeholdingViewModel.title}</h2>
      <p class="detail__type">officeholding</p>
      <p><a href={officeholdingViewModel.officeHref}>View office record</a></p>
    </header>

    {#if officeholdingViewModel.personHref}
      <section class="detail__panel">
        <p><a href={officeholdingViewModel.personHref}>View person record</a></p>
      </section>
    {/if}

    {#each officeholdingViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Officeholding facts</h3>
          <dl class="detail__rows">
            {#each officeholdingViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={officeholdingViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        <section class="detail__panel">
          <h3>Key metrics</h3>
          <dl class="detail__rows">
            {#each officeholdingViewModel.keyMetricRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "caveats" && officeholdingViewModel.validPeriodEmptyMessage}
        {@render caveatBanner(officeholdingViewModel.validPeriodEmptyMessage)}
      {/if}
    {/each}
  {/if}
</section>
