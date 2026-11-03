"""Eval backends. Each speaks one wire format behind the AgentBackend interface; add a
module for a new format, nothing else changes."""

from evals.backends.base import (
    AgentBackend,
    BackendError,
    Conversation,
    ToolOutcome,
    ToolRequest,
    ToolSpec,
    Turn,
    Usage,
)
from evals.backends.chat_completions import ChatCompletionsBackend

__all__ = [
    "AgentBackend",
    "BackendError",
    "ChatCompletionsBackend",
    "Conversation",
    "ToolOutcome",
    "ToolRequest",
    "ToolSpec",
    "Turn",
    "Usage",
]
