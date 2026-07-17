<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { navigating, page } from "$app/stores";
  import Breadcrumb from "$lib/breadcrumb/Breadcrumb.svelte";
  import ComparisonBar from "$lib/charts/ComparisonBar.svelte";
  import GeographyShareChart from "$lib/charts/GeographyShareChart.svelte";
  import HorizontalBarChart from "$lib/charts/HorizontalBarChart.svelte";
  import MonthlyContributionsChart from "$lib/charts/MonthlyContributionsChart.svelte";
  import OutsideSpendingChart from "$lib/charts/OutsideSpendingChart.svelte";
  import SkeletonPanel from "$lib/loading/SkeletonPanel.svelte";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { getTrustedPublicOrigin } from "$lib/seo/defaults";
  import { buildSeoHeadModel, type SeoHeadModel } from "$lib/seo/head";
  import { buildCompareUrl, type CompareNotice } from "./people-query";
  import {
    buildComparePresentation,
    type CompareMetricRow,
    type ComparePresentation
  } from "./presentation";
  import type { ActionData, PageData } from "./$types";

  export let data: PageData;
  export let form: ActionData | null = null;

  const NOTICE_COPY: Record<CompareNotice, string> = {
    "max-4": "Only the first four officeholders can be compared at once.",
    "unknown-people-dropped": "Some requested officeholders could not be found and were removed."
  };
  const COMPARE_METADATA = {
    title: "Compare Officeholders | Civibus",
    description: "Compare federal officeholder campaign-finance totals and outside spending."
  };
  const FEC_SCHEDULE_E_SOURCE = [
    {
      label: "FEC Schedule E independent expenditures",
      href: "https://www.fec.gov/data/independent-expenditures/"
    }
  ];

  $: selectedPersonIds = data.columns.map((column) => column.personId);
  $: columnOutcomes = Promise.allSettled(data.columns.map(({ money }) => money));
  $: compareCanonicalHref = data.canonicalComparison?.href ?? "/compare";
  $: headModel = buildCompareHeadModel(compareCanonicalHref, $page.url, env.PUBLIC_ORIGIN);
  $: addDisabled = selectedPersonIds.length >= 4;
  $: addSearchActionHref = buildAddSearchAction(selectedPersonIds);
  $: compareNavigationPending = $navigating?.to?.url.pathname === "/compare";
  $: breadcrumbCrumbs = [{ label: "Home", href: "/" }, { label: "Compare" }];

  function buildCompareHeadModel(
    canonicalHref: string,
    pageUrl: URL,
    publicOrigin: string | undefined
  ): SeoHeadModel {
    const baseModel = buildSeoHeadModel({
      metadata: COMPARE_METADATA,
      ogType: "website",
      pageUrl: new URL(canonicalHref, pageUrl),
      publicOrigin
    });
    const canonicalUrl = buildAbsoluteCompareCanonical(canonicalHref, publicOrigin);

    return {
      ...baseModel,
      robots: "noindex",
      canonicalUrl,
      openGraph: {
        ...baseModel.openGraph,
        url: canonicalUrl
      }
    };
  }

  function buildAbsoluteCompareCanonical(
    href: string,
    publicOrigin: string | undefined
  ): string | null {
    const trustedOrigin = getTrustedPublicOrigin(publicOrigin);
    if (trustedOrigin === null) {
      return null;
    }
    return new URL(href, new URL(trustedOrigin)).href;
  }

  function removePersonHref(personId: string): string {
    return buildCompareUrl(selectedPersonIds.filter((id) => id !== personId));
  }

  function addPersonHref(personId: string): string {
    return buildCompareUrl([...selectedPersonIds, personId]);
  }

  function buildAddSearchAction(personIds: string[]): string {
    const compareUrl = buildCompareUrl(personIds);
    return `${compareUrl}${compareUrl.includes("?") ? "&" : "?"}/addSearch`;
  }

  function barEntities(row: CompareMetricRow, presentation: ComparePresentation) {
    return row.cells.map((cell, index) => ({
      id: cell.personId,
      label: presentation.columns[index].name,
      href: presentation.columns[index].href,
      value: cell.value,
      valueLabel: cell.label
    }));
  }

  function firstCoveredMonth(months: string[]): string {
    return months[0] ?? "not available";
  }
</script>

{#snippet comparisonLoadingColumns(label: string)}
  <section class="compare__columns" aria-label={label}>
    {#each data.columns as column (column.personId)}
      <article class="compare__column" aria-label={`Compare column for ${column.person.detail.canonical_name}`}>
        <h3>{column.person.detail.canonical_name}</h3>
        <SkeletonPanel label="Campaign finance column loading" lines={5} />
      </article>
    {/each}
  </section>
{/snippet}

<SeoHead {headModel} />
<Breadcrumb crumbs={breadcrumbCrumbs} />

<section class="compare" aria-label="Officeholder comparison">
  <header class="compare__header">
    <div>
      <h2>Compare officeholders</h2>
      <p>{COMPARE_METADATA.description}</p>
    </div>
    {#if data.prompt !== null}
      <p>Choose at least two officeholders to compare campaign finance.</p>
    {/if}
  </header>

  {#if data.notices.length > 0}
    <ul class="compare__notices" aria-label="Comparison notices">
      {#each data.notices as notice (notice)}
        <li>{NOTICE_COPY[notice]}</li>
      {/each}
    </ul>
  {/if}

  <section class="compare__selection" aria-label="Selected officeholders">
    <div class="compare__chips">
      {#each data.columns as column (column.personId)}
        <span class="compare__chip">
          <a href={`/person/${encodeURIComponent(column.personId)}`}>{column.person.detail.canonical_name}</a>
          <a href={removePersonHref(column.personId)} aria-label={`Remove ${column.person.detail.canonical_name}`}>
            Remove
          </a>
        </span>
      {/each}
    </div>

    <form method="POST" action={addSearchActionHref} class="compare__search">
      <label for="compare-search">Add officeholder</label>
      <input
        id="compare-search"
        name="q"
        type="search"
        value={form?.query ?? ""}
        disabled={addDisabled}
      />
      <button type="submit" disabled={addDisabled}>Search</button>
      {#if addDisabled}
        <p>Remove an officeholder before adding another comparison column.</p>
      {/if}
      {#if form?.validationMessage}
        <p class="compare__form-error">{form.validationMessage}</p>
      {/if}
    </form>

    {#if !addDisabled && form?.suggestions && form.suggestions.length > 0}
      <ul class="compare__suggestions" aria-label="Officeholder search results">
        {#each form.suggestions as suggestion (suggestion.entity_id)}
          <li>
            <a href={addPersonHref(suggestion.entity_id)}>{suggestion.name}</a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  {#if compareNavigationPending}
    {@render comparisonLoadingColumns("Comparison loading columns")}
  {:else}
    {#await columnOutcomes}
      {@render comparisonLoadingColumns("Comparison loading columns")}
    {:then outcomes}
      {#await buildComparePresentation(data.columns, outcomes)}
        {@render comparisonLoadingColumns("Comparison presentation loading")}
    {:then presentation}
      <section class="compare__summary" aria-label="Answer-first comparison summary">
        <p>{presentation.answerFirstSummary}</p>
        <p>{presentation.dataThroughLabel}</p>
      </section>

      <section class="compare__totals" aria-label="Headline totals">
        {#each presentation.rows as row (row.id)}
          <section class="compare__row">
            <h3>{row.label}</h3>
            <ComparisonBar entities={barEntities(row, presentation)} scaleMax={row.scaleMax} />
            <p>Shared scale maximum: {row.scaleMaxLabel}</p>
          </section>
        {/each}
      </section>

      <section class="compare__columns" aria-label="Comparison chart columns">
        {#each presentation.charts as chart, index (chart.personId)}
          {@const column = presentation.columns[index]}
          <article class="compare__column" aria-label={`Compare column for ${column.name}`}>
            <h3><a href={column.href}>{column.name}</a></h3>
            {#if column.status === "error"}
              <p>{column.errorMessage}</p>
            {:else}
              {#if chart.moneyAtGlance === null}
                <p>No official candidate summary is loaded for this column.</p>
              {:else}
                <dl class="compare__exact">
                  {#each chart.moneyAtGlance.metricRows as metric (metric.label)}
                    <div>
                      <dt>{metric.label}</dt>
                      <dd>{metric.value}</dd>
                    </div>
                  {/each}
                </dl>
              {/if}
              {#if chart.contributionInsights === null}
                <p>No itemized contribution data is available for this column.</p>
              {:else if chart.contributionInsights.emptyMessage !== null}
                <p>{chart.contributionInsights.emptyMessage}</p>
              {:else}
                <p>First filing month: {firstCoveredMonth(chart.contributionInsights.monthlyContributions.coveredMonths)}</p>
                <p>Shared scale maximum: {presentation.chartScales.monthlyContributions.maxLabel}</p>
                <MonthlyContributionsChart
                  testId={`compare-${chart.personId}-monthly`}
                  cycle={chart.contributionInsights.monthlyContributions.cycle}
                  coverageThrough={chart.contributionInsights.monthlyContributions.coverageThrough}
                  sources={chart.contributionInsights.monthlyContributions.sources}
                  rows={chart.contributionInsights.monthlyContributions.rows}
                  coveredMonths={chart.contributionInsights.monthlyContributions.coveredMonths}
                  scaleMax={presentation.chartScales.monthlyContributions.max}
                />
                <p>Shared scale maximum: {presentation.chartScales.sizeBucketDollars.maxLabel}</p>
                <HorizontalBarChart
                  testId={`compare-${chart.personId}-size`}
                  title={chart.contributionInsights.sizeBuckets.title}
                  cycle={chart.contributionInsights.sizeBuckets.cycle}
                  coverageThrough={chart.contributionInsights.sizeBuckets.coverageThrough}
                  sources={chart.contributionInsights.sizeBuckets.sources}
                  rows={chart.contributionInsights.sizeBuckets.rowsByUnit.dollars}
                  scaleMax={presentation.chartScales.sizeBucketDollars.max}
                />
                <p>Geography basis: {chart.contributionInsights.geographyNote}</p>
                <GeographyShareChart
                  testId={`compare-${chart.personId}-geography`}
                  cycle={chart.contributionInsights.geographyShare.cycle}
                  coverageThrough={chart.contributionInsights.geographyShare.coverageThrough}
                  sources={chart.contributionInsights.geographyShare.sources}
                  rows={chart.contributionInsights.geographyShare.rows}
                  approximationNote={chart.contributionInsights.geographyShare.approximationNote}
                  unknownIncludedInDenominator={chart.contributionInsights.geographyShare.mode === "district"}
                />
                {#if chart.outsideSpending === null}
                  <p>No official outside-spending summary is loaded for this column.</p>
                {:else}
                  <p>Shared scale maximum: {presentation.chartScales.outsideSpending.maxLabel}</p>
                  <OutsideSpendingChart
                    testId={`compare-${chart.personId}-outside-spending`}
                    cycle={chart.outsideSpending.cycle}
                    coverageThrough={chart.outsideSpending.coverageThrough}
                    sources={FEC_SCHEDULE_E_SOURCE}
                    rows={chart.outsideSpending.rows}
                    topSpenders={chart.outsideSpending.topSpenders}
                    scaleMax={presentation.chartScales.outsideSpending.max}
                  />
                {/if}
              {/if}
            {/if}
            <footer class="compare__provenance">
              {#if column.provenanceLinks.length === 0}
                <p>Source links are unavailable for this officeholder.</p>
              {:else}
                <p>Sources:
                  {#each column.provenanceLinks as source, sourceIndex (`${source.href}-${sourceIndex}`)}
                    <a href={source.href}>{source.label}</a>{sourceIndex < column.provenanceLinks.length - 1 ? ", " : ""}
                  {/each}
                </p>
              {/if}
            </footer>
          </article>
        {/each}
      </section>

      <footer class="compare__footnotes" aria-label="Comparison footnotes">
        <p>{presentation.fairnessCopy}</p>
        <p>{presentation.provenanceCopy}</p>
      </footer>
      {:catch}
        <p>Comparison data is temporarily unavailable.</p>
      {/await}
    {/await}
  {/if}
</section>

<style>
  .compare {
    display: grid;
    gap: 1.25rem;
  }

  .compare__header,
  .compare__selection,
  .compare__summary,
  .compare__row,
  .compare__column,
  .compare__footnotes {
    border: 1px solid #cbd5e1;
    border-radius: 0.5rem;
    padding: 1rem;
  }

  .compare__chips,
  .compare__notices,
  .compare__suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .compare__chip {
    align-items: center;
    border: 1px solid #94a3b8;
    display: inline-flex;
    gap: 0.75rem;
    padding: 0.35rem 0.5rem;
  }

  .compare__search {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .compare__columns {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fit, minmax(min(24rem, 100%), 1fr));
  }

  .compare__exact {
    display: grid;
    gap: 0.5rem;
  }

  .compare__exact div {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }

  .compare__form-error {
    color: #991b1b;
  }
</style>
