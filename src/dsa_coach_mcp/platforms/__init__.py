"""Platform adapters, keyed by each adapter's own ``name``.

Adding a platform means writing one adapter and listing its class in ``ADAPTERS``;
nothing else in the package names a platform."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from .base import PlatformAdapter, PlatformError, UserNotFoundError
from .codeforces import CodeforcesAdapter
from .leetcode import LeetCodeAdapter

ADAPTERS: tuple[Callable[[httpx.AsyncClient], PlatformAdapter], ...] = (
    LeetCodeAdapter,
    CodeforcesAdapter,
)


def build_adapters(client: httpx.AsyncClient) -> dict[str, PlatformAdapter]:
    adapters = [make(client) for make in ADAPTERS]
    registry = {adapter.name: adapter for adapter in adapters}
    if len(registry) != len(adapters):
        raise ValueError("Two platform adapters share a name")
    return registry


__all__ = [
    "ADAPTERS",
    "PlatformAdapter",
    "PlatformError",
    "UserNotFoundError",
    "build_adapters",
]
