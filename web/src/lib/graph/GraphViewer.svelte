<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import type cytoscape from "cytoscape";
  import type { GraphElementDefinition } from "$lib/graph/transform";

  export let elements: GraphElementDefinition[];
  export let totalCount: number;
  export let returnedCount: number;

  let containerEl: HTMLDivElement;
  let cyInstance: unknown = null;
  let loadError = false;

  const GRAPH_STYLE = [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "text-wrap": "wrap",
        "text-max-width": "100px",
        "font-size": "12px",
        "background-color": "#6b7b8d",
        color: "#1a1a1a",
        "text-valign": "bottom",
        "text-margin-y": 6,
        width: 28,
        height: 28
      }
    },
    {
      selector: "node[?isSubject]",
      style: {
        "background-color": "#274d68",
        "font-weight": "bold",
        width: 36,
        height: 36
      }
    },
    {
      selector: "edge",
      style: {
        label: "data(label)",
        "font-size": "10px",
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        "line-color": "#94a3b8",
        "target-arrow-color": "#94a3b8",
        color: "#64748b",
        "text-rotation": "autorotate",
        "text-margin-y": -8,
        width: 1.5
      }
    },
    {
      selector: "node[?href]",
      style: {
        "border-width": 2,
        "border-color": "#2563eb"
      }
    }
  ] as const satisfies cytoscape.StylesheetJson;

  $: isTruncated = totalCount > returnedCount;
  $: hasNeighbors = elements.length > 1;

  function destroyGraph(): void {
    if (cyInstance && typeof (cyInstance as { destroy: () => void }).destroy === "function") {
      (cyInstance as { destroy: () => void }).destroy();
      cyInstance = null;
    }
  }

  function attachNodeNavigation(
    cy: {
      on: (
        eventName: string,
        selector: string,
        handler: (event: { target: { data: (key: string) => unknown } }) => void
      ) => void;
    }
  ): void {
    cy.on("tap", "node", (event: { target: { data: (key: string) => unknown } }) => {
      const href = event.target.data("href");
      if (typeof href === "string") {
        goto(href);
      }
    });
  }

  async function initializeGraph(): Promise<void> {
    if (!hasNeighbors) {
      return;
    }

    try {
      const cytoscape = (await import("cytoscape")).default;
      const cy = cytoscape({
        container: containerEl,
        elements: elements as unknown as cytoscape.ElementDefinition[],
        style: GRAPH_STYLE,
        layout: {
          name: "concentric",
          concentric: (node: { data: (key: string) => unknown }) => (node.data("isSubject") ? 2 : 1),
          levelWidth: () => 1,
          minNodeSpacing: 60,
          animate: false
        },
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: false
      });

      attachNodeNavigation(cy);
      cyInstance = cy;
    } catch {
      loadError = true;
    }
  }

  onMount(() => {
    void initializeGraph();
  });

  onDestroy(destroyGraph);
</script>

{#if hasNeighbors}
  <div class="graph-viewer">
    {#if loadError}
      <p class="graph-viewer__fallback">Unable to load graph visualization.</p>
    {:else}
      {#if isTruncated}
        <p class="graph-viewer__truncation">
          Showing {returnedCount} of {totalCount} relationships
        </p>
      {/if}
      <div class="graph-viewer__container" bind:this={containerEl}></div>
    {/if}
  </div>
{/if}
