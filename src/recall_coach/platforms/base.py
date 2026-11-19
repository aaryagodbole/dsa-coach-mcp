from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import PlatformInfo, Problem, Profile


class PlatformError(Exception):
    """The platform answered, but not with what was asked for."""


class UserNotFoundError(PlatformError):
    pass


class ProblemNotFoundError(PlatformError):
    pass


@runtime_checkable
class PlatformAdapter(Protocol):
    """Translates one platform's API into the shared models. Adapters hold no
    judgement: which topic is weak or which problem comes next is the caller's call."""

    name: str
    # The web hosts this platform's problems live on.
    hosts: tuple[str, ...]

    async def describe(self) -> PlatformInfo: ...

    async def profile(self, handle: str) -> Profile: ...

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]: ...

    async def problem(self, problem_id: str) -> Problem:
        """The problem as the platform describes it; ProblemNotFoundError if it has none."""
        ...
