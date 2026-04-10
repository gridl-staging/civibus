from __future__ import annotations

import pytest

from core.entity_resolution.splink_runtime import train_linker


def test_train_linker_tries_next_rule_when_first_has_no_pairs() -> None:
    class FakeTraining:
        def __init__(self) -> None:
            self.u_calls: list[int] = []
            self.em_calls: list[object] = []

        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            self.u_calls.append(max_pairs)

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: object,
        ) -> None:
            self.em_calls.append(blocking_rule)
            if blocking_rule == "rule_a":
                raise RuntimeError("Training rule `rule_a` resulted in no record pairs.")

    class FakeLinker:
        def __init__(self) -> None:
            self.training = FakeTraining()

    linker = FakeLinker()
    train_linker(linker, ["rule_a", "rule_b"])

    assert linker.training.u_calls == [1_000_000]
    assert linker.training.em_calls == ["rule_a", "rule_b"]


def test_train_linker_raises_for_non_no_pair_training_errors() -> None:
    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            assert max_pairs == 1_000_000

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: object,
        ) -> None:
            raise RuntimeError("unexpected training failure")

    class FakeLinker:
        def __init__(self) -> None:
            self.training = FakeTraining()

    with pytest.raises(RuntimeError, match="unexpected training failure"):
        train_linker(FakeLinker(), ["rule_a"])
