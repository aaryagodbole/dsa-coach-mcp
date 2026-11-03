"""What every eval backend implements: carry one conversation with a model that can
call tools. Running the tools, grading and accounting live in evals.agent, the same for
every backend; a backend only speaks its provider's wire format."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


class BackendError(Exception):
    """The backend was misconfigured, or the model API answered outside its format."""


@dataclass(frozen=True)
class ToolRequest:
    id: str
    name: str
    arguments: dict[str, Any]
    # Set when the model's arguments could not be read; the call is then not run.
    error: str | None = None


@dataclass(frozen=True)
class ToolOutcome:
    request: ToolRequest
    text: str
    is_error: bool


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, other: Usage) -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write


@dataclass(frozen=True)
class Turn:
    text: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    refused: bool = False


class Conversation(Protocol):
    async def next_turn(self) -> Turn:
        """Ask the model for its next turn, given everything so far."""
        ...

    def add_tool_results(self, outcomes: Sequence[ToolOutcome]) -> None:
        """Hand back the results of every tool requested in the last turn."""
        ...


class AgentBackend(Protocol):
    name: str

    def start(self, system: str, prompt: str, tools: Sequence[ToolSpec]) -> Conversation: ...
