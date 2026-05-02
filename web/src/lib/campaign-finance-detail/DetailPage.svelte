<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import Chart from "$lib/charts/Chart.svelte";
  import {
    buildCandidateCompletenessWarnings,
    buildCandidateDeferredCommitteeBreakdown,
    buildCandidateDeferredFundraisingSummary,
    buildCandidateDeferredKeyMetrics,
    buildCandidateDeferredOutsideSpending,
    buildCommitteeDeferredFilingBreakdown,
    buildCommitteeDeferredFundraisingSummary,
    buildCommitteeDeferredHighSignalSummary,
    buildCommitteeDeferredKeyMetrics,
    buildCommitteeDeferredTransactionRows,
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
        </section>
      {:else if sectionKey === "trust"}
        <TrustSection trustSection={shellViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        {#await presentation.summary}
          <SkeletonPanel label="Key metrics" lines={3} />
        {:then summary}
          {@const keyMetrics = buildCommitteeDeferredKeyMetrics(summary)}
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
            </section>
          {/if}
        {:catch}
          <section class="detail__panel" data-testid="key-metrics">
            <h3>Key metrics</h3>
            <p>Committee metrics are temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "records"}
        {#await presentation.summary}
          <SkeletonPanel label="Fundraising summary" lines={6} />
        {:then summary}
          {@const fundraisingSummary = buildCommitteeDeferredFundraisingSummary(summary)}
          {@const highSignalSummary = buildCommitteeDeferredHighSignalSummary(summary, { committee_id: summary.committee_id, committee_name: summary.committee_name, filings: [] })}
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

          <section class="detail__panel">
            <h3>Cash-on-hand trend</h3>
            {#await presentation.filingBreakdown}
              <SkeletonPanel label="Cash-on-hand trend" lines={3} />
            {:then filingBreakdown}
              {@const trendSummary = buildCommitteeDeferredHighSignalSummary(summary, filingBreakdown)}
              {#if trendSummary.cashOnHandTrendSeries.length === 0}
                <p>Cash-on-hand trend is not available from reported filing periods.</p>
              {:else}
                <Chart
                  kind="line"
                  title="Cash-on-hand trend"
                  ariaLabel="Committee cash-on-hand trend"
                  series={trendSummary.cashOnHandTrendSeries}
                />
              {/if}
            {:catch}
              <p>Cash-on-hand trend is not available from reported filing periods.</p>
            {/await}
          </section>

          {#await presentation.filingBreakdown}
            <SkeletonPanel label="Filing-period breakdown" lines={5} />
          {:then filingBreakdown}
            {@const filingBreakdownPresentation = buildCommitteeDeferredFilingBreakdown(filingBreakdown)}
            <section class="detail__panel">
              <h3>Filing-period breakdown</h3>
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
                        <th>Raised</th>
                        <th>Spent</th>
                        <th>Net</th>
                        <th>Transactions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each filingBreakdownPresentation.rows as row (row.filingId + row.amendmentIndicator)}
                        <tr>
                          <td>{row.filingName} ({row.filingFecId})</td>
                          <td>{row.coveragePeriod}</td>
                          <td>{row.receiptDate}</td>
                          <td>{row.totalRaised}</td>
                          <td>{row.totalSpent}</td>
                          <td>{row.net}</td>
                          <td>{row.transactionCount}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            </section>
          {:catch}
            <section class="detail__panel">
              <h3>Filing-period breakdown</h3>
              <p>Filing-period fundraising data is temporarily unavailable.</p>
            </section>
          {/await}
        {:catch}
          <section class="detail__panel" aria-label="Fundraising summary">
            <h3>Fundraising summary</h3>
            <p>Committee fundraising summary is temporarily unavailable.</p>
          </section>
        {/await}

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
          <SkeletonPanel label="Key metrics" lines={3} />
        {:then summary}
          {@const completenessWarnings = buildCandidateCompletenessWarnings(
            summary,
            shellViewModel.l10Reference
          )}
          {@const keyMetrics = buildCandidateDeferredKeyMetrics(summary)}
          {#each completenessWarnings as warning (warning.message)}
            {@render caveatBanner(warning.message, warning.methodologyHref)}
          {/each}
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
            </section>
          {/if}
        {:catch}
          <section class="detail__panel" data-testid="key-metrics">
            <h3>Key metrics</h3>
            <p>Candidate metrics are temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "outside-spending"}
        {#await presentation.ieSummary}
          <SkeletonPanel label="Outside spending" lines={5} />
        {:then ieSummary}
          {#await presentation.ieTransactions}
            <SkeletonPanel label="Outside spending" lines={5} />
          {:then ieTransactions}
            {@const outsideSpending = buildCandidateDeferredOutsideSpending(ieSummary, ieTransactions)}
            <section class="detail__panel">
              <h3>Outside Spending</h3>
              {#if outsideSpending.explanatoryBlock}
                <p>{outsideSpending.explanatoryBlock}</p>
              {/if}
              {#if outsideSpending.emptyMessage}
                <p>{outsideSpending.emptyMessage}</p>
              {:else}
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
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}
              {/if}
            </section>
          {:catch}
            <section class="detail__panel">
              <h3>Outside Spending</h3>
              <p>Outside-spending transactions are temporarily unavailable.</p>
            </section>
          {/await}
        {:catch}
          <section class="detail__panel">
            <h3>Outside Spending</h3>
            <p>Outside-spending summary data is temporarily unavailable.</p>
          </section>
        {/await}
      {:else if sectionKey === "records"}
        {#await presentation.summary}
          <SkeletonPanel label="Fundraising summary" lines={4} />
        {:then summary}
          {@const fundraisingSummary = buildCandidateDeferredFundraisingSummary(summary)}
          {@const committeeBreakdown = buildCandidateDeferredCommitteeBreakdown(summary)}
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
            </dl>
          </section>

          {#if committeeBreakdown.length > 0}
            <section class="detail__panel" aria-label="Committee breakdown">
              <h3>Committee breakdown</h3>
              {#each committeeBreakdown as committee (committee.committeeId)}
                <div class="detail__committee-card">
                  <h4><a href={committee.committeeHref}>{committee.committeeName}</a></h4>
                  <dl class="detail__rows">
                    <div class="detail__row">
                      <dt>Total raised</dt>
                      <dd>{committee.totalRaised}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Total spent</dt>
                      <dd>{committee.totalSpent}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Net</dt>
                      <dd>{committee.net}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Transaction count</dt>
                      <dd>{committee.transactionCount}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Jurisdiction</dt>
                      <dd>{committee.jurisdiction}</dd>
                    </div>
                    <div class="detail__row">
                      <dt>Data through</dt>
                      <dd>{committee.dataThrough}</dd>
                    </div>
                  </dl>
                </div>
              {/each}
            </section>
          {/if}
        {:catch}
          <section class="detail__panel" aria-label="Fundraising summary">
            <h3>Fundraising summary</h3>
            <p>Candidate fundraising summary is temporarily unavailable.</p>
          </section>
        {/await}
      {/if}
    {/each}
  </section>
{/if}
