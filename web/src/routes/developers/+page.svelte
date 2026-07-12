<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";

  const routeMetadata = APP_SHELL.staticRoutes.developers;
  const samplePersonId = "11111111-1111-1111-1111-111111111111";
  const sampleCandidateId = "44444444-4444-4444-4444-444444444444";
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
  const endpointReferences = [
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
      label: "GET /api/public/v1/federal/export.json",
      parameters: ["none"],
      curl: `${shellBaseGuard} && curl "\${CIVIBUS_PUBLIC_API_BASE}/api/public/v1/federal/export.json"`,
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
      sampleLabel: "Sample CSV",
      sampleBody: `${csvColumns.join(",")}
${samplePersonId},Sample Official,true,${sampleCandidateId},125000.00,100000.00,25000.00,45000.00,fec_weball,5000.00,0.00,2,0,https://www.fec.gov/data/candidate/H4NC00000/`
    }
  ] as const;
  const migrationMappings = [
    ["Federal official directory", endpointReferences[0].label],
    ["Current federal member money summary", endpointReferences[1].label],
    ["Bulk federal money export", endpointReferences[2].label],
    ["Spreadsheet-friendly federal money export", endpointReferences[3].label]
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
      <h5>Curl</h5>
      <pre><code>{endpoint.curl}</code></pre>
      <h5>{endpoint.sampleLabel}</h5>
      <pre><code>{endpoint.sampleBody}</code></pre>
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
        <th scope="col">Need</th>
        <th scope="col">Civibus endpoint</th>
      </tr>
    </thead>
    <tbody>
      {#each migrationMappings as [need, endpoint]}
        <tr>
          <td>{need}</td>
          <td><code>{endpoint}</code></td>
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

  <h3>Rate limits and cache</h3>
  <p>
    Public API requests are rate limited. Public responses use
    <code>Cache-Control: public, max-age=900</code>.
  </p>

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
