import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import GraphViewer from "./GraphViewer.svelte";
import type { GraphElementDefinition } from "./transform";

const SUBJECT_NODE: GraphElementDefinition = {
  data: {
    id: "person:p-001",
    label: "Jane Doe",
    entityId: "p-001",
    entityType: "person",
    isSubject: true,
    href: null
  }
};

const NEIGHBOR_NODE: GraphElementDefinition = {
  data: {
    id: "org:o-001",
    label: "Action PAC",
    entityId: "o-001",
    entityType: "org",
    isSubject: false,
    href: "/org/o-001"
  }
};

const EDGE: GraphElementDefinition = {
  data: {
    id: "edge:0:person:p-001:org:o-001:outbound:contributed_to",
    source: "person:p-001",
    target: "org:o-001",
    label: "contributed_to"
  }
};

const ELEMENTS_WITH_NEIGHBOR: GraphElementDefinition[] = [SUBJECT_NODE, NEIGHBOR_NODE, EDGE];
const DESCRIBED_BY_ID = "entity-neighbor-list";
const SUBJECT_NAME = "Jane Doe";

describe("GraphViewer SSR", () => {
  it("renders container with tabindex, role=img, aria-label, and aria-describedby", () => {
    const rendered = render(GraphViewer, {
      props: {
        elements: ELEMENTS_WITH_NEIGHBOR,
        totalCount: 1,
        returnedCount: 1,
        subjectName: SUBJECT_NAME,
        describedById: DESCRIBED_BY_ID
      }
    });

    expect(rendered.body).toContain('tabindex="0"');
    expect(rendered.body).toContain('role="img"');
    expect(rendered.body).toContain(`aria-label="Graph of ${SUBJECT_NAME} with 1 relationship"`);
    expect(rendered.body).toContain(`aria-describedby="${DESCRIBED_BY_ID}"`);
  });

  it("renders keyboard status element with role=status", () => {
    const rendered = render(GraphViewer, {
      props: {
        elements: ELEMENTS_WITH_NEIGHBOR,
        totalCount: 1,
        returnedCount: 1,
        subjectName: SUBJECT_NAME,
        describedById: DESCRIBED_BY_ID
      }
    });

    expect(rendered.body).toContain('role="status"');
  });

  it("renders nothing when hasNeighbors is false (single subject element)", () => {
    const rendered = render(GraphViewer, {
      props: {
        elements: [SUBJECT_NODE],
        totalCount: 0,
        returnedCount: 0,
        subjectName: SUBJECT_NAME,
        describedById: DESCRIBED_BY_ID
      }
    });

    expect(rendered.body).not.toContain('role="img"');
    expect(rendered.body).not.toContain('tabindex="0"');
    expect(rendered.body).not.toContain('role="status"');
    expect(rendered.body).not.toContain("graph-viewer");
  });

  it("includes correct neighbor count in aria-label for multiple neighbors", () => {
    const secondNeighbor: GraphElementDefinition = {
      data: {
        id: "committee:c-001",
        label: "Campaign Fund",
        entityId: "c-001",
        entityType: "committee",
        isSubject: false,
        href: "/committee/c-001"
      }
    };
    const secondEdge: GraphElementDefinition = {
      data: {
        id: "edge:1:person:p-001:committee:c-001:outbound:member_of",
        source: "person:p-001",
        target: "committee:c-001",
        label: "member_of"
      }
    };

    const rendered = render(GraphViewer, {
      props: {
        elements: [...ELEMENTS_WITH_NEIGHBOR, secondNeighbor, secondEdge],
        totalCount: 2,
        returnedCount: 2,
        subjectName: SUBJECT_NAME,
        describedById: DESCRIBED_BY_ID
      }
    });

    expect(rendered.body).toContain(`aria-label="Graph of ${SUBJECT_NAME} with 2 relationships"`);
  });
});
