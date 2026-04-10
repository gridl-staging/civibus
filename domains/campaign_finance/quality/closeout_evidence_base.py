"""Shared closeout evidence behavior for federal and state modules.

Eliminates duplication of surfaced_anomalies(), to_json(), utc_now(),
and write_evidence_artifact() across fec_closeout_models.py and
state_closeout_models.py.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> datetime:
    """Return current UTC datetime for evidence timestamps."""
    return datetime.now(timezone.utc)


class CloseoutEvidenceMixin:
    """Shared serialization and anomaly-surfacing for closeout evidence models.

    Concrete Pydantic models must declare ``quality_report`` and
    ``known_limitations`` fields.
    """

    def surfaced_anomalies(self) -> list[dict[str, object]]:
        """Extract non-pass checks and known limitations into a flat anomaly list."""
        anomalies: list[dict[str, object]] = []
        for summary in self.quality_report.summaries:  # type: ignore[attr-defined]
            for check in summary.check_results:
                if check.status == "pass":
                    continue
                anomalies.append(
                    {
                        "jurisdiction": summary.jurisdiction,
                        "name": check.name,
                        "status": check.status,
                        "message": check.message,
                        "details": check.details,
                    }
                )
        anomalies.extend(deepcopy(self.known_limitations))  # type: ignore[attr-defined]
        return anomalies

    def to_json(self) -> str:
        """Serialize deterministic closeout JSON for stage-gating artifacts."""
        payload = self.model_dump(mode="json")  # type: ignore[attr-defined]
        payload["quality_report"] = json.loads(
            self.quality_report.to_json()  # type: ignore[attr-defined]
        )
        payload["anomalies"] = self.surfaced_anomalies()
        return json.dumps(payload, indent=2, sort_keys=False)


def write_evidence_artifact(evidence: CloseoutEvidenceMixin, artifact_path: Path) -> None:
    """Write evidence JSON artifact to disk."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(f"{evidence.to_json()}\n", encoding="utf-8")
