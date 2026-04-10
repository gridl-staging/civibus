import { classifyGraphNeighborRoute } from "$lib/entity-detail/contract";
import { buildNeighborTitle } from "$lib/entity-detail/presentation";
import type { GraphNeighbor } from "$lib/entity-detail/contract";

// Cytoscape-compatible element definition — avoids runtime dependency on cytoscape types
// in this pure transform module.
type GraphNodeData = {
	id: string;
	label: string;
	entityId: string;
	entityType: string;
	isSubject: boolean;
	href: string | null;
};

type GraphEdgeData = {
	id: string;
	source: string;
	target: string;
	label: string;
};

export type GraphElementDefinition = {
	data: GraphNodeData | GraphEdgeData;
};

function buildGraphNodeId(entityType: string, entityId: string): string {
	return `${entityType}:${entityId}`;
}

function buildFallbackNeighborTitle(entityType: string, entityId: string): string {
	return `${entityType} ${entityId}`;
}

function updateNeighborNodeLabelIfImproved(
	nodeData: GraphNodeData,
	neighbor: GraphNeighbor
): void {
	const fallbackTitle = buildFallbackNeighborTitle(neighbor.entity_type, neighbor.entity_id);
	const candidateTitle = buildNeighborTitle(neighbor);

	if (nodeData.label === fallbackTitle && candidateTitle !== fallbackTitle) {
		nodeData.label = candidateTitle;
	}
}

function buildSubjectNodeData(
	subjectEntityType: string,
	subjectEntityId: string,
	subjectName: string
): GraphNodeData {
	return {
		id: buildGraphNodeId(subjectEntityType, subjectEntityId),
		label: subjectName,
		entityId: subjectEntityId,
		entityType: subjectEntityType,
		isSubject: true,
		href: null
	};
}

function buildNeighborNodeData(neighbor: GraphNeighbor): GraphNodeData {
	return {
		id: buildGraphNodeId(neighbor.entity_type, neighbor.entity_id),
		label: buildNeighborTitle(neighbor),
		entityId: neighbor.entity_id,
		entityType: neighbor.entity_type,
		isSubject: false,
		href: classifyGraphNeighborRoute(neighbor).href
	};
}

function buildEdgeData(
	index: number,
	subjectNodeId: string,
	neighborNodeId: string,
	neighbor: GraphNeighbor
): GraphEdgeData {
	const isOutbound = neighbor.direction === "outbound";

	return {
		id: `edge:${index}:${subjectNodeId}:${neighborNodeId}:${neighbor.direction}:${neighbor.relationship_type}`,
		source: isOutbound ? subjectNodeId : neighborNodeId,
		target: isOutbound ? neighborNodeId : subjectNodeId,
		label: neighbor.relationship_type
	};
}

/**
 * Transforms raw graph neighbor data into Cytoscape-compatible element definitions.
 * Subject entity becomes the center node; each neighbor becomes a node with a directed edge.
 * Reuses buildNeighborTitle and classifyGraphNeighborRoute to stay in sync with the
 * textual neighbor list — single source of truth for labels and routability.
 */
export function buildGraphElements(
	subjectEntityType: string,
	subjectEntityId: string,
	subjectName: string,
	neighbors: GraphNeighbor[]
): GraphElementDefinition[] {
	const elements: GraphElementDefinition[] = [];
	const subjectNodeData = buildSubjectNodeData(subjectEntityType, subjectEntityId, subjectName);
	const subjectNodeId = subjectNodeData.id;
	const nodeDataById = new Map<string, GraphNodeData>();

	// Subject center node
	nodeDataById.set(subjectNodeId, subjectNodeData);
	elements.push({ data: subjectNodeData });

	for (const [index, neighbor] of neighbors.entries()) {
		const neighborNodeId = buildGraphNodeId(neighbor.entity_type, neighbor.entity_id);
		const existingNeighborNodeData = nodeDataById.get(neighborNodeId);

		// Graph payloads are edge lists, so multiple rows may point at the same entity.
		// Reuse a single typed node id per entity to avoid duplicate Cytoscape nodes.
		if (existingNeighborNodeData) {
			updateNeighborNodeLabelIfImproved(existingNeighborNodeData, neighbor);
		} else {
			const neighborNodeData = buildNeighborNodeData(neighbor);
			nodeDataById.set(neighborNodeId, neighborNodeData);
			elements.push({ data: neighborNodeData });
		}

		elements.push({ data: buildEdgeData(index, subjectNodeId, neighborNodeId, neighbor) });
	}

	return elements;
}
