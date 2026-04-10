import { describe, expect, it } from "vitest";
import { classifyGraphNeighborRoute } from "$lib/entity-detail/contract";
import { buildNeighborTitle } from "$lib/entity-detail/presentation";
import type { GraphNeighbor } from "$lib/entity-detail/contract";
import { buildGraphElements } from "./transform";

// Reusable test constants
const SUBJECT_PERSON_TYPE = "person";
const SUBJECT_PERSON_ID = "p-001";
const SUBJECT_PERSON_NAME = "Jane Doe";

const SUBJECT_ORG_TYPE = "org";
const SUBJECT_ORG_ID = "o-001";
const SUBJECT_ORG_NAME = "Action PAC";

function makeNeighbor(overrides: Partial<GraphNeighbor> = {}): GraphNeighbor {
	return {
		entity_type: "person",
		entity_id: "p-002",
		name: "Bob Smith",
		relationship_type: "contributed_to",
		direction: "outbound",
		...overrides
	};
}

describe("buildGraphElements", () => {
	it("returns subject center node plus one neighbor node and one edge for a single neighbor", () => {
		const neighbor = makeNeighbor();
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[neighbor]
		);

		// Should have 3 elements: subject node, neighbor node, edge
		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		const edges = elements.filter((el) => "source" in (el.data as Record<string, unknown>));

		expect(nodes).toHaveLength(2);
		expect(edges).toHaveLength(1);

		// Subject node
		const subjectNode = nodes.find(
			(n) => (n.data as Record<string, unknown>).entityId === SUBJECT_PERSON_ID
		);
		expect(subjectNode).toBeDefined();
		expect((subjectNode!.data as Record<string, unknown>).label).toBe(SUBJECT_PERSON_NAME);
		expect((subjectNode!.data as Record<string, unknown>).isSubject).toBe(true);

		// Neighbor node — label must match buildNeighborTitle parity
		const neighborNode = nodes.find(
			(n) => (n.data as Record<string, unknown>).entityId === "p-002"
		);
		expect(neighborNode).toBeDefined();
		expect((neighborNode!.data as Record<string, unknown>).label).toBe(
			buildNeighborTitle(neighbor)
		);

		// Neighbor node href must match classifyGraphNeighborRoute parity
		const route = classifyGraphNeighborRoute(neighbor);
		expect((neighborNode!.data as Record<string, unknown>).href).toBe(route.href);
	});

	it("sets correct href for routable entity types and null for non-routable types", () => {
		const routableNeighbor = makeNeighbor({ entity_type: "org", entity_id: "o-100", name: "Test Org" });
		const nonRoutableNeighbor = makeNeighbor({
			entity_type: "filing",
			entity_id: "f-999",
			name: "Filing X"
		});

		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[routableNeighbor, nonRoutableNeighbor]
		);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));

		const orgNode = nodes.find((n) => (n.data as Record<string, unknown>).entityId === "o-100");
		expect(orgNode).toBeDefined();
		expect((orgNode!.data as Record<string, unknown>).href).toBe(
			classifyGraphNeighborRoute(routableNeighbor).href
		);

		const filingNode = nodes.find((n) => (n.data as Record<string, unknown>).entityId === "f-999");
		expect(filingNode).toBeDefined();
		expect((filingNode!.data as Record<string, unknown>).href).toBeNull();
	});

	it("returns only the subject node when neighbors array is empty", () => {
		const elements = buildGraphElements(
			SUBJECT_ORG_TYPE,
			SUBJECT_ORG_ID,
			SUBJECT_ORG_NAME,
			[]
		);

		expect(elements).toHaveLength(1);
		expect((elements[0].data as Record<string, unknown>).entityId).toBe(SUBJECT_ORG_ID);
		expect((elements[0].data as Record<string, unknown>).label).toBe(SUBJECT_ORG_NAME);
		expect((elements[0].data as Record<string, unknown>).isSubject).toBe(true);
	});

	it("uses entity_type + entity_id fallback when neighbor name is null", () => {
		const neighbor = makeNeighbor({ name: null, entity_type: "person", entity_id: "p-anon" });
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[neighbor]
		);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		const neighborNode = nodes.find(
			(n) => (n.data as Record<string, unknown>).entityId === "p-anon"
		);

		expect(neighborNode).toBeDefined();
		// Must match buildNeighborTitle null-name fallback
		expect((neighborNode!.data as Record<string, unknown>).label).toBe(
			buildNeighborTitle(neighbor)
		);
		expect((neighborNode!.data as Record<string, unknown>).label).toBe("person p-anon");
	});

	it("sets outbound edge direction: source = subject, target = neighbor", () => {
		const neighbor = makeNeighbor({ direction: "outbound" });
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[neighbor]
		);

		const edges = elements.filter((el) => "source" in (el.data as Record<string, unknown>));
		expect(edges).toHaveLength(1);
		expect((edges[0].data as Record<string, unknown>).source).toBe("person:p-001");
		expect((edges[0].data as Record<string, unknown>).target).toBe("person:p-002");
		expect((edges[0].data as Record<string, unknown>).label).toBe("contributed_to");
	});

	it("sets inbound edge direction: source = neighbor, target = subject", () => {
		const neighbor = makeNeighbor({
			direction: "inbound",
			entity_id: "p-003",
			relationship_type: "received_from"
		});
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[neighbor]
		);

		const edges = elements.filter((el) => "source" in (el.data as Record<string, unknown>));
		expect(edges).toHaveLength(1);
		expect((edges[0].data as Record<string, unknown>).source).toBe("person:p-003");
		expect((edges[0].data as Record<string, unknown>).target).toBe("person:p-001");
		expect((edges[0].data as Record<string, unknown>).label).toBe("received_from");
	});

	it("handles mixed routable and non-routable neighbors with correct labels", () => {
		const neighbors: GraphNeighbor[] = [
			makeNeighbor({ entity_type: "person", entity_id: "p-100", name: "Alice" }),
			makeNeighbor({ entity_type: "committee", entity_id: "c-200", name: "Save the Whales PAC" }),
			makeNeighbor({ entity_type: "filing", entity_id: "f-300", name: null, direction: "inbound" })
		];

		const elements = buildGraphElements(
			SUBJECT_ORG_TYPE,
			SUBJECT_ORG_ID,
			SUBJECT_ORG_NAME,
			neighbors
		);

		// 1 subject + 3 neighbors + 3 edges = 7
		expect(elements).toHaveLength(7);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		expect(nodes).toHaveLength(4);

		// Verify each neighbor label matches buildNeighborTitle
		for (const neighbor of neighbors) {
			const node = nodes.find(
				(n) => (n.data as Record<string, unknown>).entityId === neighbor.entity_id
			);
			expect(node).toBeDefined();
			expect((node!.data as Record<string, unknown>).label).toBe(
				buildNeighborTitle(neighbor)
			);
		}
	});

	it("reuses one node when multiple relationships point to the same neighbor entity", () => {
		const repeatedEntityId = "p-dup";
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[
				makeNeighbor({ entity_id: repeatedEntityId, relationship_type: "SAME_AS" }),
				makeNeighbor({ entity_id: repeatedEntityId, relationship_type: "POSSIBLE_MATCH" })
			]
		);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		const edges = elements.filter((el) => "source" in (el.data as Record<string, unknown>));
		const duplicateNeighborNodes = nodes.filter(
			(node) => (node.data as Record<string, unknown>).entityId === repeatedEntityId
		);

		expect(nodes).toHaveLength(2);
		expect(duplicateNeighborNodes).toHaveLength(1);
		expect(edges).toHaveLength(2);
		expect(edges.map((edge) => (edge.data as Record<string, unknown>).label)).toEqual([
			"SAME_AS",
			"POSSIBLE_MATCH"
		]);
	});

	it("upgrades a deduplicated node label when a later relationship provides the neighbor name", () => {
		const repeatedEntityId = "p-later-name";
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[
				makeNeighbor({ entity_id: repeatedEntityId, name: null, relationship_type: "SAME_AS" }),
				makeNeighbor({
					entity_id: repeatedEntityId,
					name: "Resolved Name",
					relationship_type: "POSSIBLE_MATCH"
				})
			]
		);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		const deduplicatedNode = nodes.find(
			(node) => (node.data as Record<string, unknown>).entityId === repeatedEntityId
		);

		expect(deduplicatedNode).toBeDefined();
		expect((deduplicatedNode!.data as Record<string, unknown>).label).toBe("Resolved Name");
	});

	it("keeps a deduplicated node label when a later relationship regresses to fallback naming", () => {
		const repeatedEntityId = "p-no-downgrade";
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[
				makeNeighbor({ entity_id: repeatedEntityId, name: "Stable Name", relationship_type: "SAME_AS" }),
				makeNeighbor({ entity_id: repeatedEntityId, name: null, relationship_type: "POSSIBLE_MATCH" })
			]
		);

		const nodes = elements.filter((el) => !("source" in (el.data as Record<string, unknown>)));
		const deduplicatedNode = nodes.find(
			(node) => (node.data as Record<string, unknown>).entityId === repeatedEntityId
		);

		expect(deduplicatedNode).toBeDefined();
		expect((deduplicatedNode!.data as Record<string, unknown>).label).toBe("Stable Name");
	});

	it("uses typed graph node ids so different entity types can share the same raw entity_id", () => {
		const sharedEntityId = "shared-001";
		const elements = buildGraphElements(
			SUBJECT_PERSON_TYPE,
			SUBJECT_PERSON_ID,
			SUBJECT_PERSON_NAME,
			[
				makeNeighbor({ entity_type: "person", entity_id: sharedEntityId, name: "Shared Person" }),
				makeNeighbor({ entity_type: "org", entity_id: sharedEntityId, name: "Shared Org" })
			]
		);

		const typedNodeIds = elements
			.filter((el) => !("source" in (el.data as Record<string, unknown>)))
			.filter((node) => (node.data as Record<string, unknown>).entityId === sharedEntityId)
			.map((node) => (node.data as Record<string, unknown>).id);

		expect(new Set(typedNodeIds)).toEqual(new Set(["person:shared-001", "org:shared-001"]));
	});
});
