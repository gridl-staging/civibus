<script lang="ts">
  import { env } from "$env/dynamic/public";
  import { page } from "$app/stores";
  import { APP_SHELL } from "$lib/config/app";
  import { buildDataSourcesRoutePath } from "$lib/metadata/contract";
  import SeoHead from "$lib/seo/SeoHead.svelte";
  import { buildSeoHeadModel } from "$lib/seo/head";
  import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";
  import type { PageData } from "./$types";

  export let data: PageData;

  const routeMetadata = APP_SHELL.staticRoutes.dataSources;

  $: canonicalPageUrl = new URL(buildDataSourcesRoutePath(), $page.url);
  $: headModel = buildSeoHeadModel({
    metadata: routeMetadata,
    ogType: "website",
    pageUrl: canonicalPageUrl,
    publicOrigin: env.PUBLIC_ORIGIN
  });
</script>

<SeoHead {headModel} />

<section class="card" aria-label="Data sources">
  <h2>Data sources</h2>

  {#if data.dataSources.length === 0}
    <p>No runtime data-source rows are available right now.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Domain</th>
          <th scope="col">Jurisdiction</th>
          <th scope="col">Update frequency</th>
          <th scope="col">Record count</th>
          <th scope="col">Last pull status</th>
          <th scope="col">Last pull at</th>
          <th scope="col">Latest source pull</th>
          <th scope="col">Latest source record</th>
        </tr>
      </thead>
      <tbody>
        {#each data.dataSources as row (row.data_source_id)}
          {@const sourceUrl = sanitizeExternalUrl(row.source_url)}
          {@const latestSourceRecordUrl = sanitizeExternalUrl(row.latest_source_record_url)}
          <tr>
            <td>
              {#if sourceUrl}
                <a href={sourceUrl}>{row.name}</a>
              {:else}
                {row.name}
              {/if}
            </td>
            <td>{row.domain}</td>
            <td>{row.jurisdiction ?? "(none)"}</td>
            <td>{row.update_frequency ?? "unknown"}</td>
            <td>{row.record_count ?? "unknown"}</td>
            <td>{row.last_pull_status ?? "unknown"}</td>
            <td>{row.last_pull_at ?? "unknown"}</td>
            <td>{row.latest_source_pull_date ?? "unknown"}</td>
            <td>
              {#if latestSourceRecordUrl}
                <a href={latestSourceRecordUrl}>
                  {row.latest_source_record_key ?? latestSourceRecordUrl}
                </a>
              {:else}
                {row.latest_source_record_key ?? "unknown"}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
