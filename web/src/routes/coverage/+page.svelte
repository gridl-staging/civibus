<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import { buildCoverageRoutePath } from "$lib/metadata/contract";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import type { PageData } from "./$types";

  export let data: PageData;

  const routeMetadata = APP_SHELL.staticRoutes.coverage;

  $: canonicalPageUrl = new URL(buildCoverageRoutePath(), $page.url);
  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: canonicalPageUrl,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Coverage registry">
  <h2>Coverage registry</h2>

  {#if data.coverageRows.length === 0}
    <p>No runtime coverage rows are available right now.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th scope="col">Domain</th>
          <th scope="col">Jurisdiction</th>
          <th scope="col">Data sources</th>
          <th scope="col">Latest source pull date</th>
          <th scope="col">Latest data-source pull at</th>
        </tr>
      </thead>
      <tbody>
        {#each data.coverageRows as row (`${row.domain}:${row.jurisdiction ?? "null"}`)}
          <tr>
            <td>{row.domain}</td>
            <td>{row.jurisdiction ?? "(none)"}</td>
            <td>{row.data_source_count}</td>
            <td>{row.latest_source_pull_date ?? "unknown"}</td>
            <td>{row.latest_data_source_pull_at ?? "unknown"}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
