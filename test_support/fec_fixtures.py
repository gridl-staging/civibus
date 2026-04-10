from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fec_sample_response.json"


def load_fixture_results() -> list[dict]:
    with open(FIXTURE_PATH) as fixture_file:
        return json.load(fixture_file)["results"]


def clone_with_unique_sub_id(record: dict) -> dict:
    cloned_record = dict(record)
    cloned_record["sub_id"] = f"{record['sub_id']}-{uuid4().hex}"
    return cloned_record
