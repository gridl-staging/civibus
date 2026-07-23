<script lang="ts">
  import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
  import GeographyShareChart from "$lib/charts/GeographyShareChart.svelte";
  import HorizontalBarChart from "$lib/charts/HorizontalBarChart.svelte";
  import MonthlyContributionsChart from "$lib/charts/MonthlyContributionsChart.svelte";
  import OutsideSpendingChart from "$lib/charts/OutsideSpendingChart.svelte";
  import ReceiptCompositionChart from "$lib/charts/ReceiptCompositionChart.svelte";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import Portrait from "$lib/portrait/Portrait.svelte";
  import type { PersonDetailResponse, PersonPortraitResponse } from "$lib/entity-detail/contract";
  import {
    buildPersonDonorVendorEmptyStateBanner,
    buildPersonLinkedCommitteeEmptyStateBanner,
    buildPersonDonorVendorRows,
    buildPersonLinkedCommitteeRows,
    buildPersonContributionInsightsPresentation,
    buildPersonMoneyAtGlancePresentation,
    buildPersonMoneyAtGlanceSummary,
    buildPersonOutsideSpendingSection,
    buildEntityDetailShellPresentation,
    type EntityDetailShellPresentation,
    type PersonMoneyAtGlancePresentation,
    type PersonMoneyAtGlanceSummary
  } from "$lib/entity-detail/presentation";
  import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
  import type { PersonMoneyHeadlineState } from "$lib/server/api/entity-detail";
  import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
  import type {
    CandidateFundraisingSummary,
    PersonTopEmployerRow,
    RankedTransactionParty
  } from "$lib/campaign-finance-detail/contract";

  export let data: EntityDetailPageBundle;
  export let compareHref: string | null = null;

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
  let selectedSizeBucketUnit: "dollars" | "reported_transactions" = "dollars";

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
  $: personMoneyHeadline =
    data.entityType === "person" ? ((data.personMoneyHeadline ?? null) as PersonMoneyHeadlineState | null) : null;
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

  function combineDeferredPair<TFirst, TSecond>(
    first: TFirst | Promise<TFirst>,
    second: TSecond | Promise<TSecond>
  ): [TFirst, TSecond] | Promise<[TFirst, TSecond]> {
    if (isThenable(first) || isThenable(second)) {
      return Promise.all([first, second]);
    }

    return [first, second];
  }

  function buildMoneyAtGlanceSummary(
    sections: PersonCandidateFinanceSection[]
  ): PersonMoneyAtGlanceSummary | Promise<PersonMoneyAtGlanceSummary> {
    const summaries = sections.map((section) => section.summary) as Array<
      CandidateFundraisingSummary | Promise<CandidateFundraisingSummary>
    >;
    if (summaries.some(isThenable)) {
      return Promise.all(summaries).then(buildPersonMoneyAtGlanceSummary);
    }

    return buildPersonMoneyAtGlanceSummary(summaries as Array<CandidateFundraisingSummary>);
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
        <MonthlyContributionsChart
          testId={fundraisingDetail.monthlyContributions.testId}
          cycle={fundraisingDetail.monthlyContributions.cycle}
          coverageThrough={fundraisingDetail.monthlyContributions.coverageThrough}
          sources={fundraisingDetail.monthlyContributions.sources}
          rows={fundraisingDetail.monthlyContributions.rows}
          coveredMonths={fundraisingDetail.monthlyContributions.coveredMonths}
        />
        <p>{fundraisingDetail.unitemizedExclusionNote}</p>
        <div class="detail__segmented-control" role="group" aria-label="Contribution-size bucket scale">
          <span class="detail__segmented-label">Dollars | Reported transactions</span>
          <button
            type="button"
            aria-pressed={selectedSizeBucketUnit === "dollars"}
            onclick={() => (selectedSizeBucketUnit = "dollars")}
          >
            Dollars
          </button>
          <button
            type="button"
            aria-pressed={selectedSizeBucketUnit === "reported_transactions"}
            onclick={() => (selectedSizeBucketUnit = "reported_transactions")}
          >
            Reported transactions
          </button>
        </div>
        <HorizontalBarChart
          testId={fundraisingDetail.sizeBuckets.testId}
          title={fundraisingDetail.sizeBuckets.title}
          cycle={fundraisingDetail.sizeBuckets.cycle}
          coverageThrough={fundraisingDetail.sizeBuckets.coverageThrough}
          sources={fundraisingDetail.sizeBuckets.sources}
          rows={fundraisingDetail.sizeBuckets.rowsByUnit[selectedSizeBucketUnit]}
        />
        <p>Reported rows exclude unitemized counts and do not equal unique donors.</p>
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
        <GeographyShareChart
          testId={fundraisingDetail.geographyShare.testId}
          cycle={fundraisingDetail.geographyShare.cycle}
          coverageThrough={fundraisingDetail.geographyShare.coverageThrough}
          sources={fundraisingDetail.geographyShare.sources}
          rows={fundraisingDetail.geographyShare.rows}
          approximationNote={fundraisingDetail.geographyShare.approximationNote}
          unknownIncludedInDenominator={fundraisingDetail.geographyShare.mode === "district"}
        />
        <h5>{fundraisingDetail.rankingLabels.topDonors}</h5>
        {#if fundraisingDetail.topDonorsEmptyMessage !== null}
          <p>{fundraisingDetail.topDonorsEmptyMessage}</p>
        {:else}
          <div class="detail__table-scroll" data-testid="person-top-donors-scroll">
            <table>
              <thead>
                <tr>
                  <th>Reported contributor name</th>
                  <th>Total</th>
                  <th>Transactions</th>
                </tr>
              </thead>
              <tbody>
                {#each fundraisingDetail.topDonors as donor, donorIndex (`${donor.name}-${donorIndex}`)}
                  <tr>
                    <td>{donor.name}</td>
                    <td>
                      <span class="detail__rank-cell">
                        <span>{donor.totalAmount}</span>
                        <span
                          class="detail__rank-bar"
                          aria-hidden="true"
                          style:--rank-width={`${donor.barPercent}%`}
                        ></span>
                      </span>
                    </td>
                    <td>{donor.transactionCountLabel}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
        <h5>{fundraisingDetail.rankingLabels.topEmployers}</h5>
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
                    <td>
                      <span class="detail__rank-cell">
                        <span>{employer.totalAmount}</span>
                        <span
                          class="detail__rank-bar"
                          aria-hidden="true"
                          style:--rank-width={`${employer.barPercent}%`}
                        ></span>
                      </span>
                    </td>
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

{#snippet moneyAtGlanceSummaryRows(moneyAtGlance: PersonMoneyAtGlancePresentation)}
  <dl class="detail__rows">
    <div class="detail__row">
      <dt>Coverage</dt>
      <dd>{moneyAtGlance.coverageLabel}</dd>
    </div>
    <div class="detail__row">
      <dt>Source</dt>
      <dd>{moneyAtGlance.sourceLabel}</dd>
    </div>
    <div class="detail__row">
      <dt>Outside spending</dt>
      <dd><a class="detail__cta-link" href="#person-outside-spending">Outside spending details</a></dd>
    </div>
  </dl>
{/snippet}

{#snippet moneyAtGlanceCycleNav(moneyAtGlance: PersonMoneyAtGlancePresentation)}
  {#if moneyAtGlance.cycleOptions.length > 0}
    <nav class="detail__cycle-nav" aria-label="Election cycle">
      {#each moneyAtGlance.cycleOptions as option (option.cycle)}
        <a href={option.href} aria-current={option.selected ? "page" : undefined}>{option.label}</a>
      {/each}
    </nav>
  {/if}
{/snippet}

{#snippet moneyAtGlanceMetricRows(
  moneyAtGlance: PersonMoneyAtGlancePresentation,
  layout: "rows" | "grid"
)}
  {#if layout === "grid"}
    <dl class="detail__metrics-grid">
      {#each moneyAtGlance.metricRows as row (row.label)}
        <div class="detail__metric">
          <dt class="detail__metric-label">{row.label}</dt>
          <dd class="detail__metric-value">{row.value}</dd>
        </div>
      {/each}
    </dl>
  {:else}
    <dl class="detail__rows">
      {#each moneyAtGlance.metricRows as row (row.label)}
        <div class="detail__row">
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      {/each}
    </dl>
  {/if}
{/snippet}

{#snippet moneyAtGlanceReceiptComposition(
  moneyAtGlance: PersonMoneyAtGlancePresentation,
  testId: string
)}
  <ReceiptCompositionChart
    {testId}
    cycle={moneyAtGlance.receiptComposition.cycle}
    coverageThrough={moneyAtGlance.receiptComposition.coverageThrough}
    sources={moneyAtGlance.receiptComposition.sources}
    rows={moneyAtGlance.receiptComposition.rows}
    totalReceipts={moneyAtGlance.receiptComposition.totalReceipts}
    canPlot={moneyAtGlance.receiptComposition.canPlot}
    caveat={moneyAtGlance.receiptComposition.caveat}
  />
{/snippet}

{#snippet moneyHeadline(headline: PersonMoneyHeadlineState)}
  {#if headline.kind === "loaded"}
    {@const moneyAtGlance = buildPersonMoneyAtGlancePresentation(headline.summary)}
    <section class="detail__money-glance" aria-label={moneyAtGlance.heading}>
      <h4>{moneyAtGlance.heading}</h4>
      <p>{moneyAtGlance.cycleLabel}</p>
      {@render moneyAtGlanceSummaryRows(moneyAtGlance)}
      {@render moneyAtGlanceCycleNav(moneyAtGlance)}
      {@render moneyAtGlanceMetricRows(moneyAtGlance, "rows")}
      {@render moneyAtGlanceReceiptComposition(
        moneyAtGlance,
        moneyAtGlance.receiptComposition.testId
      )}
    </section>
  {:else if headline.kind === "no_linked_candidate"}
    <p>{headline.message}</p>
  {:else}
    <section class="detail__money-glance" aria-label="Money at a glance">
      <h4>Money at a glance</h4>
      <p>{headline.selectedCycle} cycle</p>
      <p>{headline.message}</p>
    </section>
  {/if}
{/snippet}

{#snippet moneyAtGlance(sections: PersonCandidateFinanceSection[])}
  {#await buildMoneyAtGlanceSummary(sections)}
    <SkeletonPanel label="Selected-cycle money" lines={4} />
  {:then summary}
    {@const moneyAtGlance = buildPersonMoneyAtGlancePresentation(summary)}
    <section class="detail__money-glance" aria-label={moneyAtGlance.heading}>
      <div class="detail__section-heading">
        <h4>{moneyAtGlance.heading}</h4>
        <p>{moneyAtGlance.cycleLabel}</p>
      </div>
      {@render moneyAtGlanceCycleNav(moneyAtGlance)}
      {@render moneyAtGlanceSummaryRows(moneyAtGlance)}
      {@render moneyAtGlanceMetricRows(moneyAtGlance, "grid")}
      {@render moneyAtGlanceReceiptComposition(moneyAtGlance, moneyAtGlance.receiptComposition.testId)}
    </section>
  {:catch}
    <p>Selected-cycle money summary is temporarily unavailable.</p>
  {/await}
{/snippet}

<section class="card detail" aria-label="Entity detail">
  <header class="detail__header">
    {#if data.entityType === "person"}
      <Portrait canonicalName={shellViewModel.canonicalName} personId={data.detail.id} {portrait} />
    {/if}
    <h2>{shellViewModel.canonicalName}</h2>
    <p class="detail__type">{shellViewModel.entityType}</p>
    {#if personDetail !== null && compareHref !== null}
      <a class="detail__cta-link" href={compareHref}>Compare</a>
    {/if}
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
          {#if personMoneyHeadline !== null}
            {@render moneyHeadline(personMoneyHeadline)}
          {/if}
          {#await personFinanceSections}
            {@render fundraisingDetail()}
            <SkeletonPanel label="Finance data loading" lines={8} />
          {:then personFinanceSections}
            {#if personFinanceSections.length === 0}
              {@render fundraisingDetail()}
              {#if personMoneyHeadline === null}
                <p>No campaign-finance candidacies are linked yet.</p>
              {/if}
            {:else}
              {#if personMoneyHeadline === null}
                {@render moneyAtGlance(personFinanceSections)}
              {/if}
              {@render fundraisingDetail()}

              {#each personFinanceSections as section (section.candidate.id)}
                <article class="detail__committee-card">
                  <h4>
                    <a href={buildCandidateHref(section.candidate)}>
                      {section.candidate.name}
                    </a>
                  </h4>

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
                      <div class="detail__table-scroll" data-testid="person-linked-committees">
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

                  <h4 id="person-outside-spending">Outside spending</h4>
                  {#await combineDeferredPair(section.ieSummary, section.ieTransactions)}
                    <SkeletonPanel label="Outside spending" lines={4} />
                  {:then [ieSummary, ieTransactions]}
                    {@const outsideSpending = buildPersonOutsideSpendingSection(ieSummary, ieTransactions)}
                    {#if outsideSpending.emptyMessage || ieSummary === null}
                      <p>{outsideSpending.emptyMessage}</p>
                    {:else}
                      {#if outsideSpending.explanatoryBlock}
                        <p>{outsideSpending.explanatoryBlock}</p>
                      {/if}
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
                      <OutsideSpendingChart
                        testId="person-outside-spending"
                        cycle={ieSummary.selected_cycle}
                        coverageThrough={ieSummary.coverage_end_date}
                        sources={[
                          {
                            label: "FEC Schedule E independent expenditures",
                            href: "https://www.fec.gov/data/independent-expenditures/"
                          }
                        ]}
                        rows={outsideSpending.chartRows}
                        topSpenders={outsideSpending.chartTopSpenders}
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
                      <h5>Transactions</h5>
                      {#if outsideSpending.transactionRows.length === 0}
                        <p>No outside-spending transactions available.</p>
                      {:else}
                        <div class="detail__table-scroll" data-testid="person-ie-transactions-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Date</th>
                                <th>Spender</th>
                                <th>Stance</th>
                                <th>Amount</th>
                                <th>Dissemination date</th>
                                <th>Source</th>
                              </tr>
                            </thead>
                            <tbody>
                              {#each outsideSpending.transactionRows as row (row.rowKey)}
                                <tr>
                                  <td>{row.date}</td>
                                  <td><a href={row.spenderHref}>{row.spender}</a></td>
                                  <td>{row.stance}</td>
                                  <td>{row.amount}</td>
                                  <td>{row.disseminationDate}</td>
                                  <td>
                                    {#if row.sourceHref}
                                      <a href={row.sourceHref}>Source filing</a>
                                    {:else}
                                      Source filing unavailable
                                    {/if}
                                  </td>
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

<style>
  .detail__rank-cell {
    display: grid;
    gap: 0.25rem;
    min-width: 8rem;
  }

  .detail__rank-bar {
    background: linear-gradient(90deg, #0f766e var(--rank-width), #e2e8f0 0);
    border: 1px solid #cbd5e1;
    display: block;
    height: 0.5rem;
  }
</style>
