"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/tests/load/locustfile.py.
"""

from __future__ import annotations

import os
import random
from typing import Any

from locust import HttpUser, between, task


class CivibusUser(HttpUser):

    host = os.getenv("CIVIBUS_LOCUST_HOST", "http://127.0.0.1:8000")
    wait_time = between(1, 3)

    def on_start(self) -> None:
        api_key = self._resolve_public_api_key()
        if api_key:
            self.client.headers.update({"X-API-Key": api_key})

        self.committee_ids: list[str] = []
        self.candidate_ids: list[str] = []
        self.person_ids: list[str] = []
        self.org_ids: list[str] = []
        self.parcel_ids: list[str] = []

        self._discover_ids_from_transactions()
        self._discover_ids_from_parcels()

    def _resolve_public_api_key(self) -> str:
        configured_keys = os.getenv("CIVIBUS_API_KEYS", "")
        first_key = configured_keys.split(",")[0].strip() if configured_keys else ""
        return first_key

    def _add_discovered_id(self, bucket: list[str], raw_value: Any) -> None:
        if not raw_value:
            return
        entity_id = str(raw_value)
        if entity_id not in bucket:
            bucket.append(entity_id)

    def _response_json_list(self, response: Any) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _discover_ids_from_transactions(self) -> None:
        response = self.client.get("/v1/transactions", name="/v1/transactions")
        if response.status_code != 200:
            return

        for transaction in self._response_json_list(response):
            self._add_discovered_id(self.committee_ids, transaction.get("committee_id"))
            self._add_discovered_id(self.candidate_ids, transaction.get("recipient_candidate_id"))
            self._add_discovered_id(self.person_ids, transaction.get("contributor_person_id"))
            self._add_discovered_id(self.org_ids, transaction.get("contributor_organization_id"))

    def _discover_ids_from_parcels(self) -> None:
        response = self.client.get("/v1/parcels", name="/v1/parcels")
        if response.status_code != 200:
            return

        for parcel in self._response_json_list(response):
            self._add_discovered_id(self.parcel_ids, parcel.get("id"))

    def _choose_discovered_id(self, entity_ids: list[str]) -> str | None:
        if not entity_ids:
            return None
        return random.choice(entity_ids)

    def _get_entity_detail(self, entity_ids: list[str], path: str) -> None:
        entity_id = self._choose_discovered_id(entity_ids)
        if entity_id is None:
            return
        self.client.get(f"/v1/{path}/{entity_id}", name=f"/v1/{path}/{{id}}")

    # Pairs of (graph entity type label, id bucket) used by get_graph_relationships.
    _GRAPH_ENTITY_SOURCES: list[tuple[str, str]] = [
        ("person", "person_ids"),
        ("org", "org_ids"),
        ("committee", "committee_ids"),
        ("candidate", "candidate_ids"),
    ]

    @task
    def get_health(self) -> None:
        self.client.get("/health")

    @task
    def list_transactions(self) -> None:
        self.client.get("/v1/transactions")

    @task
    def list_parcels(self) -> None:
        self.client.get("/v1/parcels")

    @task
    def search_entities(self) -> None:
        self.client.get("/v1/search?q=ci", name="/v1/search?q=...")

    @task
    def get_committee_detail(self) -> None:
        self._get_entity_detail(self.committee_ids, "committees")

    @task
    def get_candidate_detail(self) -> None:
        self._get_entity_detail(self.candidate_ids, "candidates")

    @task
    def get_person_detail(self) -> None:
        self._get_entity_detail(self.person_ids, "person")

    @task
    def get_organization_detail(self) -> None:
        self._get_entity_detail(self.org_ids, "org")

    @task
    def get_parcel_detail(self) -> None:
        self._get_entity_detail(self.parcel_ids, "parcels")

    @task
    def get_graph_relationships(self) -> None:
        graph_targets = [
            (entity_type, entity_id)
            for entity_type, bucket_attr in self._GRAPH_ENTITY_SOURCES
            if (entity_id := self._choose_discovered_id(getattr(self, bucket_attr))) is not None
        ]
        if not graph_targets:
            return

        entity_type, entity_id = random.choice(graph_targets)
        self.client.get(
            f"/v1/graph/{entity_type}/{entity_id}/relationships",
            name="/v1/graph/{entity_type}/{entity_id}/relationships",
        )
