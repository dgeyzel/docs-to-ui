from d2u.generation.batching import build_batches, estimate_tokens
from d2u.schemas.docpage import Operation


def make_op(op_id: str, group: str, description: str = "") -> Operation:
    return Operation(
        id=op_id,
        kind="http",
        signature=op_id,
        group_hint=group,
        params=[],
        source_description=description or None,
    )


def batch_ids(batches: list) -> list[list[str]]:
    return [[op.id for op in batch.operations] for batch in batches]


def test_small_groups_are_packed_together_in_first_seen_order() -> None:
    ops = [make_op("a1", "a"), make_op("b1", "b"), make_op("a2", "a")]

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=10_000, max_operations=25
    )

    assert batch_ids(batches) == [["a1", "a2", "b1"]]
    assert [batch.index for batch in batches] == [0]


def test_groups_are_kept_whole_when_the_next_one_does_not_fit() -> None:
    ops = [make_op(f"a{i}", "a") for i in range(3)] + [
        make_op(f"b{i}", "b") for i in range(3)
    ]

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=10_000, max_operations=4
    )

    assert batch_ids(batches) == [["a0", "a1", "a2"], ["b0", "b1", "b2"]]


def test_oversized_groups_are_split_in_order() -> None:
    ops = [make_op(f"a{i}", "a") for i in range(5)]

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=10_000, max_operations=2
    )

    assert batch_ids(batches) == [["a0", "a1"], ["a2", "a3"], ["a4"]]


def test_token_budget_limits_batch_size() -> None:
    ops = [make_op(f"a{i}", f"g{i}", description="x" * 400) for i in range(4)]
    budget = estimate_tokens(ops[0]) * 2

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=budget, max_operations=25
    )

    assert batch_ids(batches) == [["a0", "a1"], ["a2", "a3"]]


def test_an_operation_larger_than_the_budget_gets_its_own_batch() -> None:
    ops = [make_op("big", "g", description="x" * 4000), make_op("small", "h")]

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=10, max_operations=25
    )

    assert batch_ids(batches) == [["big"], ["small"]]


def test_every_operation_lands_in_exactly_one_batch() -> None:
    ops = [make_op(f"op{i}", f"g{i % 7}") for i in range(60)]

    batches = build_batches(
        ops, group_of=lambda op: op.group_hint, token_budget=500, max_operations=5
    )

    ids = [op_id for batch in batch_ids(batches) for op_id in batch]
    assert sorted(ids) == sorted(op.id for op in ops)
    assert all(len(batch.operations) <= 5 for batch in batches)
