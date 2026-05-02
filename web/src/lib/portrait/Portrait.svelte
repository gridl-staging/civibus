<script lang="ts">
  import type { PersonPortraitResponse } from "$lib/entity-detail/contract";

  export let canonicalName: string;
  export let personId: string | null | undefined = null;
  export let portrait: PersonPortraitResponse | null | undefined = null;

  $: resolvedImageUrl = portrait?.source_image_url ?? null;
  $: imageAlt = `Portrait of ${canonicalName}`;
  $: fallbackLabel = `Portrait unavailable for ${canonicalName}`;
  $: initialsLabel = `Initials avatar for ${canonicalName}`;
  $: fallbackInitials = deriveInitials(canonicalName);

  const TRAILING_NAME_SUFFIXES = new Set(["JR", "SR", "II", "III", "IV", "V"]);

  function normalizeNameToken(token: string): string {
    return token.replace(/[.,]/g, "").toUpperCase();
  }

  function stripTrailingSuffixTokens(parts: string[]): string[] {
    const nameParts = [...parts];
    while (nameParts.length > 1) {
      const trailingToken = normalizeNameToken(nameParts[nameParts.length - 1]);
      if (!TRAILING_NAME_SUFFIXES.has(trailingToken)) {
        break;
      }
      nameParts.pop();
    }
    return nameParts;
  }

  function deriveInitials(name: string): string {
    const parts = name
      .trim()
      .split(/\s+/)
      .filter((part) => part.length > 0);

    if (parts.length === 0) {
      return "?";
    }

    const nameParts = stripTrailingSuffixTokens(parts);

    if (nameParts.length === 1) {
      return nameParts[0].slice(0, 2).toUpperCase();
    }

    const firstNameToken = nameParts[0];
    const lastNameToken = nameParts[nameParts.length - 1];
    return `${firstNameToken[0]}${lastNameToken[0]}`.toUpperCase();
  }
</script>

{#if resolvedImageUrl !== null}
  <img
    class="entity-portrait"
    src={resolvedImageUrl}
    alt={imageAlt}
    loading="lazy"
    decoding="async"
    data-testid="entity-portrait-image"
  />
{:else}
  {#if personId !== null && personId !== undefined}
    <div
      class="entity-portrait entity-portrait--fallback entity-portrait--initials"
      role="img"
      aria-label={initialsLabel}
      data-testid="entity-portrait-initials"
    >
      <span aria-hidden="true">{fallbackInitials}</span>
    </div>
  {:else}
  <div class="entity-portrait entity-portrait--fallback" role="img" aria-label={fallbackLabel} data-testid="entity-portrait-silhouette">
    <span aria-hidden="true">No image</span>
  </div>
  {/if}
{/if}

<style>
  .entity-portrait {
    width: 5rem;
    height: 5rem;
    border-radius: 9999px;
    object-fit: cover;
    flex-shrink: 0;
    background: #e5e7eb;
    color: #4b5563;
  }

  .entity-portrait--fallback {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    border: 1px solid #d1d5db;
  }

  .entity-portrait--initials {
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
</style>
