from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from os import cpu_count


def resolve_worker_count(parallel: int) -> int:
    if parallel < 0:
        raise ValueError("parallel worker count must be zero or greater")
    if parallel == 0:
        return max(cpu_count() or 1, 1)
    return parallel


def ordered_map[T, R](function: Callable[[T], R], values: list[T], parallel: int) -> list[R]:
    """Map values concurrently while retaining input order."""
    workers = resolve_worker_count(parallel)
    if workers == 1 or len(values) < 2:
        return [function(value) for value in values]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(function, values))
