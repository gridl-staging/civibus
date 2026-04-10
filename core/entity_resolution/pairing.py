from __future__ import annotations

from uuid import UUID


def canonicalize_entity_pair(entity_id_a: UUID, entity_id_b: UUID) -> tuple[UUID, UUID]:
    if entity_id_a <= entity_id_b:
        return entity_id_a, entity_id_b
    return entity_id_b, entity_id_a
