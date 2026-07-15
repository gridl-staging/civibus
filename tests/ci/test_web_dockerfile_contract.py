"""Contract tests for the web container Dockerfile build-provenance stamp.

``web/Dockerfile`` is multi-stage. The build-provenance ARG/ENV pair MUST live
in the FINAL runtime stage: an ARG declared in the builder stage does NOT cross
the ``FROM`` boundary, so the runtime image would silently ship an empty/
``unknown`` SHA while every unit test stayed green. These tests parse the
Dockerfile into stages and assert placement, not mere substring presence.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "web/Dockerfile"


def _stages(dockerfile_text: str) -> list[list[str]]:
    """Split a Dockerfile into stages, one list of lines per ``FROM``."""
    stages: list[list[str]] = []
    for line in dockerfile_text.splitlines():
        if line.strip().startswith("FROM "):
            stages.append([])
        if stages:
            stages[-1].append(line)
    return stages


def test_web_dockerfile_exists() -> None:
    assert DOCKERFILE_PATH.is_file(), "web/Dockerfile must exist"


def test_web_dockerfile_stamps_build_provenance_in_final_stage() -> None:
    dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    stages = _stages(dockerfile_text)
    assert len(stages) >= 2, "web/Dockerfile is expected to be multi-stage"

    builder_stage = "\n".join(stages[0])
    final_stage = "\n".join(stages[-1])

    for arg_line in ("ARG CIVIBUS_GIT_SHA", "ARG CIVIBUS_BUILT_AT"):
        assert arg_line in final_stage, f"{arg_line} must live in the FINAL stage"
        assert arg_line not in builder_stage, f"{arg_line} must NOT live in the builder stage"

    assert "ENV CIVIBUS_GIT_SHA=$CIVIBUS_GIT_SHA" in final_stage
    assert "ENV CIVIBUS_BUILT_AT=$CIVIBUS_BUILT_AT" in final_stage

    # Placed AFTER the cached node_modules COPY so per-deploy SHA changes never
    # bust the ``npm ci`` layer, and BEFORE the runtime CMD.
    assert final_stage.index("COPY --from=builder /app/node_modules") < final_stage.index("ARG CIVIBUS_GIT_SHA")
    assert final_stage.index("ARG CIVIBUS_GIT_SHA") < final_stage.index("CMD")
