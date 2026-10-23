from __future__ import annotations

import httpx
import pytest

from dsa_coach_mcp import platforms
from dsa_coach_mcp.platforms import PlatformAdapter, build_adapters


async def test_every_adapter_is_keyed_by_its_own_name() -> None:
    async with httpx.AsyncClient() as client:
        registry = build_adapters(client)

    assert all(isinstance(a, PlatformAdapter) for a in registry.values())
    assert all(name == adapter.name for name, adapter in registry.items())


async def test_two_adapters_with_one_name_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    first = platforms.ADAPTERS[0]
    monkeypatch.setattr(platforms, "ADAPTERS", (first, first))

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="share a name"):
            build_adapters(client)
