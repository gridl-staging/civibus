<script lang="ts">
  import type { ComponentProps } from "svelte";

  import Portrait from "$lib/portrait/Portrait.svelte";
  import {
    buildComparisonSegments,
    sharedScaleWidthPct,
    type ComparisonSegmentInput
  } from "./comparison-transforms";
  import { FINANCE_CHART_COLORS } from "./finance";

  type PortraitProps = ComponentProps<typeof Portrait>;

  type ComparisonBarEntity = {
    id: string;
    label: string;
    portrait?: PortraitProps["portrait"];
    href?: string;
    linkTestId?: string;
    // A finite number or exact serialized decimal (including an honest 0) is a
    // reported value; null signals money that was never reported or loaded.
    value: number | string | null;
    valueLabel: string;
    // Exact-decimal callers project geometry before the number-only transform seam.
    widthPercentage?: string;
    // Keep the default genuine-empty copy unless the parent knows the whole metric request is unavailable.
    showMissingValueLabel?: boolean;
    segments?: ComparisonSegmentInput[];
  };

  export let entities: ComparisonBarEntity[] = [];
  export let scaleMax: number | string;
  export let segmentOrder: readonly string[] = [];

  const NO_REPORTED_MONEY = "No reported/loaded money.";
  const INTERNAL_LINK_ORIGIN = "https://civibus.invalid";
  const SAFE_SEGMENT_COLOR = /^(?:#[\da-f]{3}|#[\da-f]{4}|#[\da-f]{6}|#[\da-f]{8}|[a-z]+)$/i;
  const SAFE_WIDTH_PERCENTAGE = /^(?:100(?:\.0+)?|\d{1,2}(?:\.\d+)?)%$/;

  function isReportedValue(entity: ComparisonBarEntity): boolean {
    if (typeof entity.value === "number") {
      return Number.isFinite(entity.value);
    }
    return typeof entity.value === "string" && getExactWidthPercentage(entity) !== null;
  }

  function getExactWidthPercentage(entity: ComparisonBarEntity): string | null {
    const width = entity.widthPercentage;
    return typeof width === "string" && SAFE_WIDTH_PERCENTAGE.test(width) ? width : null;
  }

  function getSharedScaleWidth(entity: ComparisonBarEntity): string {
    const exactWidth = getExactWidthPercentage(entity);
    if (typeof entity.value === "string") {
      return exactWidth ?? "0%";
    }
    // Keep the shared-scale ratio unrounded until the final CSS percentage render boundary.
    return `${sharedScaleWidthPct(entity.value ?? 0, typeof scaleMax === "number" ? scaleMax : 0) * 100}%`;
  }

  function getSegmentWidth(widthPct: number): string {
    return `${widthPct * 100}%`;
  }

  function getSafeInternalHref(href: string | undefined): string | null {
    if (!href?.startsWith("/")) {
      return null;
    }

    try {
      const parsed = new URL(href, INTERNAL_LINK_ORIGIN);
      if (parsed.origin !== INTERNAL_LINK_ORIGIN) {
        return null;
      }
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      return null;
    }
  }

  function getSafeSegmentColor(color: string): string {
    return SAFE_SEGMENT_COLOR.test(color) ? color : FINANCE_CHART_COLORS.neutral;
  }

  function getSegments(entity: ComparisonBarEntity, total: number) {
    if (!entity.segments || entity.segments.length === 0) {
      return [];
    }
    const result = buildComparisonSegments({
      total,
      segments: entity.segments,
      segmentOrder
    });
    if (result.kind === "no-data") {
      return [];
    }
    return result.segments;
  }
</script>

<div
  class="comparison-bars"
  style:--comparison-track-fill={FINANCE_CHART_COLORS.neutral}
  style:--comparison-track-background={FINANCE_CHART_COLORS.mutedBackground}
  style:--comparison-surface={FINANCE_CHART_COLORS.background}
>
  {#each entities as entity (entity.id)}
    {@const safeHref = getSafeInternalHref(entity.href)}
    <div class="comparison-bars__row" data-testid={`comparison-row-${entity.id}`}>
      <div class="comparison-bars__identity">
        <Portrait canonicalName={entity.label} personId={entity.id} portrait={entity.portrait} />
        <div class="comparison-bars__label-block">
          {#if safeHref}
            <a class="comparison-bars__label" href={safeHref} data-testid={entity.linkTestId}>{entity.label}</a>
          {:else}
            <span class="comparison-bars__label">{entity.label}</span>
          {/if}
        </div>
      </div>

      <div class="comparison-bars__measure">
        {#if isReportedValue(entity)}
          {@const segments = typeof entity.value === "number" ? getSegments(entity, entity.value) : []}
          <div
            class="comparison-bars__track"
            data-testid={`comparison-bar-${entity.id}`}
            style:--comparison-track-width={getSharedScaleWidth(entity)}
          >
            {#if segments.length > 0}
              {#each segments as segment (segment.id)}
                <span
                  class="comparison-bars__segment"
                  data-testid={`comparison-segment-${entity.id}-${segment.id}`}
                  title={segment.tooltipText}
                  style:--comparison-segment-width={getSegmentWidth(segment.widthPct)}
                  style:--comparison-segment-fill={getSafeSegmentColor(segment.color)}
                >
                  <span class="comparison-bars__segment-label">{segment.label}</span>
                </span>
              {/each}
            {:else}
              <span class="comparison-bars__unsegmented-fill"></span>
            {/if}
          </div>
        {/if}
      </div>

      <span class="comparison-bars__end-label" data-testid={`comparison-end-label-${entity.id}`}>
        {#if isReportedValue(entity)}
          {entity.valueLabel}
        {:else if entity.showMissingValueLabel !== false}
          {NO_REPORTED_MONEY}
        {/if}
      </span>
    </div>
  {/each}
</div>

<style>
  .comparison-bars {
    background: var(--comparison-surface);
    display: grid;
    gap: 0.75rem;
  }

  .comparison-bars__row {
    align-items: center;
    display: grid;
    gap: 0.75rem;
    grid-template-columns: minmax(13rem, 1.5fr) minmax(8rem, 3fr) max-content;
    min-width: 0;
  }

  .comparison-bars__identity {
    align-items: center;
    display: flex;
    gap: 0.75rem;
    min-width: 0;
  }

  .comparison-bars__label-block {
    min-width: 0;
  }

  .comparison-bars__label {
    color: #0f172a;
    overflow-wrap: anywhere;
    text-decoration-color: #94a3b8;
  }

  .comparison-bars__measure {
    min-width: 0;
  }

  .comparison-bars__track {
    background: var(--comparison-track-background);
    border: 1px solid #cbd5e1;
    display: flex;
    height: 1rem;
    max-width: 100%;
    overflow: hidden;
    width: var(--comparison-track-width);
  }

  .comparison-bars__segment {
    background: var(--comparison-segment-fill);
    display: block;
    min-width: 0;
    width: var(--comparison-segment-width);
  }

  .comparison-bars__segment-label {
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    height: 1px;
    overflow: hidden;
    position: absolute;
    white-space: nowrap;
    width: 1px;
  }

  .comparison-bars__unsegmented-fill {
    background: var(--comparison-track-fill);
    display: block;
    width: 100%;
  }

  .comparison-bars__end-label {
    color: #334155;
  }

  .comparison-bars__end-label {
    overflow-wrap: anywhere;
    text-align: right;
  }

  @media (max-width: 42rem) {
    .comparison-bars__row {
      align-items: stretch;
      grid-template-columns: minmax(0, 1fr);
    }

    .comparison-bars__end-label {
      text-align: left;
    }
  }
</style>
