<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
  import type {
    CampaignFinanceDetailRoutePresentation,
    CandidateDetailPresentation,
    CommitteeDetailPresentation
  } from "$lib/campaign-finance-detail/presentation";

  export let presentation: CampaignFinanceDetailRoutePresentation;
</script>

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
  {@const committeeViewModel = presentation.detail as CommitteeDetailPresentation}
  <section class="card detail" aria-label="Committee detail">
    <header class="detail__header">
      <h2>{committeeViewModel.canonicalName}</h2>
      <p class="detail__type">committee</p>
    </header>

    {#each committeeViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Core attributes</h3>
          <dl class="detail__rows">
            {#each committeeViewModel.factRows as row (row.label)}
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
        <TrustSection trustSection={committeeViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        {#if committeeViewModel.keyMetrics.length > 0}
          <section class="detail__panel">
            <h3>Key metrics</h3>
            <dl class="detail__rows">
              {#each committeeViewModel.keyMetrics as metric (metric.label)}
                <div class="detail__row">
                  <dt>{metric.label}</dt>
                  <dd>{metric.value}</dd>
                </div>
              {/each}
            </dl>
          </section>
        {/if}
      {:else if sectionKey === "records"}
        <section class="detail__panel" aria-label="Fundraising summary">
          <h3>Fundraising summary</h3>
          <dl class="detail__rows">
            <div class="detail__row">
              <dt>Total raised</dt>
              <dd>{committeeViewModel.fundraisingSummary.totalRaised}</dd>
            </div>
            <div class="detail__row">
              <dt>Total spent</dt>
              <dd>{committeeViewModel.fundraisingSummary.totalSpent}</dd>
            </div>
            <div class="detail__row">
              <dt>Net</dt>
              <dd>{committeeViewModel.fundraisingSummary.net}</dd>
            </div>
            <div class="detail__row">
              <dt>Transaction count</dt>
              <dd>{committeeViewModel.fundraisingSummary.transactionCount}</dd>
            </div>
            <div class="detail__row">
              <dt>Jurisdiction</dt>
              <dd>{committeeViewModel.fundraisingSummary.jurisdiction}</dd>
            </div>
            <div class="detail__row">
              <dt>Data through</dt>
              <dd>{committeeViewModel.fundraisingSummary.dataThrough}</dd>
            </div>
          </dl>
        </section>

        <section class="detail__panel">
          <h3>Filing-period breakdown</h3>
          {#if committeeViewModel.filingBreakdown.rows.length === 0}
            <p>{committeeViewModel.filingBreakdown.emptyMessage}</p>
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
                  {#each committeeViewModel.filingBreakdown.rows as row (row.filingId + row.amendmentIndicator)}
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

        <section class="detail__panel">
          <h3>Recent transactions</h3>
          {#if committeeViewModel.transactionRows.length === 0}
            <p>{committeeViewModel.transactionEmptyMessage}</p>
          {:else}
            <ul class="detail__list">
              {#each committeeViewModel.transactionRows as row (row.id)}
                <li>
                  <p>date: {row.date}</p>
                  <p>amount: {row.amount}</p>
                  <p>type: {row.transactionType}</p>
                  <p>contributor: {row.contributorName}</p>
                  {#if row.contributorPersonHref && row.contributorPersonLabel}
                    <p><a href={row.contributorPersonHref}>{row.contributorPersonLabel}</a></p>
                  {/if}
                  {#if row.contributorOrgHref && row.contributorOrgLabel}
                    <p><a href={row.contributorOrgHref}>{row.contributorOrgLabel}</a></p>
                  {/if}
                  {#if row.recipientCandidateHref && row.recipientCandidateLabel}
                    <p><a href={row.recipientCandidateHref}>{row.recipientCandidateLabel}</a></p>
                  {/if}
                  {#if row.recipientCommitteeHref && row.recipientCommitteeLabel}
                    <p><a href={row.recipientCommitteeHref}>{row.recipientCommitteeLabel}</a></p>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}
    {/each}
  </section>
{:else}
  {@const candidateViewModel = presentation.detail as CandidateDetailPresentation}
  <section class="card detail" aria-label="Candidate detail">
    <header class="detail__header">
      <h2>{candidateViewModel.canonicalName}</h2>
      <p class="detail__type">candidate</p>
    </header>

    {#each candidateViewModel.sectionOrder as sectionKey (sectionKey)}
      {#if sectionKey === "summary"}
        <section class="detail__panel">
          <h3>Core attributes</h3>
          <dl class="detail__rows">
            {#each candidateViewModel.factRows as row (row.label)}
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
        <TrustSection trustSection={candidateViewModel.trustSection} />
      {:else if sectionKey === "metrics"}
        {#if candidateViewModel.keyMetrics.length > 0}
          <section class="detail__panel">
            <h3>Key metrics</h3>
            <dl class="detail__rows">
              {#each candidateViewModel.keyMetrics as metric (metric.label)}
                <div class="detail__row">
                  <dt>{metric.label}</dt>
                  <dd>{metric.value}</dd>
                </div>
              {/each}
            </dl>
          </section>
        {/if}
      {:else if sectionKey === "outside-spending"}
        <section class="detail__panel">
          <h3>Outside Spending</h3>
          {#if candidateViewModel.outsideSpending.explanatoryBlock}
            <p>{candidateViewModel.outsideSpending.explanatoryBlock}</p>
          {/if}
          {#if candidateViewModel.outsideSpending.emptyMessage}
            <p>{candidateViewModel.outsideSpending.emptyMessage}</p>
          {:else}
            <h4>Support spending</h4>
            <dl class="detail__rows">
              <div class="detail__row">
                <dt>Total</dt>
                <dd>{candidateViewModel.outsideSpending.supportTotal}</dd>
              </div>
              <div class="detail__row">
                <dt>Expenditures</dt>
                <dd>{candidateViewModel.outsideSpending.supportCountLabel}</dd>
              </div>
            </dl>
            <h4>Oppose spending</h4>
            <dl class="detail__rows">
              <div class="detail__row">
                <dt>Total</dt>
                <dd>{candidateViewModel.outsideSpending.opposeTotal}</dd>
              </div>
              <div class="detail__row">
                <dt>Expenditures</dt>
                <dd>{candidateViewModel.outsideSpending.opposeCountLabel}</dd>
              </div>
            </dl>
            {#if candidateViewModel.outsideSpending.topSpenders.length > 0}
              <h4>Top spenders</h4>
              <ul class="detail__list">
                {#each candidateViewModel.outsideSpending.topSpenders as spender (spender.committeeHref)}
                  <li>
                    <a href={spender.committeeHref}>{spender.committeeName}</a>
                    - {spender.stance} - {spender.totalAmount} ({spender.transactionCountLabel})
                  </li>
                {/each}
              </ul>
            {/if}
            {#if candidateViewModel.outsideSpending.transactionRows.length > 0}
              <h4>Transactions</h4>
              <ul class="detail__list">
                {#each candidateViewModel.outsideSpending.transactionRows as row (row.date + row.spender + row.amount)}
                  <li>
                    <p>date: {row.date}</p>
                    <p>spender: <a href={row.spenderHref}>{row.spender}</a></p>
                    <p>dissemination date: {row.disseminationDate}</p>
                    <p>stance: {row.stance}</p>
                    <p>amount: {row.amount}</p>
                  </li>
                {/each}
              </ul>
            {/if}
          {/if}
        </section>
      {:else if sectionKey === "records"}
        <section class="detail__panel" aria-label="Fundraising summary">
          <h3>Fundraising summary</h3>
          <dl class="detail__rows">
            <div class="detail__row">
              <dt>Total raised</dt>
              <dd>{candidateViewModel.fundraisingSummary.totalRaised}</dd>
            </div>
            <div class="detail__row">
              <dt>Total spent</dt>
              <dd>{candidateViewModel.fundraisingSummary.totalSpent}</dd>
            </div>
            <div class="detail__row">
              <dt>Net</dt>
              <dd>{candidateViewModel.fundraisingSummary.net}</dd>
            </div>
            <div class="detail__row">
              <dt>Transaction count</dt>
              <dd>{candidateViewModel.fundraisingSummary.transactionCount}</dd>
            </div>
          </dl>
        </section>

        {#if candidateViewModel.committeeBreakdown.length > 0}
          <section class="detail__panel" aria-label="Committee breakdown">
            <h3>Committee breakdown</h3>
            {#each candidateViewModel.committeeBreakdown as committee (committee.committeeId)}
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
      {/if}
    {/each}
  </section>
{/if}
