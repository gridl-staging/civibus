<script lang="ts">
  type BreadcrumbCrumb = {
    label: string;
    href?: string;
  };

  export let crumbs: BreadcrumbCrumb[];
</script>

<nav aria-label="Breadcrumb">
  <ol class="breadcrumb">
    {#each crumbs as crumb, index}
      <li>
        {#if crumb.href && index < crumbs.length - 1}
          <a href={crumb.href}>{crumb.label}</a>
        {:else}
          <span aria-current="page">{crumb.label}</span>
        {/if}
      </li>
    {/each}
  </ol>
</nav>

<style>
  .breadcrumb {
    margin: 0 0 0.8rem;
    padding: 0;
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }

  .breadcrumb li {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
  }

  .breadcrumb li:not(:last-child)::after {
    content: "/";
    color: #4b6983;
  }
</style>
