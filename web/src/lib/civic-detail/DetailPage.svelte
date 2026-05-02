<script lang="ts">
  import { navigating } from "$app/stores";
  import Chart from "$lib/charts/Chart.svelte";
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
    type OfficeholdingDetailPresentation,
    type ContestCandidateFinanceByPersonId
  } from "$lib/civic-detail/presentation";
  import {
    CIVIC_ROUTE_PREFIXES,
    type CandidacyDetailResponse,
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
  export let contestCandidateFinanceByPersonId: ContestCandidateFinanceByPersonId = {};
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
        candidateFinanceByPersonId: contestCandidateFinanceByPersonId
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
          <h3>Recent contests</h3>
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
        <section class="detail__panel">
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

        <section class="detail__panel">
          <h3>Candidate finance and outside spending</h3>
          {#if contestViewModel.financeRows.length === 0}
            <p>{contestViewModel.financeEmptyMessage}</p>
          {:else}
            {#each contestViewModel.financeRows as financeRow (financeRow.personId)}
              <article class="detail__committee-card">
                <h4>
                  {#if financeRow.candidateHref}
                    <a href={financeRow.candidateHref}>{financeRow.personName}</a>
                  {:else if financeRow.personHref}
                    <a href={financeRow.personHref}>{financeRow.personName}</a>
                  {:else}
                    {financeRow.personName}
                  {/if}
                </h4>

                {#if financeRow.fundraisingSummary}
                  <h5>Fundraising summary</h5>
                  <dl class="detail__rows">
                    <div class="detail__row">
                      <dt>Total raised</dt>
                      <dd>{financeRow.fundraisingSummary.totalRaised}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Total spent</dt>
                      <dd>{financeRow.fundraisingSummary.totalSpent}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Net</dt>
                      <dd>{financeRow.fundraisingSummary.net}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Transactions</dt>
                      <dd>{financeRow.fundraisingSummary.transactionCount}</dd>
                    </div>
                  </dl>
                  <Chart
                    kind="bar"
                    title={`Finance chart: ${financeRow.personName}`}
                    ariaLabel={`Finance chart for ${financeRow.personName}`}
                    series={financeRow.financeChartSeries}
                  />
                {:else}
                  <p>Candidate fundraising data is not yet available.</p>
                {/if}

                <h5>Outside Spending</h5>
                {#if financeRow.outsideSpending.emptyMessage}
                  <p>{financeRow.outsideSpending.emptyMessage}</p>
                {:else}
                  <dl class="detail__rows">
                    <div class="detail__row">
                      <dt>Support total</dt>
                      <dd>{financeRow.outsideSpending.supportTotal}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Oppose total</dt>
                      <dd>{financeRow.outsideSpending.opposeTotal}</dd>
                    </div>
                  </dl>
                  <Chart
                    kind="bar"
                    title={`Outside spending chart: ${financeRow.personName}`}
                    ariaLabel={`Outside spending chart for ${financeRow.personName}`}
                    series={financeRow.outsideSpendingChartSeries}
                  />
                {/if}
              </article>
            {/each}
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
