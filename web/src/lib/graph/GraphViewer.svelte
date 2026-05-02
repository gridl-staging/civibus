<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import type cytoscape from "cytoscape";
  import type { GraphElementDefinition } from "$lib/graph/transform";

  export let elements: GraphElementDefinition[];
  export let totalCount: number;
  export let returnedCount: number;
  export let subjectName: string;
  export let describedById: string;

  type CyNode = {
    data: (key: string) => unknown;
    select: () => void;
  };

  type CyInstance = {
    on: (
      eventName: string,
      selector: string,
      handler: (event: { target: CyNode }) => void
    ) => void;
    elements: () => { unselect: () => void };
    nodes: (selector?: string) => CyNode[];
    center: (node: CyNode) => void;
    destroy: () => void;
  };

  let containerEl: HTMLDivElement;
  let cyInstance: CyInstance | null = null;
  let loadError = false;
  let focusedIndex = -1;
  let statusText = "";

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
    },
    {
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#f59e0b",
        "background-color": "#fbbf24"
      }
    }
  ] as const satisfies cytoscape.StylesheetJson;

  $: isTruncated = totalCount > returnedCount;
  $: hasNeighbors = elements.length > 1;
  $: ariaLabel = `Graph of ${subjectName} with ${returnedCount} relationship${returnedCount === 1 ? "" : "s"}`;

  function getNavigableNodes(): CyNode[] {
    if (cyInstance === null) {
      return [];
    }
    return cyInstance.nodes("[!isSubject]");
  }

  function updateFocusedNode(index: number): void {
    if (cyInstance === null) {
      return;
    }

    const nodes = getNavigableNodes();
    if (nodes.length === 0) {
      return;
    }

    cyInstance.elements().unselect();
    const node = nodes[index];
    node.select();
    cyInstance.center(node);

    const label = node.data("label") as string;
    const href = node.data("href");
    const entityType = node.data("entityType") as string;

    if (typeof href === "string") {
      statusText = `${label} (${entityType}) — press Enter to open`;
    } else {
      statusText = `${label} (${entityType})`;
    }
  }

  function clearSelection(): void {
    if (cyInstance !== null) {
      cyInstance.elements().unselect();
    }
    focusedIndex = -1;
    statusText = "";
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (cyInstance === null) {
      return;
    }

    const nodes = getNavigableNodes();
    if (nodes.length === 0) {
      return;
    }

    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown": {
        event.preventDefault();
        focusedIndex = focusedIndex < nodes.length - 1 ? focusedIndex + 1 : 0;
        updateFocusedNode(focusedIndex);
        break;
      }
      case "ArrowLeft":
      case "ArrowUp": {
        event.preventDefault();
        focusedIndex = focusedIndex > 0 ? focusedIndex - 1 : nodes.length - 1;
        updateFocusedNode(focusedIndex);
        break;
      }
      case "Enter": {
        if (focusedIndex >= 0 && focusedIndex < nodes.length) {
          const href = nodes[focusedIndex].data("href");
          if (typeof href === "string") {
            event.preventDefault();
            goto(href);
          }
        }
        break;
      }
      case "Escape": {
        event.preventDefault();
        clearSelection();
        break;
      }
    }
  }

  function destroyGraph(): void {
    if (cyInstance !== null) {
      cyInstance.destroy();
      cyInstance = null;
    }
  }

  function attachNodeNavigation(cy: CyInstance): void {
    cy.on("tap", "node", (event: { target: CyNode }) => {
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

      attachNodeNavigation(cy as unknown as CyInstance);
      cyInstance = cy as unknown as CyInstance;
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
      <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
      <div
        class="graph-viewer__container"
        bind:this={containerEl}
        tabindex="0"
        role="img"
        aria-label={ariaLabel}
        aria-describedby={describedById}
        on:keydown={handleKeydown}
      ></div>
      <div class="graph-viewer__status" role="status" aria-live="polite">
        {statusText}
      </div>
    {/if}
  </div>
{/if}

<style>
  .graph-viewer__status {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
