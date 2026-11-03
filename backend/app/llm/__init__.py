"""LLM provider factory. Switch providers with ``LLM_PROVIDER`` in .env."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import LLMConfigError, LLMError, LLMProvider, LLMRefusalError, LLMResult, LLMTransientError

__all__ = [
    "LLMConfigError", "LLMError", "LLMProvider", "LLMRefusalError", "LLMResult", "LLMTransientError",
    "get_provider",
]


def get_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if s.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.anthropic_effort, s.llm_timeout_seconds)
    if s.llm_provider == "ollama":
        from app.llm.ollama_provider import OllamaProvider

        # local models on CPU can need much longer per window than hosted APIs
        return OllamaProvider(s.ollama_base_url, s.ollama_model, s.ollama_num_ctx, max(s.llm_timeout_seconds, 1800))
    raise LLMConfigError(f"Neznámý LLM_PROVIDER: {s.llm_provider} (povoleno: anthropic, ollama)")
