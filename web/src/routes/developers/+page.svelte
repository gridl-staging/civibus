<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";

  const routeMetadata = APP_SHELL.staticRoutes.developers;
  const samplePersonId = "11111111-1111-1111-1111-111111111111";
  const sampleCandidateId = "44444444-4444-4444-4444-444444444444";
  const sampleUnloadedPersonId = "66666666-6666-6666-6666-666666666666";
  const sampleUnloadedPersonName = "Sample Official Without Loaded Filings";
  // api/routes/public_federal.py::_csv_cell writes an empty cell for every
  // null money value, so the unknown-money CSV row is name + false + eleven
  // empty cells. Built by join so the column count cannot drift from
  // csvColumns silently.
  const notLoadedCoverageBlock = `{
    "activity_state": "not_loaded",
    "completeness": "unknown",
    "basis": "no_authoritative_load_evidence"
  }`;
  // The nullable-money contract, shared verbatim by the money endpoint and
  // both export blocks (civibus-o53): null and empty-cell values are unknown,
  // never zero, per api.models.campaign_finance.PublicMemberMoneySummary.
  const nullableMoneyNote =
    "Every money field is nullable — the fundraising fields (total_raised, total_spent, net, " +
    "cash_on_hand, summary_source) and the outside-spending fields (ie_support_total, " +
    "ie_oppose_total, ie_support_count, ie_oppose_count). A null value means the figure is " +
    "unknown and never means zero: the official has no linked FEC candidate, or the FEC filings " +
    "for the selected cycle were never loaded. A fundraising_coverage / ie_coverage block " +
    "accompanies every non-populated state and says why. A candidate whose loaded filings " +
    'genuinely total nothing still sends "0.00" — the coverage state, never the number, says ' +
    "which is which.";
  const csvEmptyCellNote =
    "The money columns write an empty cell when the value is unknown — an empty cell never " +
    "means zero. The CSV carries no coverage columns; consult export.json's " +
    "fundraising_coverage / ie_coverage blocks for why a value is unknown.";
  const shellBaseGuard =
    ': "${CIVIBUS_PUBLIC_API_BASE:?Set CIVIBUS_PUBLIC_API_BASE to a Civibus origin that serves /api}"';
  const csvColumns = [
    "person_id",
    "person_name",
    "has_fec_money",
    "candidate_id",
    "total_raised",
    "total_spent",
    "net",
    "cash_on_hand",
    "summary_source",
    "ie_support_total",
    "ie_oppose_total",
    "ie_support_count",
    "ie_oppose_count",
    "source_urls"
  ] as const;
  const notLoadedMoneySample = `{
  "person_id": "${sampleUnloadedPersonId}",
  "person_name": "${sampleUnloadedPersonName}",
  "has_fec_money": false,
  "candidate_id": null,
  "total_raised": null,
  "total_spent": null,
  "net": null,
  "cash_on_hand": null,
  "summary_source": null,
  "fundraising_coverage": ${notLoadedCoverageBlock},
  "ie_support_total": null,
  "ie_oppose_total": null,
  "ie_support_count": null,
  "ie_oppose_count": null,
  "ie_coverage": ${notLoadedCoverageBlock},
  "sources": []
}`;
  const csvNotLoadedRow = [
    sampleUnloadedPersonId,
    sampleUnloadedPersonName,
    "false",
    ...Array.from({ length: csvColumns.length - 3 }, () => "")
  ].join(",");
  type EndpointReference = {
    label: string;
    parameters: readonly string[];
    curl: string;
    sampleLabel: string;
    sampleBody: string;
    notes?: string;
    secondarySampleLabel?: string;
    secondarySampleBody?: string;
  };
  const endpointReferences: readonly EndpointReference[] = [
    {
      label: "GET /api/public/v1/federal/officials",
      parameters: ["chamber", "state", "party"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/officials?state=NC&chamber=House"`,
      sampleLabel: "Sample JSON",
      sampleBody: `[
  {
    "person_id": "${samplePersonId}",
    "person_name": "Sample Official",
    "officeholding_id": "22222222-2222-2222-2222-222222222222",
    "office_id": "33333333-3333-3333-3333-333333333333",
    "office_name": "U.S. House NC-01",
    "chamber": "House",
    "state": "NC",
    "district": "01",
    "district_or_class": "01",
    "party": "Independent",
    "portrait_source_image_url": "https://www.congress.gov/img/member/sample.jpg",
    "person_detail_path": "/person/${samplePersonId}"
  }
]`
    },
    {
      label: "GET /api/public/v1/federal/officials/{person_id}/money",
      parameters: ["none beyond person_id in the path"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/officials/${samplePersonId}/money"`,
      notes: nullableMoneyNote,
      secondarySampleLabel: "Sample JSON (money not loaded)",
      secondarySampleBody: notLoadedMoneySample,
      sampleLabel: "Sample JSON",
      sampleBody: `{
  "person_id": "${samplePersonId}",
  "person_name": "Sample Official",
  "has_fec_money": true,
  "candidate_id": "${sampleCandidateId}",
  "total_raised": "125000.00",
  "total_spent": "100000.00",
  "net": "25000.00",
  "cash_on_hand": "45000.00",
  "summary_source": "fec_weball",
  "ie_support_total": "5000.00",
  "ie_oppose_total": "0.00",
  "ie_support_count": 2,
  "ie_oppose_count": 0,
  "sources": [
    {
      "domain": "campaign_finance",
      "jurisdiction": "federal",
      "data_source_name": "FEC candidate master",
      "data_source_url": "https://www.fec.gov/data/browse-data/?tab=candidates",
      "source_record_key": "H4NC00000",
      "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
      "pull_date": "2026-07-10T00:00:00Z"
    }
      ]
}`
    },
    {
      label: "GET /api/public/v1/federal/officials/{person_id}/contributors",
      parameters: ["none beyond person_id in the path"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/officials/${samplePersonId}/contributors"`,
      sampleLabel: "Sample JSON",
      sampleBody: `{
  "person_id": "${samplePersonId}",
  "contributors": [
    {
      "name": "Sample Contributor",
      "total_amount": "5000.00",
      "transaction_count": 3
    }
  ],
  "sources": [
    {
      "domain": "campaign_finance",
      "jurisdiction": "federal",
      "data_source_name": "FEC itemized individual contributions",
      "data_source_url": "https://www.fec.gov/data/receipts/individual-contributions/",
      "source_record_key": "H4NC00000",
      "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
      "pull_date": "2026-07-10T00:00:00Z"
    }
  ]
}`
    },
    {
      label: "GET /api/public/v1/federal/officials/{person_id}/employers",
      parameters: ["none beyond person_id in the path"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/officials/${samplePersonId}/employers"`,
      sampleLabel: "Sample JSON",
      sampleBody: `{
  "person_id": "${samplePersonId}",
  "employers": [
    {
      "employer": "Unclassified / not provided",
      "total_amount": "29150.00",
      "transaction_count": 85,
      "industry": "UNKNOWN_INDUSTRY"
    }
  ],
  "classified_count": 837,
  "unknown_count": 13487,
  "sampled_coverage_percentage": "5.843340",
  "sources": [
    {
      "domain": "campaign_finance",
      "jurisdiction": "federal",
      "data_source_name": "FEC itemized individual contributions",
      "data_source_url": "https://www.fec.gov/data/receipts/individual-contributions/",
      "source_record_key": "H4NC00000",
      "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
      "pull_date": "2026-07-10T00:00:00Z"
    }
  ]
}`
    },
    {
      label: "GET /api/public/v1/federal/export.json",
      parameters: ["none"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/export.json"`,
      notes:
        "Rows use the same nullable-money contract as the per-official money endpoint: " +
        "officials whose money is unknown appear with null totals and a fundraising_coverage / " +
        "ie_coverage block saying why, never with fabricated zeros.",
      sampleLabel: "Sample JSON",
      sampleBody: `[
  {
    "person_id": "${samplePersonId}",
    "person_name": "Sample Official",
    "has_fec_money": true,
    "candidate_id": "${sampleCandidateId}",
    "total_raised": "125000.00",
    "total_spent": "100000.00",
    "net": "25000.00",
    "cash_on_hand": "45000.00",
    "summary_source": "fec_weball",
    "ie_support_total": "5000.00",
    "ie_oppose_total": "0.00",
    "ie_support_count": 2,
    "ie_oppose_count": 0,
    "sources": [
      {
        "domain": "campaign_finance",
        "jurisdiction": "federal",
        "data_source_name": "FEC candidate master",
        "data_source_url": "https://www.fec.gov/data/browse-data/?tab=candidates",
        "source_record_key": "H4NC00000",
        "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
        "pull_date": "2026-07-10T00:00:00Z"
      }
    ]
  }
]`
    },
    {
      label: "GET /api/public/v1/federal/export.csv",
      parameters: ["none"],
      curl: `${shellBaseGuard} && curl -L "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/export.csv" -o civibus_federal_money.csv`,
      notes: csvEmptyCellNote,
      sampleLabel: "Sample CSV",
      sampleBody: `${csvColumns.join(",")}
${samplePersonId},Sample Official,true,${sampleCandidateId},125000.00,100000.00,25000.00,45000.00,fec_weball,5000.00,0.00,2,0,https://www.fec.gov/data/candidate/H4NC00000/
${csvNotLoadedRow}`
    },
    {
      label: "GET /api/public/v1/federal/metadata",
      parameters: ["none"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/metadata"`,
      sampleLabel: "Sample JSON",
      sampleBody: `{
  "data_sources": [
    {
      "data_source_id": "55555555-5555-5555-5555-555555555555",
      "domain": "campaign_finance",
      "jurisdiction": "federal/fec",
      "name": "FEC bulk data",
      "source_url": "https://www.fec.gov/data/browse-data/",
      "update_frequency": "weekly",
      "last_pull_at": "2026-07-20T09:00:00Z",
      "last_pull_status": "success",
      "record_count": 542,
      "latest_source_record_id": null,
      "latest_source_record_key": null,
      "latest_source_record_url": null,
      "latest_source_pull_date": "2026-07-20T09:00:00Z"
    }
  ],
  "rate_limit": {
    "max_requests": 100,
    "window_seconds": 60
  },
  "coverage": {
    "current_officeholder_count": 543,
    "officeholder_denominator_is_fixed": false,
    "employer_industry": {
      "classified_count": 837,
      "unknown_count": 13487,
      "sampled_coverage_percentage": "5.843340"
    },
    "donor_identity_resolution": "unresolved"
  }
}`
    }
  ] as const;
  const migrationMappings = [
    {
      source: "ProPublica Congress API members",
      civibusEquivalent: endpointReferences[0].label,
      delta: "Current federal officeholders only; no historical membership or legislative activity."
    },
    {
      source: "OpenSecrets API candSummary",
      civibusEquivalent: endpointReferences[1].label,
      delta: "FEC summary totals and Schedule E support or opposition, keyed by Civibus person_id."
    },
    {
      source: "OpenSecrets API candContrib",
      civibusEquivalent: endpointReferences[2].label,
      delta: "Aggregated contributor names from itemized FEC receipts; donor identities remain unresolved."
    },
    {
      source: "OpenSecrets API candIndustry",
      civibusEquivalent: endpointReferences[3].label,
      delta: "Employer rollups disclose sparse industry classification and do not reproduce OpenSecrets categories."
    },
    {
      source: "OpenSecrets bulk candidate summaries (JSON)",
      civibusEquivalent: endpointReferences[4].label,
      delta: "Current federal officeholders with FEC summaries and Schedule E totals; not a full OpenSecrets bulk mirror."
    },
    {
      source: "OpenSecrets bulk candidate summaries (CSV)",
      civibusEquivalent: endpointReferences[5].label,
      delta: "The same bounded Civibus export in spreadsheet form with source URLs."
    },
    {
      source: "ProPublica Congress API roll-call votes",
      civibusEquivalent: "No Civibus equivalent yet",
      delta: "Civibus does not currently publish roll-call votes or voting positions."
    }
  ] as const;
  const referenceLinks = ["/api/openapi.json", "/api/docs", "/api/redoc"] as const;

  $: canonicalPageUrl = new URL("/developers", $page.url);
  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: canonicalPageUrl,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card developers" aria-label="Public API">
  <h2>Public API</h2>
  <p>
    Developers and journalists migrating from OpenSecrets or ProPublica APIs can use this static
    reference to find Civibus's nonpartisan, source-linked federal public-record endpoints.
  </p>
  <p>
    FastAPI router owner: <code>/public/v1</code>; Caddy public URL prefix:
    <code>/api/public/v1</code>.
  </p>

  <h3>Endpoint reference</h3>

  {#each endpointReferences as endpoint}
    <article class="developers__endpoint">
      <h4><code>{endpoint.label}</code></h4>
      <p>Parameters: {endpoint.parameters.join(", ")}.</p>
      {#if endpoint.notes}
        <p>{endpoint.notes}</p>
      {/if}
      <h5>Curl</h5>
      <!-- The overflow is intentional; keyboard users need to focus the scrolling element. -->
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <pre tabindex="0"><code>{endpoint.curl}</code></pre>
      <h5>{endpoint.sampleLabel}</h5>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <pre tabindex="0"><code>{endpoint.sampleBody}</code></pre>
      {#if endpoint.secondarySampleLabel && endpoint.secondarySampleBody}
        <h5>{endpoint.secondarySampleLabel}</h5>
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <pre tabindex="0"><code>{endpoint.secondarySampleBody}</code></pre>
      {/if}
    </article>
  {/each}

  <h3>CSV columns</h3>
  <ul class="developers__columns">
    {#each csvColumns as column}
      <li><code>{column}</code></li>
    {/each}
  </ul>

  <h3>OpenSecrets and ProPublica migration mapping</h3>
  <table>
    <thead>
      <tr>
        <th scope="col">Source API and endpoint/product</th>
        <th scope="col">Civibus equivalent</th>
        <th scope="col">Honest delta</th>
      </tr>
    </thead>
    <tbody>
      {#each migrationMappings as mapping}
        <tr>
          <td>{mapping.source}</td>
          <td><code>{mapping.civibusEquivalent}</code></td>
          <td>{mapping.delta}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <h3>Reference links</h3>
  <ul>
    {#each referenceLinks as referenceLink}
      <li><a href={referenceLink}>{referenceLink}</a></li>
    {/each}
  </ul>

  <section aria-labelledby="public-api-stability-heading">
    <h3 id="public-api-stability-heading">Stability, freshness, and limits</h3>
    <p>
      Endpoint schemas are the stable client contract. Read the metadata endpoint for live source
      freshness, coverage qualifications, and the effective rate-limit policy.
    </p>
    <p>
      Metadata endpoint:
      <a href="/api/public/v1/federal/metadata">GET /api/public/v1/federal/metadata</a>.
    </p>
    <p>
      Public API requests are rate limited. Public responses use
      <code>Cache-Control: public, max-age=900</code>.
    </p>
  </section>

  <p>
    <a href={APP_SHELL.reportingLink.href}>{APP_SHELL.reportingLink.label}</a>
  </p>
</section>

<style>
  .developers h3 {
    margin: 1.2rem 0 0.5rem;
  }

  .developers h4 {
    margin: 0;
  }

  .developers h5 {
    margin: 0.75rem 0 0.35rem;
  }

  .developers__endpoint {
    border-top: 1px solid #d7e3ed;
    padding: 1rem 0;
  }

  .developers__endpoint:first-of-type {
    margin-top: 0.5rem;
  }

  .developers pre {
    overflow-x: auto;
    border-radius: 0.45rem;
    background: #0f1720;
    color: #f7fbff;
    padding: 0.75rem;
  }

  .developers__columns {
    columns: 2 14rem;
    margin: 0;
    padding-left: 1.2rem;
  }
</style>
