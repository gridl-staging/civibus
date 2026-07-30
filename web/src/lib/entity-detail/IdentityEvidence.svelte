<script lang="ts">
  import { formatDisplayValue } from "$lib/detail-format";
  import {
    buildIdentityDisclosureLabel,
    buildIdentityEvidencePresentation,
    CORRECTION_UNAVAILABLE_REASON,
    describeCombinedIdentity,
    formatCombinedRecordCount,
    getPublishedConfidenceLabel,
    IDENTITY_EVIDENCE_UNAVAILABLE_MESSAGE,
    type IdentityConfidenceBand,
    type IdentityEvidenceRecord,
    type NotCombinedIdentityEvidenceRecord
  } from "./donor-identity-evidence";

  export let donorName: string;
  export let idPrefix: string;
  export let combinedRecordCount: number;
  export let confidenceBand: IdentityConfidenceBand;
  export let underlyingRecords: IdentityEvidenceRecord[] = [];
  export let notCombinedCandidates: NotCombinedIdentityEvidenceRecord[] = [];

  $: combinedCountLabel = formatCombinedRecordCount(combinedRecordCount);
  $: confidenceLabel = getPublishedConfidenceLabel(confidenceBand);
  $: disclosureLabel = buildIdentityDisclosureLabel(donorName, combinedRecordCount);
  $: combinedDescription = describeCombinedIdentity(confidenceBand, combinedRecordCount);
  $: combinedEvidence = buildIdentityEvidencePresentation(underlyingRecords);
  $: candidateEvidence = notCombinedCandidates.map((candidate) =>
    buildIdentityEvidencePresentation([candidate])
  );
  $: combinedCorrectionReasonId = `${idPrefix}-combined-correction-reason`;

  function formatLocation(record: IdentityEvidenceRecord): string {
    const city = record.contributor_city?.trim();
    const state = record.contributor_state?.trim();

    if (city && state) {
      return `${city}, ${state}`;
    }

    return formatDisplayValue(city || state || null);
  }

  function recordKey(record: IdentityEvidenceRecord, index: number): string {
    return `${record.contributor_name}:${record.sources[0]?.source_record_key ?? index}`;
  }

  function candidateCorrectionReasonId(index: number): string {
    return `${idPrefix}-candidate-${index}-correction-reason`;
  }

  function buildFilingLabel(record: IdentityEvidenceRecord): string {
    const contributorName = record.contributor_name?.trim();
    if (contributorName) {
      return `Source filing for ${contributorName}`;
    }

    return "Source filing for this donor record";
  }
</script>

<div class="identity-evidence">
  {#if combinedEvidence.status === "available"}
    <details class="identity-evidence__disclosure" data-testid="donor-identity-disclosure" open>
      <summary aria-label={disclosureLabel}>
        <span>{combinedCountLabel}</span>
        <span>{confidenceLabel}</span>
      </summary>

      <p class="identity-evidence__description">{combinedDescription}</p>

      <ul
        class="identity-evidence__records"
        data-testid="donor-identity-combined-records"
        aria-label="Combined donor records"
      >
        {#each combinedEvidence.records as evidence, index (recordKey(evidence.record, index))}
          <li class="identity-evidence__record" data-testid="donor-identity-underlying-record">
            <span class="identity-evidence__record-name">{evidence.record.contributor_name}</span>
            <span>{formatDisplayValue(evidence.record.contributor_employer)}</span>
            <span>{formatDisplayValue(evidence.record.contributor_occupation)}</span>
            <span>{formatLocation(evidence.record)}</span>
            <a
              data-testid="donor-identity-underlying-filing"
              href={evidence.filingHref}
              aria-label={buildFilingLabel(evidence.record)}
            >
              Source filing
            </a>
          </li>
        {/each}
      </ul>

      <div class="identity-evidence__correction">
        <button
          type="button"
          disabled
          data-testid="donor-identity-correction-combined"
          aria-describedby={combinedCorrectionReasonId}
        >
          this isn't the same person
        </button>
        <span id={combinedCorrectionReasonId}>{CORRECTION_UNAVAILABLE_REASON}</span>
      </div>
    </details>
  {:else}
    <p class="identity-evidence__unavailable" data-testid="donor-identity-evidence-unavailable">
      {IDENTITY_EVIDENCE_UNAVAILABLE_MESSAGE}
    </p>
  {/if}

  {#if candidateEvidence.length > 0}
    <div
      class="identity-evidence__not-combined"
      data-testid="donor-identity-not-combined-candidates"
    >
      {#each candidateEvidence as presentation, index}
        {#if presentation.status === "available"}
          {#each presentation.records as evidence (recordKey(evidence.record, index))}
            <section
              class="identity-evidence__candidate"
              data-testid="donor-identity-not-combined-candidate"
            >
              <p>
                <span>not combined</span>
                <span>{getPublishedConfidenceLabel(evidence.record.confidence_band)}</span>
              </p>
              <div class="identity-evidence__record">
                <span class="identity-evidence__record-name">{evidence.record.contributor_name}</span>
                <span>{formatDisplayValue(evidence.record.contributor_employer)}</span>
                <span>{formatDisplayValue(evidence.record.contributor_occupation)}</span>
                <span>{formatLocation(evidence.record)}</span>
                <a href={evidence.filingHref} aria-label={buildFilingLabel(evidence.record)}>
                  Source filing
                </a>
              </div>
              <div class="identity-evidence__correction">
                <button
                  type="button"
                  disabled
                  data-testid="donor-identity-correction-candidate"
                  aria-describedby={candidateCorrectionReasonId(index)}
                >
                  these are the same person
                </button>
                <span id={candidateCorrectionReasonId(index)}>{CORRECTION_UNAVAILABLE_REASON}</span>
              </div>
            </section>
          {/each}
        {:else}
          <p class="identity-evidence__unavailable" data-testid="donor-candidate-evidence-unavailable">
            {IDENTITY_EVIDENCE_UNAVAILABLE_MESSAGE}
          </p>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .identity-evidence {
    display: grid;
    gap: 0.65rem;
    margin-top: 0.55rem;
  }

  .identity-evidence__disclosure {
    display: grid;
    gap: 0.45rem;
  }

  .identity-evidence__disclosure summary {
    cursor: pointer;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    font-weight: 700;
  }

  .identity-evidence__description,
  .identity-evidence__candidate p,
  .identity-evidence__unavailable {
    margin: 0;
  }

  .identity-evidence__records {
    display: grid;
    gap: 0.4rem;
    margin: 0.5rem 0 0;
    padding-left: 1rem;
  }

  .identity-evidence__record {
    display: grid;
    gap: 0.2rem;
  }

  .identity-evidence__record-name {
    font-weight: 700;
  }

  .identity-evidence__correction {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    align-items: center;
    margin-top: 0.5rem;
  }

  .identity-evidence__not-combined {
    display: grid;
    gap: 0.65rem;
  }

  .identity-evidence__candidate {
    border-top: 1px solid #d6e1ea;
    display: grid;
    gap: 0.4rem;
    padding-top: 0.55rem;
  }
</style>
