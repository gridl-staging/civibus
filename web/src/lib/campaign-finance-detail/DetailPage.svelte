<script lang="ts">
  import { page } from "$app/stores";
  import { buildCommitteeFilingPageHref } from "$lib/campaign-finance-detail/contract";
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import CashOnHandTrendChart from "$lib/charts/CashOnHandTrendChart.svelte";
  import FactRows from "$lib/campaign-finance-detail/FactRows.svelte";
  import * as candidateMoneyPresentation from "$lib/campaign-finance-detail/candidate_money_presentation";
  import {
    buildCandidateCompletenessWarnings,
    buildCommitteeCycleSummaryRows,
    buildCommitteeDeferredFundraisingSummary,
    buildCommitteeDeferredHighSignalSummary,
    buildCommitteeDeferredKeyMetrics,
    buildCommitteeDeferredOutsideSpending,
    buildCommitteeDeferredTransactionRows,
    buildPaginatedCommitteeFilingBreakdown,
    COMMITTEE_FILINGS_PAGE_SIZE,
    getCampaignFinanceEmptyMessage,
    type CampaignFinanceDetailRoutePresentation
  } from "$lib/campaign-finance-detail/presentation";
  export let presentation: CampaignFinanceDetailRoutePresentation;
</script>

{#snippet caveatBanner(message: string, methodologyHref: string)}
  <section class="detail__panel caveat-banner" role="note" aria-label="Data coverage warning">
    <h3>Data coverage warning</h3>
    <p>{message} <a href={methodologyHref}>See methodology.</a></p>
  </section>
{/snippet}

{#snippet coverageMessage(message: string, methodologyHref: string | null)}
  <p>
    {message}
    {#if methodologyHref}
      <a href={methodologyHref}>Learn how Civibus reports coverage.</a>
    {/if}
  </p>
{/snippet}

{#if presentation.routeKind === "slug-collision"}
  <section class="card detail" aria-label={`${presentation.entityType} slug collision`}>
    <header class="detail__header">
      <h2>{presentation.heading}</h2>
      <p class="detail__type">{presentation.entityType}</p>
    </header>

    <section class="detail__panel">
      <h3>Choose a record</h3>
      <p>Multiple records share this slug. Select the intended detail page.</p>
      <ul class="detail__list" aria-label={presentation.chooserLabel}>
        {#each presentation.matches as match (match.id)}
          <li>
            <p><a href={match.href}>{match.name}</a></p>
            <p>ID: {match.id}</p>
          </li>
        {/each}
      </ul>
    </section>
  </section>
{:else if presentation.entityType === "committee"}
  {@const shellViewModel = presentation.shell}
  <section class="card detail" aria-label="Committee detail">
    <header class="detail__header">
      <h2>{shellViewModel.canonicalName}</h2>
      <p class="detail__type">committee</p>
    </header>

    {#each shellViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Core attributes</h3>
          <dl class="detail__rows">
            {#each shellViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>
                  {#if row.href}
                    <a href={row.href}>{row.value}</a>
                  {:else}
                    {row.value}
                  {/if}
                </dd>
              </div>
            {/each}
          </dl>
          {#if shellViewModel.linkedCandidates.length > 0}
            <div data-testid="committee-linked-candidates">
              <h4>Linked candidates</h4>
              <ul class="detail__list" aria-label="Linked candidates">
                {#each shellViewModel.linkedCandidates as candidate (candidate.candidateId)}
                  <li>
                    <a href={candidate.href}>{candidate.name}</a>
                    <span> — {candidate.context}</span>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={shellViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        {#await presentation.summary}
          <SkeletonPanel label="Key metrics" lines={3} />
        {:then summary}
          {@const keyMetrics = buildCommitteeDeferredKeyMetrics(summary)}
          {@const fundraisingSummaryForMetrics = buildCommitteeDeferredFundraisingSummary(summary)}
          {#if keyMetrics.length > 0}
            <section class="detail__panel" data-testid="key-metrics">
              <h3>Key metrics</h3>
              <dl class="detail__rows">
                {#each keyMetrics as metric (metric.label)}
                  <div class="detail__row">
                    <dt>{metric.label}</dt>
                    <dd>{metric.value}</dd>
                  </div>
                {/each}
              </dl>
              <p class="detail__metric-source">{fundraisingSummaryForMetrics.summarySourceLabel}</p>
              <p class="detail__metric-coverage-note">{fundraisingSummaryForMetrics.itemizedCoverageNote}</p>
            </section>
          {/if}
        {:catch}
          <section class="detail__panel" data-testid="key-metrics">
            <h3>Key metrics</h3>
            <p>Committee metrics are temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "outside-spending"}
        {#await presentation.independentExpendituresMade}
          <SkeletonPanel label="Outside spending" lines={5} />
        {:then independentExpendituresMade}
          {@const outsideSpending = buildCommitteeDeferredOutsideSpending(independentExpendituresMade)}
          <section class="detail__panel" data-testid="committee-outside-spending">
            <h3>Outside Spending</h3>
            {#if outsideSpending.emptyMessage}
              <p>{outsideSpending.emptyMessage}</p>
            {:else}
              <dl class="detail__rows">
                <div class="detail__row">
                  <dt>Support spending</dt>
                  <dd>{outsideSpending.supportTotal}</dd>
                </div>
                <div class="detail__row">
                  <dt>Oppose spending</dt>
                  <dd>{outsideSpending.opposeTotal}</dd>
                </div>
                <div class="detail__row">
                  <dt>Independent expenditures</dt>
                  <dd>{outsideSpending.ieCountLabel}</dd>
                </div>
              </dl>
              {#if outsideSpending.targetRows.length > 0}
                <h4>Target candidates</h4>
                <div class="detail__table-scroll" data-testid="committee-outside-spending-targets">
                  <table>
                    <thead>
                      <tr>
                        <th>Target</th>
                        <th>Context</th>
                        <th>Support</th>
                        <th>Oppose</th>
                        <th>Expenditures</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each outsideSpending.targetRows as target (target.rowKey)}
                        <tr>
                          <td>
                            {#if target.targetHref}
                              <a href={target.targetHref}>{target.candidateName}</a>
                            {:else}
                              {target.candidateName}
                            {/if}
                          </td>
                          <td>{target.context}</td>
                          <td>{target.supportTotal}</td>
                          <td>{target.opposeTotal}</td>
                          <td>{target.transactionCountLabel}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
              {#if outsideSpending.sourceRows.length > 0}
                <h4>Source filings</h4>
                <div class="detail__table-scroll" data-testid="committee-outside-spending-sources">
                  <table>
                    <thead>
                      <tr>
                        <th>Target</th>
                        <th>Source</th>
                        <th>Record</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each outsideSpending.sourceRows as source (source.rowKey)}
                        <tr>
                          <td>{source.candidateName}</td>
                          <td>
                            {#if source.href}
                              <a href={source.href}>{source.sourceName}</a>
                            {:else}
                              {source.sourceName}
                            {/if}
                          </td>
                          <td>{source.sourceRecordKey}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            {/if}
            {#if outsideSpending.outlierNote}
              <p role="note">{outsideSpending.outlierNote}</p>
            {/if}
          </section>
        {:catch}
          <section class="detail__panel" data-testid="committee-outside-spending">
            <h3>Outside Spending</h3>
            <p>Committee independent-expenditure data is temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "records"}
        {#await presentation.summary}
          <SkeletonPanel label="Fundraising summary" lines={6} />
        {:then summary}
          {@const fundraisingSummary = buildCommitteeDeferredFundraisingSummary(summary)}
          {@const filingBreakdownForDerivedPanels = presentation.filingBreakdown ?? {
            committee_id: summary.committee_id,
            committee_name: summary.committee_name,
            filings: []
          }}
          {@const highSignalSummary = buildCommitteeDeferredHighSignalSummary(summary, filingBreakdownForDerivedPanels)}
          <section class="detail__panel" aria-label="Fundraising summary">
            <h3>Fundraising summary</h3>
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
              <div class="detail__row">
                <dt>Jurisdiction</dt>
                <dd>{fundraisingSummary.jurisdiction}</dd>
              </div>
              <div class="detail__row">
                <dt>Data through</dt>
                <dd>{fundraisingSummary.dataThrough}</dd>
              </div>
            </dl>
          </section>

          <section class="detail__panel">
            <h3>Receipt split</h3>
            <dl class="detail__rows">
              {#each highSignalSummary.receiptSplit as row (row.label)}
                <div class="detail__row">
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </div>
              {/each}
            </dl>
          </section>

          <section class="detail__panel">
            <h3>Top donors</h3>
            {#if highSignalSummary.topDonors.length === 0}
              <p>No donor rankings available.</p>
            {:else}
              <div class="detail__table-scroll" data-testid="top-donors-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Donor</th>
                      <th>Total</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each highSignalSummary.topDonors as donor (donor.name)}
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
          </section>

          <section class="detail__panel">
            <h3>Top vendors</h3>
            {#if highSignalSummary.topVendors.length === 0}
              <p>No vendor rankings available.</p>
            {:else}
              <div class="detail__table-scroll" data-testid="top-vendors-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Vendor</th>
                      <th>Total</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each highSignalSummary.topVendors as vendor (vendor.name)}
                      <tr>
                        <td>{vendor.name}</td>
                        <td>{vendor.totalAmount}</td>
                        <td>{vendor.transactionCountLabel}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>

          <section class="detail__panel">
            <h3>Spend categories</h3>
            {#if highSignalSummary.spendCategories.length > 0}
              <div class="detail__table-scroll" data-testid="spend-categories-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Total</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each highSignalSummary.spendCategories as category (category.category)}
                      <tr>
                        <td>{category.category}</td>
                        <td>{category.totalAmount}</td>
                        <td>{category.transactionCountLabel}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <p>{highSignalSummary.spendCategoriesEmptyMessage ?? "No categorized expenditures available."}</p>
            {/if}
          </section>

          {@const cycleSummaryRows = buildCommitteeCycleSummaryRows(summary)}
          <section class="detail__panel">
            <h3>Per-cycle history</h3>
            {#if cycleSummaryRows.length === 0}
              <p>No cycle-level FEC totals loaded for this committee yet.</p>
            {:else}
              <div class="detail__table-scroll" data-testid="committee-cycle-summaries-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Cycle</th>
                      <th>Coverage</th>
                      <th>Total receipts</th>
                      <th>Total disbursements</th>
                      <th>Cash on hand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each cycleSummaryRows as cycle (cycle.cycle)}
                      <tr>
                        <td>{cycle.cycleLabel}</td>
                        <td>{cycle.coveragePeriod}</td>
                        <td>{cycle.totalReceipts}</td>
                        <td>{cycle.totalDisbursements}</td>
                        <td>{cycle.cashOnHand}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </section>

          {@const trendFigure = buildCommitteeDeferredHighSignalSummary(
            summary,
            filingBreakdownForDerivedPanels
          ).cashOnHandTrend}
          <section class="detail__panel">
            <h3>Cash-on-hand trend</h3>
            <CashOnHandTrendChart
              testId="committee-cash-on-hand-trend"
              cycle={trendFigure.cycle}
              coverageThrough={trendFigure.coverageThrough}
              sources={trendFigure.sources}
              points={trendFigure.points}
            />
          </section>
        {:catch}
          <section class="detail__panel" aria-label="Fundraising summary">
            <h3>Fundraising summary</h3>
            <p>Committee fundraising summary is temporarily unavailable.</p>
          </section>
        {/await}

        <section class="detail__panel">
          <h3>Filing-period breakdown</h3>
          {#if presentation.filingBreakdown === null}
            <p>Committee filing-period data is temporarily unavailable.</p>
          {:else}
            {@const filingBreakdownPresentation = buildPaginatedCommitteeFilingBreakdown(
              presentation.filingBreakdown,
              $page.url.searchParams.get("filings_offset")
            )}
            {#if filingBreakdownPresentation.label}
              <p data-testid="filing-breakdown-pagination-label">{filingBreakdownPresentation.label}</p>
            {/if}
            {#if filingBreakdownPresentation.rows.length === 0}
              <p>{filingBreakdownPresentation.emptyMessage}</p>
            {:else}
              <div class="detail__table-scroll" data-testid="filing-breakdown-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Filing</th>
                      <th>Coverage</th>
                      <th>Received</th>
                      <th>Total receipts</th>
                      <th>Total disbursements</th>
                      <th>Cash on hand</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each filingBreakdownPresentation.rows as row (row.filingId + row.amendmentIndicator)}
                      <tr>
                        <td>{row.filingName} ({row.filingFecId})</td>
                        <td>{row.coveragePeriod}</td>
                        <td>{row.receiptDate}</td>
                        <td>{row.totalReceipts}</td>
                        <td>{row.totalDisbursements}</td>
                        <td>{row.cashOnHand}</td>
                        <td>{row.transactionCount}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              <nav class="detail__pagination" aria-label="Filing-period breakdown pagination">
                {#if filingBreakdownPresentation.pagination.hasPrevious}
                  <a
                    data-testid="filing-breakdown-prev"
                    href={buildCommitteeFilingPageHref(
                      $page.url,
                      filingBreakdownPresentation.normalizedOffset - COMMITTEE_FILINGS_PAGE_SIZE
                    )}
                  >Previous</a>
                {/if}
                {#if filingBreakdownPresentation.pagination.hasNext}
                  <a
                    data-testid="filing-breakdown-next"
                    href={buildCommitteeFilingPageHref(
                      $page.url,
                      filingBreakdownPresentation.normalizedOffset + COMMITTEE_FILINGS_PAGE_SIZE
                    )}
                  >Next</a>
                {/if}
              </nav>
            {/if}
          {/if}
        </section>

        {#await presentation.transactions}
          <SkeletonPanel label="Recent transactions" lines={5} />
        {:then transactions}
          {@const transactionRows = buildCommitteeDeferredTransactionRows(
            transactions,
            shellViewModel.committeeRouteRef
          )}
          <section class="detail__panel">
            <h3>Recent transactions</h3>
            {#if transactionRows.length === 0}
              <p>{getCampaignFinanceEmptyMessage()}</p>
            {:else}
              <div class="detail__table-scroll" data-testid="committee-transactions-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Amount</th>
                      <th>Type</th>
                      <th>Stance</th>
                      <th>Dissemination Date</th>
                      <th>Aggregate Amount</th>
                      <th>Contributor</th>
                      <th>Recipient</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each transactionRows as row (row.id)}
                      <tr>
                        <td>{row.date}</td>
                        <td>{row.amount}</td>
                        <td>{row.transactionType}</td>
                        <td>{row.ieStance}</td>
                        <td>{row.disseminationDate}</td>
                        <td>{row.aggregateAmount}</td>
                        <td>
                          {row.contributorName}
                          {#if row.contributorPersonHref && row.contributorPersonLabel}
                            <a href={row.contributorPersonHref}>{row.contributorPersonLabel}</a>
                          {/if}
                          {#if row.contributorOrgHref && row.contributorOrgLabel}
                            <a href={row.contributorOrgHref}>{row.contributorOrgLabel}</a>
                          {/if}
                        </td>
                        <td>
                          {#if row.recipientCandidateHref && row.recipientCandidateLabel}
                            <a href={row.recipientCandidateHref}>{row.recipientCandidateLabel}</a>
                          {/if}
                          {#if row.recipientCommitteeHref && row.recipientCommitteeLabel}
                            <a href={row.recipientCommitteeHref}>{row.recipientCommitteeLabel}</a>
                          {/if}
                          {#if !row.recipientCandidateHref && !row.recipientCommitteeHref}
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
        {:catch}
          <section class="detail__panel">
            <h3>Recent transactions</h3>
            <p>Recent committee transactions are temporarily unavailable.</p>
          </section>
        {/await}
      {/if}
    {/each}
  </section>
{:else}
  {@const shellViewModel = presentation.shell}
  <section class="card detail" aria-label="Candidate detail">
    <header class="detail__header">
      <h2>{shellViewModel.canonicalName}</h2>
      <p class="detail__type">candidate</p>
      {#if shellViewModel.identityQualifier}
        <p class="detail__qualifier">{shellViewModel.identityQualifier}</p>
      {/if}
    </header>

    {#each shellViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Core attributes</h3>
          <dl class="detail__rows">
            {#each shellViewModel.factRows as row (row.label)}
              <div class="detail__row">
                <dt>{row.label}</dt>
                <dd>
                  {#if row.href}
                    <a href={row.href}>{row.value}</a>
                  {:else}
                    {row.value}
                  {/if}
                </dd>
              </div>
            {/each}
          </dl>
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={shellViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        {#await presentation.summary}
          <SkeletonPanel label="Key financials" lines={3} />
        {:then summary}
          {@const fundraisingRegions = candidateMoneyPresentation.buildCandidateFundraisingRegionViewModels(summary)}
          {#if summary}
            {@const completenessWarnings = buildCandidateCompletenessWarnings(
              summary,
              shellViewModel.l10Reference
            )}
            {#each completenessWarnings as warning (warning.message)}
              {@render caveatBanner(warning.message, warning.methodologyHref)}
            {/each}
          {/if}
          <section class="detail__panel" data-testid="key-metrics">
            <h3>Key financials</h3>
            {#if fundraisingRegions.keyFinancials.message}
              {@render coverageMessage(
                fundraisingRegions.keyFinancials.message,
                fundraisingRegions.keyFinancials.methodologyHref
              )}
            {/if}
            {#if fundraisingRegions.keyFinancials.metrics.length > 0}
              <dl class="detail__rows">
                {#each fundraisingRegions.keyFinancials.metrics as metric (metric.label)}
                  <div class="detail__row">
                    <dt>{metric.label}</dt>
                    <dd>{metric.value}</dd>
                  </div>
                {/each}
              </dl>
            {/if}
          </section>
        {:catch}
          <section class="detail__panel" data-testid="key-metrics">
            <h3>Key financials</h3>
            <p>Candidate financial totals are temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "outside-spending"}
        {#await presentation.ieSummary}
          <SkeletonPanel label="Outside spending" lines={5} />
        {:then ieSummary}
          {#await presentation.ieTransactions}
            <SkeletonPanel label="Outside spending" lines={5} />
          {:then ieTransactions}
            {@const outsideSpendingRegion = candidateMoneyPresentation.buildCandidateOutsideSpendingRegionViewModel(ieSummary, ieTransactions)}
            {@const outsideSpending = outsideSpendingRegion.presentation}
            <section class="detail__panel" data-testid="candidate-outside-spending">
              <h3>Outside spending</h3>
              {#if outsideSpendingRegion.message}
                {@render coverageMessage(
                  outsideSpendingRegion.message,
                  outsideSpendingRegion.methodologyHref
                )}
              {/if}
              {#if outsideSpending?.explanatoryBlock}
                <p>{outsideSpending.explanatoryBlock}</p>
              {/if}
              {#if outsideSpending?.emptyMessage}
                <p>{outsideSpending.emptyMessage}</p>
              {:else if outsideSpending}
                <h4>Support spending</h4>
                <dl class="detail__rows">
                  <div class="detail__row">
                    <dt>Total</dt>
                    <dd>{outsideSpending.supportTotal}</dd>
                  </div>
                  <div class="detail__row">
                    <dt>Expenditures</dt>
                    <dd>{outsideSpending.supportCountLabel}</dd>
                  </div>
                </dl>
                <h4>Oppose spending</h4>
                <dl class="detail__rows">
                  <div class="detail__row">
                    <dt>Total</dt>
                    <dd>{outsideSpending.opposeTotal}</dd>
                  </div>
                  <div class="detail__row">
                    <dt>Expenditures</dt>
                    <dd>{outsideSpending.opposeCountLabel}</dd>
                  </div>
                </dl>
                {#if outsideSpending.topSpenders.length > 0}
                  <h4>Top spenders</h4>
                  <div class="detail__table-scroll" data-testid="top-spenders-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Committee</th>
                          <th>Stance</th>
                          <th>Total</th>
                          <th>Transactions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {#each outsideSpending.topSpenders as spender (spender.committeeHref + spender.stance)}
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
                {#if outsideSpending.transactionRows.length > 0}
                  <h4>Transactions</h4>
                  <div class="detail__table-scroll" data-testid="outside-spending-transactions-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Spender</th>
                          <th>Stance</th>
                          <th>Amount</th>
                          <th>Dissemination Date</th>
                          <th>Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {#each outsideSpending.transactionRows as row (row.date + row.spender + row.amount)}
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
                                —
                              {/if}
                            </td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}
              {/if}
            </section>
          {:catch}
            <!-- Jul15 production-shape guard: transport failure is not the same state as loaded zero. -->
            <section class="detail__panel" data-testid="candidate-outside-spending">
              <h3>Outside spending</h3>
              <p>Outside-spending data is temporarily unavailable.</p>
            </section>
          {/await}
        {:catch}
          <!-- Jul15 production-shape guard: transport failure is not the same state as loaded zero. -->
          <section class="detail__panel" data-testid="candidate-outside-spending">
            <h3>Outside spending</h3>
            <p>Outside-spending data is temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "records"}
        {#await presentation.summary}
          <SkeletonPanel label="Fundraising summary" lines={4} />
        {:then summary}
          {@const fundraisingRegions = candidateMoneyPresentation.buildCandidateFundraisingRegionViewModels(summary)}
          {@const fundraisingSummary = fundraisingRegions.fundraisingSummary.summary}
          {@const committeeBreakdown = fundraisingRegions.committeeBreakdown.rows}
          <section class="detail__panel" aria-label="Fundraising summary" data-testid="candidate-fundraising-summary">
            <h3>Fundraising summary</h3>
            {#if fundraisingRegions.fundraisingSummary.message}
              {@render coverageMessage(
                fundraisingRegions.fundraisingSummary.message,
                fundraisingRegions.fundraisingSummary.methodologyHref
              )}
            {/if}
            {#if fundraisingSummary}
              <FactRows rows={fundraisingSummary.factRows} />
            {/if}
          </section>

          <section class="detail__panel" aria-label="Committee breakdown" data-testid="candidate-committee-breakdown">
            <h3>Committee breakdown</h3>
            {#if fundraisingRegions.committeeBreakdown.message}
              {@render coverageMessage(
                fundraisingRegions.committeeBreakdown.message,
                fundraisingRegions.committeeBreakdown.methodologyHref
              )}
            {/if}
            {#if committeeBreakdown.length > 0}
              {#each committeeBreakdown as committee (committee.committeeId)}
                <div class="detail__committee-card">
                  <h4><a href={committee.committeeHref}>{committee.committeeName}</a></h4>
                  <FactRows rows={committee.factRows} />
                </div>
              {/each}
            {/if}
          </section>
        {:catch}
          <section class="detail__panel" aria-label="Fundraising summary" data-testid="candidate-fundraising-summary">
            <h3>Fundraising summary</h3>
            <p>Candidate fundraising summary is temporarily unavailable.</p>
          </section>
          <section class="detail__panel" aria-label="Committee breakdown" data-testid="candidate-committee-breakdown">
            <h3>Committee breakdown</h3>
            <p>Committee breakdown is temporarily unavailable.</p>
          </section>
        {/await}
      {/if}
    {/each}
  </section>
{/if}
