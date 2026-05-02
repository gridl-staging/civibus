"""NC committee registry row model for CFOrgLkup discovery results.

Source-specific pre-ingest state — not a shared domain model. Maps directly
to the fields returned by the CFOrgLkup search endpoint and stored in
cf.nc_committee_registry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NCCommitteeStatus = Literal[
    "ACTIVE (EXEMPT)",
    "ACTIVE (NON-EXEMPT)",
    "CLOSED",
    "CLOSED (PENDING)",
    "CONDITIONALLY CLOSED",
    "INACTIVE",
    "TERMINATED",
]

NC_COMMITTEE_STATUS_VALUES: set[str] = set(NCCommitteeStatus.__args__)


class NCCommitteeRegistryRow(BaseModel, frozen=True, extra="forbid"):
    org_group_id: int = Field(gt=0)
    sboe_id: str
    committee_name: str
    status_desc: NCCommitteeStatus
    old_id: str | None = None
    candidate_name: str | None = None
