"""Packing operations into LLM batches under a token budget."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from d2u.schemas.docpage import Operation

# A rough, provider-independent estimate: about four characters per token.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class Batch:
    """Operations sent to the LLM in one `EnrichOperations` call."""

    index: int
    operations: list[Operation]


def estimate_tokens(op: Operation) -> int:
    """Approximate the prompt tokens an operation adds to a batch."""
    text = json.dumps(op.model_dump(mode="json"), ensure_ascii=False)
    return max(1, len(text) // CHARS_PER_TOKEN)


def build_batches(
    operations: list[Operation],
    *,
    group_of: Callable[[Operation], str],
    token_budget: int,
    max_operations: int,
) -> list[Batch]:
    """Group operations and pack the groups into batches.

    Groups are kept whole where they fit; a group too large for one batch is
    split in order. Groups appear in the order their first operation appears.
    An operation larger than the whole budget still gets a batch of its own.

    Args:
        operations: Operations in surface order.
        group_of: The adapter's grouping function.
        token_budget: Maximum estimated tokens per batch.
        max_operations: Maximum operations per batch.
    """
    groups: dict[str, list[Operation]] = {}
    for op in operations:
        groups.setdefault(group_of(op), []).append(op)

    chunks: list[list[Operation]] = []
    current: list[Operation] = []
    current_tokens = 0

    def close_current() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append(current)
        current, current_tokens = [], 0

    for group in groups.values():
        group_tokens = sum(estimate_tokens(op) for op in group)
        fits_in_one = len(group) <= max_operations and group_tokens <= token_budget
        if fits_in_one:
            if (
                len(current) + len(group) > max_operations
                or current_tokens + group_tokens > token_budget
            ):
                close_current()
            current.extend(group)
            current_tokens += group_tokens
            continue

        close_current()
        for op in group:
            tokens = estimate_tokens(op)
            if current and (
                len(current) >= max_operations or current_tokens + tokens > token_budget
            ):
                close_current()
            current.append(op)
            current_tokens += tokens
        close_current()
    close_current()

    return [Batch(index=index, operations=ops) for index, ops in enumerate(chunks)]
