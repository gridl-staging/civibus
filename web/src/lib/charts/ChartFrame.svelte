<script lang="ts">
  import type { Snippet } from "svelte";
  import { formatDate } from "./finance";
  import type { ChartFrameProps } from "./types";

  export let testId: ChartFrameProps["testId"];
  export let title: ChartFrameProps["title"];
  export let unit: ChartFrameProps["unit"];
  export let cycle: ChartFrameProps["cycle"];
  export let coverageThrough: ChartFrameProps["coverageThrough"];
  export let summary: ChartFrameProps["summary"];
  export let sources: ChartFrameProps["sources"] = [];
  export let exactRows: ChartFrameProps["exactRows"] = [];
  export let state: ChartFrameProps["state"] = { kind: "ready" };
  export let children: Snippet | undefined = undefined;

  $: coverageLabel = formatDate(coverageThrough);

  function sanitizeHref(href: string | null | undefined): string | null {
    if (typeof href !== "string") {
      return null;
    }

    const trimmedHref = href.trim();
    if (trimmedHref.length === 0) {
      return null;
    }

    if (trimmedHref.startsWith("/") && !trimmedHref.startsWith("//")) {
      return trimmedHref;
    }

    try {
      const parsed = new URL(trimmedHref);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
    } catch {
      return null;
    }
  }

  function exactRowKey(row: ChartFrameProps["exactRows"][number], index: number): string {
    const valueKey = row.values
      .map((value) => `${value.label}:${value.value}:${value.href ?? ""}`)
      .join("|");
    return `${row.label}:${valueKey}:${index}`;
  }
</script>

<figure class="finance-chart" data-testid={testId}>
  <figcaption class="finance-chart__caption">
    <span class="finance-chart__title">{title}</span>
    <span class="finance-chart__meta">
      {cycle} cycle, coverage through {coverageLabel}. Unit: {unit}
    </span>
  </figcaption>

  <p class="finance-chart__summary">{summary.sentence}</p>

  {#if state.kind !== "ready"}
    <p class:finance-chart__table-only={state.kind === "table-only"}>{state.message}</p>
  {/if}

  {#if state.kind === "ready"}
    <div class="finance-chart__body">
      {@render children?.()}
    </div>
  {/if}

  <p class="finance-chart__sources">
    Sources:
    {#each sources as source, index (source.label)}
      {#if index > 0}, {/if}
      {@const safeSourceHref = sanitizeHref(source.href)}
      {#if safeSourceHref}
        <a href={safeSourceHref}>{source.label}</a>
      {:else}
        <span>{source.label}</span>
      {/if}
    {/each}
  </p>

  <details class="finance-chart__details">
    <summary>View chart data</summary>
    <table>
      <thead>
        <tr>
          <th scope="col">Label</th>
          <th scope="col">Values</th>
        </tr>
      </thead>
      <tbody>
        {#each exactRows as row, rowIndex (exactRowKey(row, rowIndex))}
          <tr>
            <th scope="row">{row.label}</th>
            <td>
              {#each row.values as value, index (value.label)}
                {#if index > 0}; {/if}{value.label}:
                {@const safeValueHref = sanitizeHref(value.href)}
                {#if safeValueHref}
                  <a href={safeValueHref}>{value.value}</a>
                {:else}
                  {value.value}
                {/if}
              {/each}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </details>
</figure>

<style>
  .finance-chart {
    display: grid;
    gap: 0.75rem;
    margin: 0;
    color: #111827;
  }

  .finance-chart__caption {
    display: grid;
    gap: 0.25rem;
  }

  .finance-chart__title {
    font-weight: 700;
  }

  .finance-chart__meta,
  .finance-chart__sources {
    color: #475569;
    font-size: 0.875rem;
  }

  .finance-chart__summary,
  .finance-chart__sources,
  .finance-chart__details {
    margin: 0;
  }

  .finance-chart__body {
    min-height: 8rem;
  }

  .finance-chart__table-only {
    border-left: 0.25rem solid #92400e;
    margin: 0;
    padding-left: 0.75rem;
  }

  .finance-chart__details summary {
    min-height: 44px;
    display: flex;
    align-items: center;
    padding: 0.4rem 0;
    cursor: pointer;
    font-weight: 600;
  }

  .finance-chart__details table {
    border-collapse: collapse;
    margin-top: 0.5rem;
    width: 100%;
  }

  .finance-chart__details th,
  .finance-chart__details td {
    border-top: 1px solid #cbd5e1;
    padding: 0.5rem;
    text-align: left;
    vertical-align: top;
  }
</style>
