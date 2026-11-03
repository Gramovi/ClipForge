"""Provider-agnostic LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """Base error; ``str(e)`` is a user-facing Czech message."""

    retryable: bool = False


class LLMConfigError(LLMError):
    """Missing/invalid API key, unknown model, provider unreachable... (not retryable)."""


class LLMTransientError(LLMError):
    """Rate limit, overload, network glitch (retryable with backoff)."""

    retryable = True

    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


class LLMRefusalError(LLMError):
    """The model declined the request (skip the window)."""


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class LLMProvider(ABC):
    name: str
    model: str
    #: local models produce less reliable JSON -> stricter repair/validation path
    is_local: bool = False

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000) -> LLMResult:
        """Return raw model text that should contain JSON matching *schema*."""

    @abstractmethod
    def check(self) -> dict[str, Any]:
        """Cheap configuration check for the settings page: {ok, message}."""
