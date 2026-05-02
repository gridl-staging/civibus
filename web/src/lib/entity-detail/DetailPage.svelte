<script lang="ts">
  import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
  import Chart from "$lib/charts/Chart.svelte";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import GraphViewer from "$lib/graph/GraphViewer.svelte";
  import { buildGraphElements } from "$lib/graph/transform";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import Portrait from "$lib/portrait/Portrait.svelte";
  import type { PersonDetailResponse, PersonPortraitResponse } from "$lib/entity-detail/contract";
  import {
    buildPersonDonorVendorEmptyStateBanner,
    buildPersonLinkedCommitteeEmptyStateBanner,
    buildResolvedKeyMetrics,
    buildPersonCandidacyRows,
    buildPersonDonorVendorRows,
    buildPersonFinanceSummaryPresentation,
    buildPersonLinkedCommitteeRows,
    buildPersonOfficeholdingTimelineRows,
    buildPersonOutsideSpendingChartSeries,
    buildPersonOutsideSpendingSection,
    buildPersonSummaryChartSeries,
    buildUnavailableKeyMetrics,
    buildCivicRecordSection,
    buildEntityDetailShellPresentation,
    buildTechnicalDisclosureSection,
    type EntityDetailShellPresentation
  } from "$lib/entity-detail/presentation";
  import type {
    EntityDetailPageBundle,
    PersonCivicHistorySections
  } from "$lib/server/api/entity-detail";
  import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";

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

  const graphNeighborListId = "entity-neighbor-list";
  const EMPTY_PERSON_CIVIC_HISTORY: PersonCivicHistorySections = {
    officeholdings: [],
    candidacies: [],
    officeholdingLabelsById: {},
    officeLabelsById: {},
    candidacyLabelsById: {},
    contestLabelsById: {}
  };
  const EMPTY_PERSON_FINANCE_SECTIONS: PersonCandidateFinanceSection[] = [];
  let personCivicHistory: Promise<PersonCivicHistorySections> | null = null;
  $: personCivicHistory =
    data.entityType === "person"
      ? (data.personCivicHistory ?? Promise.resolve(EMPTY_PERSON_CIVIC_HISTORY))
      : null;
  let personFinanceSections: Promise<PersonCandidateFinanceSection[]> | null = null;
  $: personFinanceSections =
    data.entityType === "person"
      ? (data.personFinanceSections ?? Promise.resolve(EMPTY_PERSON_FINANCE_SECTIONS))
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
</script>

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
          {#await Promise.all([data.matches, data.relationships])}
            {#each shellViewModel.keyMetricRows as row (row.label)}
              <div class="detail__row" data-testid={buildMetricTestId(row.label)}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          {:then [matches, relationships]}
            {@const resolvedKeyMetricRows = buildResolvedKeyMetrics(
              shellViewModel.identifierRows,
              matches,
              relationships
            )}
            {#each resolvedKeyMetricRows as row (row.label)}
              <div class="detail__row" data-testid={buildMetricTestId(row.label)}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          {:catch}
            {@const unavailableKeyMetricRows = buildUnavailableKeyMetrics(shellViewModel.identifierRows)}
            {#each unavailableKeyMetricRows as row (row.label)}
              <div class="detail__row" data-testid={buildMetricTestId(row.label)}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            {/each}
          {/await}
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
    {:else if sectionKey === "civic-record"}
      {#await data.relationships}
        <SkeletonPanel label="Civic Record" lines={3} />
      {:then relationships}
        {@const civicRecordSection = buildCivicRecordSection(data.entityType, relationships.neighbors)}
        {#if civicRecordSection}
          <section class="detail__panel">
            <h3>{civicRecordSection.title}</h3>
            {#if civicRecordSection.rows.length === 0}
              <p>{civicRecordSection.emptyMessage}</p>
            {:else}
              <div class="detail__table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Record</th>
                      <th>Record type</th>
                      <th>Office/contest context</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each civicRecordSection.rows as row (row.recordHref)}
                      <tr>
                        <td><a href={row.recordHref}>{row.recordName}</a></td>
                        <td>{row.recordType}</td>
                        <td>
                          {#if row.contextHref !== null && row.contextLabel !== null && row.contextName !== null}
                            {row.contextLabel}: <a href={row.contextHref}>{row.contextName}</a>
                          {:else if row.contextLabel !== null && row.contextName !== null}
                            {row.contextLabel}: {row.contextName}
                          {:else}
                            —
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>
        {/if}
      {:catch}
        <section class="detail__panel">
          <h3>Civic Record</h3>
          <p>Civic record relationships are temporarily unavailable.</p>
        </section>
      {/await}
    {:else if sectionKey === "person-civic-history"}
      {#if data.entityType === "person" && personCivicHistory !== null}
        {#await personCivicHistory}
          <SkeletonPanel label="Civic history" lines={6} />
        {:then civicHistory}
          {@const officeholdingRows = buildPersonOfficeholdingTimelineRows(civicHistory.officeholdings, {
            officeholdingLabelsById: civicHistory.officeholdingLabelsById,
            officeLabelsById: civicHistory.officeLabelsById
          })}
          <section class="detail__panel">
            <h3>Officeholding timeline</h3>
            {#if officeholdingRows.length === 0}
              <p>No officeholding history is available yet.</p>
            {:else}
              <div class="detail__table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Officeholding</th>
                      <th>Office</th>
                      <th>Status</th>
                      <th>Valid from</th>
                      <th>Valid through</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each officeholdingRows as row (row.officeholdingId)}
                      <tr>
                        <td><a href={row.officeholdingHref}>{row.officeholdingLabel}</a></td>
                        <td><a href={row.officeHref}>{row.officeLabel}</a></td>
                        <td>{row.holderStatus}</td>
                        <td>{row.validFrom}</td>
                        <td>{row.validThrough}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>

          {@const candidacyRows = buildPersonCandidacyRows(civicHistory.candidacies, {
            candidacyLabelsById: civicHistory.candidacyLabelsById,
            contestLabelsById: civicHistory.contestLabelsById
          })}
          <section class="detail__panel">
            <h3>Candidacies</h3>
            {#if candidacyRows.length === 0}
              <p>No candidacy history is available yet.</p>
            {:else}
              <div class="detail__table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Candidacy</th>
                      <th>Contest</th>
                      <th>Party</th>
                      <th>Status</th>
                      <th>Incumbent/challenge</th>
                      <th>Filing date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each candidacyRows as row (row.candidacyId)}
                      <tr>
                        <td><a href={row.candidacyHref}>{row.candidacyLabel}</a></td>
                        <td><a href={row.contestHref}>{row.contestLabel}</a></td>
                        <td>{row.party}</td>
                        <td>{row.status}</td>
                        <td>{row.incumbentChallenge}</td>
                        <td>{row.filingDate}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>
        {:catch}
          <section class="detail__panel">
            <h3>Officeholding timeline</h3>
            <p>Civic history is temporarily unavailable.</p>
          </section>
          <section class="detail__panel">
            <h3>Candidacies</h3>
            <p>Civic history is temporarily unavailable.</p>
          </section>
        {/await}
      {/if}
    {:else if sectionKey === "person-campaign-finance"}
      {#if data.entityType === "person" && personFinanceSections !== null}
        {#await personFinanceSections}
          <SkeletonPanel label="Campaign finance" lines={8} />
        {:then personFinanceSections}
          <section class="detail__panel">
            <h3>Campaign finance</h3>
            {#if personFinanceSections.length === 0}
              <p>No campaign-finance candidacies are linked yet.</p>
            {:else}
              {#each personFinanceSections as section (section.candidate.id)}
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
                    {@const linkedCommitteeRows = buildPersonLinkedCommitteeRows(summary)}
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
                      ariaLabel={`Finance chart for ${section.candidate.name}`}
                      series={summaryChartSeries}
                    />
                    <h4>Linked committees</h4>
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
                    <p>Candidate fundraising summary is temporarily unavailable.</p>
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
                  {#await Promise.all([section.ieSummary, section.ieTransactions])}
                    <SkeletonPanel label="Outside spending" lines={4} />
                  {:then [ieSummary, ieTransactions]}
                    {@const outsideSpending = buildPersonOutsideSpendingSection(ieSummary, ieTransactions)}
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
                    {/if}
                  {:catch}
                    <p>Outside-spending data is temporarily unavailable.</p>
                  {/await}
                </article>
              {/each}
            {/if}
          </section>
        {:catch}
          <section class="detail__panel">
            <h3>Campaign finance</h3>
            <p>Campaign-finance sections are temporarily unavailable.</p>
          </section>
        {/await}
      {/if}
    {:else if sectionKey === "technical-disclosure"}
      {#await Promise.all([data.matches, data.relationships])}
        <SkeletonPanel label="Entity internals" lines={6} />
      {:then [matches, relationships]}
        {@const technicalDisclosure = buildTechnicalDisclosureSection(matches, relationships.neighbors, data.detail.id)}
        {@const graphElements = buildGraphElements(
          data.entityType,
          data.detail.id,
          data.detail.canonical_name,
          relationships.neighbors
        )}
        <details class="detail__panel" aria-label="Entity internals">
          <summary>{technicalDisclosure.summary}</summary>
          <section class="detail__panel">
            <h3>Entity resolution matches</h3>
            {#if technicalDisclosure.matchRows.length === 0}
              <p>{technicalDisclosure.matchEmptyMessage}</p>
            {:else}
              <div class="detail__table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Counterpart entity</th>
                      <th>Decision</th>
                      <th>Confidence</th>
                      <th>Decided at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each technicalDisclosure.matchRows as row (row.counterpartEntityId + row.decidedAt)}
                      <tr>
                        <td>{row.counterpartEntityId}</td>
                        <td>{row.decision}</td>
                        <td>{row.confidence}</td>
                        <td>{row.decidedAt}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>

          <section class="detail__panel">
            <h3>Graph relationships</h3>
            {#key `${data.entityType}:${data.detail.id}`}
              <GraphViewer
                elements={graphElements}
                totalCount={relationships.total_count}
                returnedCount={relationships.neighbors.length}
                subjectName={data.detail.canonical_name}
                describedById={graphNeighborListId}
              />
            {/key}
            {#if technicalDisclosure.neighborRows.length === 0}
              <p id={graphNeighborListId}>{technicalDisclosure.neighborEmptyMessage}</p>
            {:else}
              <div class="detail__table-scroll" id={graphNeighborListId}>
                <table>
                  <thead>
                    <tr>
                      <th>Neighbor</th>
                      <th>Entity type</th>
                      <th>Relationship</th>
                      <th>Direction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each technicalDisclosure.neighborRows as row (row.entityType + row.title + row.relationshipType + row.direction)}
                      <tr>
                        <td>
                          {#if row.href}
                            <a href={row.href}>{row.title}</a>
                          {:else}
                            <span class="detail__metadata-only">{row.title}</span>
                          {/if}
                        </td>
                        <td>{row.entityType}</td>
                        <td>{row.relationshipType}</td>
                        <td>{row.direction}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>
        </details>
      {:catch}
        <details class="detail__panel" aria-label="Entity internals">
          <summary>Entity-resolution and graph internals</summary>
          <p>Entity internals are temporarily unavailable.</p>
        </details>
      {/await}
    {/if}
  {/each}
</section>
