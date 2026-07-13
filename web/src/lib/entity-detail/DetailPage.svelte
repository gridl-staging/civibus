<script lang="ts">
  import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
  import Chart from "$lib/charts/Chart.svelte";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import Portrait from "$lib/portrait/Portrait.svelte";
  import type { PersonDetailResponse, PersonPortraitResponse } from "$lib/entity-detail/contract";
  import {
    buildPersonDonorVendorEmptyStateBanner,
    buildPersonLinkedCommitteeEmptyStateBanner,
    buildPersonDonorVendorRows,
    buildPersonFinanceSummaryPresentation,
    buildPersonLinkedCommitteeRows,
    buildPersonContributionInsightsPresentation,
    buildPersonOutsideSpendingChartSeries,
    buildPersonOutsideSpendingSection,
    buildPersonSummaryChartSeries,
    buildEntityDetailShellPresentation,
    type EntityDetailShellPresentation
  } from "$lib/entity-detail/presentation";
  import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
  import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
  import type { PersonTopEmployerRow, RankedTransactionParty } from "$lib/campaign-finance-detail/contract";

  export let data: EntityDetailPageBundle;

  let shellViewModel: EntityDetailShellPresentation;
  $: shellViewModel = buildEntityDetailShellPresentation({
    entityType: data.entityType,
    detail: data.detail
  });

  const BIO_LICENSE_LABELS: Record<string, string> = {
    public_domain: "Public domain",
    licensed: "Licensed (CC BY-SA)",
    restricted: "Used with attribution",
    unknown: "Source unknown"
  };
  const EMPTY_PERSON_FINANCE_SECTIONS: PersonCandidateFinanceSection[] = [];
  const EMPTY_PERSON_TOP_DONORS: RankedTransactionParty[] = [];
  const EMPTY_PERSON_TOP_EMPLOYERS: PersonTopEmployerRow[] = [];
  let selectedContributionTotalView: "cycle" | "career" = "cycle";

  $: personDetail =
    data.entityType === "person" ? (data.detail as PersonDetailResponse) : null;
  $: personBioLicenseLabel =
    personDetail === null
      ? null
      : personDetail.bio_license === null
        ? BIO_LICENSE_LABELS.unknown
        : (BIO_LICENSE_LABELS[personDetail.bio_license] ?? BIO_LICENSE_LABELS.unknown);
  $: safeBioSourceUrl =
    personDetail === null ? null : normalizeSafeExternalHttpUrl(personDetail.bio_source_url);
  $: portrait =
    data.entityType === "person" && "portrait" in data.detail
      ? ((data.detail.portrait ?? null) as PersonPortraitResponse | null)
      : null;
  $: personFinanceSections =
    data.entityType === "person"
      ? (data.personFinanceSections ?? Promise.resolve(EMPTY_PERSON_FINANCE_SECTIONS))
      : null;
  $: personContributionInsights =
    data.entityType === "person" ? (data.personContributionInsights ?? null) : null;
  $: personTopDonors =
    data.entityType === "person"
      ? (data.personTopDonors ?? Promise.resolve(EMPTY_PERSON_TOP_DONORS))
      : null;
  $: personTopEmployers =
    data.entityType === "person"
      ? (data.personTopEmployers ?? Promise.resolve(EMPTY_PERSON_TOP_EMPLOYERS))
      : null;

  function buildMetricTestId(label: string): string {
    return `entity-metric-${label.toLowerCase().replace(/\s+/g, "-")}`;
  }

  function normalizeSafeExternalHttpUrl(url: string | null | undefined): string | null {
    if (typeof url !== "string") {
      return null;
    }
    const normalized = url.trim();
    if (normalized === "") {
      return null;
    }
    let parsed: URL;
    try {
      parsed = new URL(normalized);
    } catch {
      return null;
    }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return null;
    }
    return parsed.toString();
  }

  function isThenable<T>(value: T | Promise<T>): value is Promise<T> {
    return value !== null && typeof (value as Promise<T>).then === "function";
  }

  function combineDeferredTriple<TFirst, TSecond, TThird>(
    first: TFirst | Promise<TFirst>,
    second: TSecond | Promise<TSecond>,
    third: TThird | Promise<TThird>
  ): [TFirst, TSecond, TThird] | Promise<[TFirst, TSecond, TThird]> {
    if (isThenable(first) || isThenable(second) || isThenable(third)) {
      return Promise.all([first, second, third]);
    }

    return [first, second, third];
  }
</script>

{#snippet fundraisingDetail()}
  {#if personContributionInsights !== null && personTopDonors !== null && personTopEmployers !== null}
    <h4>Fundraising detail</h4>
    {#await combineDeferredTriple(personContributionInsights, personTopDonors, personTopEmployers)}
      <SkeletonPanel label="Finance data loading" lines={5} />
    {:then [contributionInsights, topDonors, topEmployers]}
      {@const fundraisingDetail = buildPersonContributionInsightsPresentation(
        contributionInsights,
        topDonors,
        topEmployers
      )}
      {#if fundraisingDetail.emptyMessage}
        <p>{fundraisingDetail.emptyMessage}</p>
      {:else}
        {@const selectedTotalSummary =
          fundraisingDetail.totalSummaryViews.find((view) => view.key === selectedContributionTotalView) ??
          fundraisingDetail.totalSummaryViews[0] ??
          null}
        {#each fundraisingDetail.caveatMessages as caveatMessage (caveatMessage)}
          <p>{caveatMessage}</p>
        {/each}
        <dl class="detail__rows">
          <div class="detail__row">
            <dt>Small-dollar share</dt>
            <dd>{fundraisingDetail.smallDollarHeadline}</dd>
          </div>
          <div class="detail__row">
            <dt>Small-dollar amount</dt>
            <dd>{fundraisingDetail.smallDollarSummary}</dd>
          </div>
          <div class="detail__row">
            <dt>Coverage</dt>
            <dd>{fundraisingDetail.coverageLabel}</dd>
          </div>
        </dl>
        <h5>Individual contribution totals</h5>
        {#if selectedTotalSummary === null}
          <p>{fundraisingDetail.totalsEmptyMessage}</p>
        {:else}
          <div class="detail__segmented-control" role="group" aria-label="Contribution totals view">
            {#each fundraisingDetail.totalSummaryViews as totalSummaryView (totalSummaryView.key)}
              <button
                type="button"
                aria-pressed={selectedTotalSummary.key === totalSummaryView.key}
                onclick={() => (selectedContributionTotalView = totalSummaryView.key)}
              >
                {totalSummaryView.label}
              </button>
            {/each}
          </div>
          <dl class="detail__rows" data-testid="person-contribution-total-summary">
            <div class="detail__row">
              <dt>{selectedTotalSummary.label}</dt>
              <dd>{selectedTotalSummary.amountLabel}</dd>
            </div>
            <div class="detail__row">
              <dt>Itemized</dt>
              <dd>{selectedTotalSummary.itemizedAmountLabel}</dd>
            </div>
            <div class="detail__row">
              <dt>Unitemized</dt>
              <dd>{selectedTotalSummary.unitemizedAmountLabel}</dd>
            </div>
            <div class="detail__row">
              <dt>Itemized transactions</dt>
              <dd>{selectedTotalSummary.transactionCountLabel}</dd>
            </div>
          </dl>
          {#if selectedTotalSummary.caveatMessage !== null}
            <p>{selectedTotalSummary.caveatMessage}</p>
          {/if}
        {/if}
        <Chart
          kind="line"
          title="Donations over time"
          ariaLabel={`Donations over time for ${shellViewModel.canonicalName}`}
          series={fundraisingDetail.monthlyTotalsSeries}
        />
        <p>{fundraisingDetail.unitemizedExclusionNote}</p>
        <Chart
          kind="bar"
          title="Donation count by size bucket"
          ariaLabel={`Donation count by size bucket for ${shellViewModel.canonicalName}`}
          series={fundraisingDetail.itemizedCountSeries}
        />
        <Chart
          kind="bar"
          title="Dollars by size bucket"
          ariaLabel={`Dollars by size bucket for ${shellViewModel.canonicalName}`}
          series={fundraisingDetail.dollarsBySizeSeries}
        />
        <ul class="detail__inline-list" aria-label="Dollars by size bucket labels">
          {#each fundraisingDetail.dollarsBySizeSeries[0]?.points ?? [] as point (String(point.x))}
            <li>{point.x}</li>
          {/each}
        </ul>
        <p>{fundraisingDetail.geographyNote}</p>
        <dl class="detail__rows">
          <div class="detail__row">
            <dt>District share</dt>
            <dd>{fundraisingDetail.districtShareHeadline}</dd>
          </div>
          <div class="detail__row">
            <dt>District share basis</dt>
            <dd>{fundraisingDetail.districtShareSummary}</dd>
          </div>
        </dl>
        <Chart
          kind="bar"
          title="Fundraising geography"
          ariaLabel={`Fundraising geography for ${shellViewModel.canonicalName}`}
          series={fundraisingDetail.preferredGeographySeries}
        />
        <h5>Top donors</h5>
        {#if fundraisingDetail.topDonorsEmptyMessage !== null}
          <p>{fundraisingDetail.topDonorsEmptyMessage}</p>
        {:else}
          <div class="detail__table-scroll" data-testid="person-top-donors-scroll">
            <table>
              <thead>
                <tr>
                  <th>Donor</th>
                  <th>Total</th>
                  <th>Transactions</th>
                </tr>
              </thead>
              <tbody>
                {#each fundraisingDetail.topDonors as donor, donorIndex (`${donor.name}-${donorIndex}`)}
                  <tr>
                    <td>{donor.name}</td>
                    <td>{donor.totalAmount}</td>
                    <td>{donor.transactionCountLabel}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
        <h5>Top employers</h5>
        <p>{fundraisingDetail.topEmployerDisclaimer}</p>
        <p>{fundraisingDetail.topEmployerMethodologyReference}</p>
        {#if fundraisingDetail.topEmployersEmptyMessage !== null}
          <p>{fundraisingDetail.topEmployersEmptyMessage}</p>
        {:else}
          <div class="detail__table-scroll" data-testid="person-top-employers-scroll">
            <table>
              <thead>
                <tr>
                  <th>Employer</th>
                  <th>Total</th>
                  <th>Transactions</th>
                </tr>
              </thead>
              <tbody>
                {#each fundraisingDetail.topEmployers as employer, employerIndex (`${employer.name}-${employerIndex}`)}
                  <tr>
                    <td>{employer.name}</td>
                    <td>{employer.totalAmount}</td>
                    <td>{employer.transactionCountLabel}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/if}
    {:catch}
      <p>Contribution insights are temporarily unavailable.</p>
    {/await}
  {/if}
{/snippet}

<section class="card detail" aria-label="Entity detail">
  <header class="detail__header">
    {#if data.entityType === "person"}
      <Portrait canonicalName={shellViewModel.canonicalName} personId={data.detail.id} {portrait} />
    {/if}
    <h2>{shellViewModel.canonicalName}</h2>
    <p class="detail__type">{shellViewModel.entityType}</p>
  </header>

  {#if personDetail !== null && personDetail.bio_text !== null}
    <section class="detail__panel detail__bio-panel">
      <h3>Biography</h3>
      <p>{personDetail.bio_text}</p>
      <p class="detail__bio-attribution">
        {#if safeBioSourceUrl !== null}
          <a href={safeBioSourceUrl} rel="noopener noreferrer">Biography source</a>
        {:else}
          <span>Biography source unavailable</span>
        {/if}
        <span>{personBioLicenseLabel}</span>
      </p>
    </section>
  {/if}

  {#each shellViewModel.sectionOrder as sectionKey (sectionKey)}
    {#if sectionKey === "summary"}
      <section class="detail__panel">
        <h3>Core attributes</h3>
        <dl class="detail__rows">
          {#each shellViewModel.coreFactRows as row (row.label)}
            <div class="detail__row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "trust"}
      <TrustSection trustSection={shellViewModel.trustSection} />
    {:else if sectionKey === "metrics"}
      <section class="detail__panel">
        <h3>Key metrics</h3>
        <dl class="detail__rows">
          {#each shellViewModel.keyMetricRows as row (row.label)}
            <div class="detail__row" data-testid={buildMetricTestId(row.label)}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {:else if sectionKey === "records"}
      <section class="detail__panel">
        <h3>Identifiers</h3>
        {#if shellViewModel.identifierRows.length === 0}
          <p>{shellViewModel.identifierEmptyMessage}</p>
        {:else}
          <dl class="detail__rows">
            {#each shellViewModel.identifierRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          </dl>
        {/if}
      </section>
    {:else if sectionKey === "person-campaign-finance"}
      {#if data.entityType === "person" && personFinanceSections !== null}
        <section class="detail__panel">
          <h3>Campaign finance</h3>
          {#await personFinanceSections}
            {@render fundraisingDetail()}
            <SkeletonPanel label="Finance data loading" lines={8} />
          {:then personFinanceSections}
            {#if personFinanceSections.length === 0}
              {@render fundraisingDetail()}
              <p>No campaign-finance candidacies are linked yet.</p>
            {:else}
              {#each personFinanceSections as section, sectionIndex (section.candidate.id)}
                <article class="detail__committee-card">
                  <h4>
                    <a href={buildCandidateHref(section.candidate)}>
                      {section.candidate.name}
                    </a>
                  </h4>

                  {#await section.summary}
                    <SkeletonPanel label="Candidate finance summary" lines={4} />
                  {:then summary}
                    {@const fundraisingSummary = buildPersonFinanceSummaryPresentation(summary)}
                    {@const summaryChartSeries = buildPersonSummaryChartSeries(summary)}
                    <dl class="detail__rows">
                      <div class="detail__row">
                        <dt>Total raised</dt>
                        <dd>{fundraisingSummary.totalRaised}</dd>
                      </div>
                      <div class="detail__row">
                        <dt>Total spent</dt>
                        <dd>{fundraisingSummary.totalSpent}</dd>
                      </div>
                      <div class="detail__row">
                        <dt>Net</dt>
                        <dd>{fundraisingSummary.net}</dd>
                      </div>
                      <div class="detail__row">
                        <dt>Transaction count</dt>
                        <dd>{fundraisingSummary.transactionCount}</dd>
                      </div>
                    </dl>
                    <Chart
                      kind="bar"
                      title={`Finance chart: ${section.candidate.name}`}
                      ariaLabel={`Finance chart for ${shellViewModel.canonicalName}`}
                      series={summaryChartSeries}
                    />
                  {:catch}
                    <p>Candidate fundraising summary is temporarily unavailable.</p>
                  {/await}

                  {#if sectionIndex === 0}
                    {@render fundraisingDetail()}
                  {/if}

                  <h4>Linked committees</h4>
                  {#await section.summary}
                    <SkeletonPanel label="Linked committees" lines={4} />
                  {:then summary}
                    {@const linkedCommitteeRows = buildPersonLinkedCommitteeRows(summary)}
                    {@const linkedCommitteeBanner = buildPersonLinkedCommitteeEmptyStateBanner(
                      linkedCommitteeRows.length
                    )}
                    {#if linkedCommitteeBanner}
                      <p>{linkedCommitteeBanner}</p>
                    {:else}
                      <div class="detail__table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Committee</th>
                              <th>Raised</th>
                              <th>Spent</th>
                              <th>Net</th>
                              <th>Transactions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {#each linkedCommitteeRows as committee (committee.committeeId)}
                              <tr>
                                <td><a href={committee.committeeHref}>{committee.committeeName}</a></td>
                                <td>{committee.totalRaised}</td>
                                <td>{committee.totalSpent}</td>
                                <td>{committee.net}</td>
                                <td>{committee.transactionCount}</td>
                              </tr>
                            {/each}
                          </tbody>
                        </table>
                      </div>
                    {/if}
                  {:catch}
                    <p>Linked committees are temporarily unavailable.</p>
                  {/await}

                  <h4>Donors and vendors</h4>
                  {#await section.donorVendorTransactions}
                    <SkeletonPanel label="Donor/vendor transactions" lines={4} />
                  {:then donorVendorTransactions}
                    {@const donorVendorRows = buildPersonDonorVendorRows(donorVendorTransactions)}
                    {@const donorVendorBanner = buildPersonDonorVendorEmptyStateBanner(donorVendorRows.length)}
                    {#if donorVendorBanner}
                      <p>{donorVendorBanner}</p>
                    {:else}
                      <div class="detail__table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Date</th>
                              <th>Amount</th>
                              <th>Type</th>
                              <th>Contributor</th>
                            </tr>
                          </thead>
                          <tbody>
                            {#each donorVendorRows as row (row.id)}
                              <tr>
                                <td>{row.date}</td>
                                <td>{row.amount}</td>
                                <td>{row.transactionType}</td>
                                <td>{row.contributorName}</td>
                              </tr>
                            {/each}
                          </tbody>
                        </table>
                      </div>
                    {/if}
                  {:catch}
                    <p>Donor/vendor transactions are temporarily unavailable.</p>
                  {/await}

                  <h4>Outside Spending</h4>
                  {#await section.ieSummary}
                    <SkeletonPanel label="Outside spending" lines={4} />
                  {:then ieSummary}
                    {@const outsideSpending = buildPersonOutsideSpendingSection(ieSummary, [])}
                    {@const outsideSpendingSeries = buildPersonOutsideSpendingChartSeries(ieSummary)}
                    {#if outsideSpending.emptyMessage}
                      <p>{outsideSpending.emptyMessage}</p>
                    {:else}
                      <dl class="detail__rows">
                        <div class="detail__row">
                          <dt>Support total</dt>
                          <dd>{outsideSpending.supportTotal}</dd>
                        </div>
                        <div class="detail__row">
                          <dt>Oppose total</dt>
                          <dd>{outsideSpending.opposeTotal}</dd>
                        </div>
                      </dl>
                      <Chart
                        kind="bar"
                        title={`Outside spending chart: ${section.candidate.name}`}
                        ariaLabel={`Outside spending chart for ${section.candidate.name}`}
                        series={outsideSpendingSeries}
                      />
                      <h5>Top spenders</h5>
                      {#if outsideSpending.topSpenders.length === 0}
                        <p>No outside-spending rankings available.</p>
                      {:else}
                        <div class="detail__table-scroll" data-testid="person-ie-top-spenders-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Spender</th>
                                <th>Stance</th>
                                <th>Total</th>
                                <th>Expenditures</th>
                              </tr>
                            </thead>
                            <tbody>
                              {#each outsideSpending.topSpenders as spender, spenderIndex (`${spender.committeeName}-${spenderIndex}`)}
                                <tr>
                                  <td><a href={spender.committeeHref}>{spender.committeeName}</a></td>
                                  <td>{spender.stance}</td>
                                  <td>{spender.totalAmount}</td>
                                  <td>{spender.transactionCountLabel}</td>
                                </tr>
                              {/each}
                            </tbody>
                          </table>
                        </div>
                      {/if}
                    {/if}
                  {:catch}
                    <p>Outside-spending data is temporarily unavailable.</p>
                  {/await}
                </article>
              {/each}
            {/if}
          {:catch}
            {@render fundraisingDetail()}
            <p>Campaign-finance sections are temporarily unavailable.</p>
          {/await}
        </section>
      {/if}
    {/if}
  {/each}
</section>
