<script lang="ts">
  import TrustSection from "$lib/detail-trust/TrustSection.svelte";
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
  import type {
    CandidacyDetailResponse,
    ContestDetailResponse,
    OfficeDetailResponse,
    OfficeholdingDetailResponse
  } from "$lib/civic-detail/contract";

  export let entityType: "office" | "contest" | "candidacy" | "officeholding";
  export let data:
    | OfficeDetailResponse
    | ContestDetailResponse
    | CandidacyDetailResponse
    | OfficeholdingDetailResponse;

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
      contestViewModel = buildContestDetailPresentation(data as ContestDetailResponse);
    } else if (entityType === "candidacy") {
      candidacyViewModel = buildCandidacyDetailPresentation(data as CandidacyDetailResponse);
    } else if (entityType === "officeholding") {
      officeholdingViewModel = buildOfficeholdingDetailPresentation(data as OfficeholdingDetailResponse);
    }
  }
</script>

<section class="card detail" aria-label={`${entityType} detail`}>
  {#if entityType === "office" && officeViewModel}
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
        <section class="detail__panel">
          <h3>Current officeholders</h3>
          {#if officeViewModel.officeholderRows.length === 0}
            <p>{officeViewModel.officeholderEmptyMessage}</p>
          {:else}
            <ul class="detail__list">
              {#each officeViewModel.officeholderRows as row (row.id)}
                <li>
                  {#if row.personHref}
                    <p><a href={row.personHref}>{row.personName}</a></p>
                  {:else}
                    <p>{row.personName}</p>
                  {/if}
                  <p>status: {row.holderStatus}</p>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {:else if sectionKey === "caveats"}
        {#if officeViewModel.incompleteDataWarning}
          <section class="detail__panel">
            <h3>Data coverage warning</h3>
            <p>{officeViewModel.incompleteDataWarning}</p>
          </section>
        {/if}
      {/if}
    {/each}
  {:else if entityType === "contest" && contestViewModel}
    <header class="detail__header">
      <h2>{contestViewModel.title}</h2>
      <p class="detail__type">contest</p>
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
          <h3>Candidacies</h3>
          {#if contestViewModel.candidacyRows.length === 0}
            <p>{contestViewModel.candidacyEmptyMessage}</p>
          {:else}
            <ul class="detail__list">
              {#each contestViewModel.candidacyRows as row (row.id)}
                <li>
                  {#if row.personHref}
                    <p><a href={row.personHref}>{row.personName}</a></p>
                  {:else}
                    <p>{row.personName}</p>
                  {/if}
                  <p>party: {row.party}</p>
                  <p>status: {row.status}</p>
                  <p>incumbent/challenger: {row.incumbentChallenge}</p>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {:else if sectionKey === "caveats"}
        {#if contestViewModel.candidateListWarning}
          <section class="detail__panel">
            <h3>Data coverage warning</h3>
            <p>{contestViewModel.candidateListWarning}</p>
          </section>
        {/if}
      {/if}
    {/each}
  {:else if entityType === "candidacy" && candidacyViewModel}
    <header class="detail__header">
      <h2>{candidacyViewModel.title}</h2>
      <p class="detail__type">candidacy</p>
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
      {:else if sectionKey === "caveats"}
        {#if candidacyViewModel.statusEmptyMessage}
          <section class="detail__panel">
            <h3>Data coverage warning</h3>
            <p>{candidacyViewModel.statusEmptyMessage}</p>
          </section>
        {/if}
      {/if}
    {/each}
  {:else if entityType === "officeholding" && officeholdingViewModel}
    <header class="detail__header">
      <h2>{officeholdingViewModel.title}</h2>
      <p class="detail__type">officeholding</p>
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
      {:else if sectionKey === "caveats"}
        {#if officeholdingViewModel.validPeriodEmptyMessage}
          <section class="detail__panel">
            <h3>Data coverage warning</h3>
            <p>{officeholdingViewModel.validPeriodEmptyMessage}</p>
          </section>
        {/if}
      {/if}
    {/each}
  {/if}
</section>
