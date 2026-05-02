from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from core.db import get_connection
from domains.civics.tests.statewide_roster_stage5_support import (
    build_stage5_local_proof_payload,
    emit_stage5_local_proof_artifact,
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit the canonical Stage 5 local statewide roster proof artifact.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Override output path for the proof artifact. "
            "Defaults to docs/research/artifacts/2026_04_29_dwo_rosters/local/"
            "stage5_statewide_roster_local_proof.json"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    with get_connection() as connection:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = build_stage5_local_proof_payload(
                connection,
                Path(temp_dir),
                expect_clean_first_run=False,
            )
        emitted_path = emit_stage5_local_proof_artifact(payload=payload, output_path=args.output)
    print(f"Stage 5 statewide roster proof artifact emitted at {emitted_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
