"""Anthropic (Claude) provider using the official SDK with structured JSON output."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.llm.base import LLMConfigError, LLMError, LLMProvider, LLMRefusalError, LLMResult, LLMTransientError

log = logging.getLogger(__name__)

KEY_HELP = (
    "Získejte klíč na https://console.anthropic.com/settings/keys, vložte ho do souboru .env "
    "jako ANTHROPIC_API_KEY=… a restartujte služby (docker compose up -d). "
    "Alternativně nastavte LLM_PROVIDER=ollama pro lokální model zdarma."
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str = "medium", timeout: float = 600) -> None:
        if not api_key:
            raise LLMConfigError("Chybí API klíč pro Anthropic (ANTHROPIC_API_KEY). " + KEY_HELP)
        self.model = model
        self.effort = effort
        # SDK retries 408/409/429/5xx itself; we add our own backoff on top in the moment finder.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)

    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000) -> LLMResult:
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},  # type: ignore[typeddict-item]
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMConfigError("API klíč pro Anthropic je neplatný. " + KEY_HELP) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMConfigError("API klíč nemá oprávnění k modelu " + self.model + ".") from e
        except anthropic.NotFoundError as e:
            raise LLMConfigError(
                f"Model „{self.model}“ neexistuje nebo k němu nemáte přístup. Zkontrolujte ANTHROPIC_MODEL."
            ) from e
        except anthropic.RateLimitError as e:
            ra = e.response.headers.get("retry-after") if e.response is not None else None
            raise LLMTransientError("Překročen limit požadavků Anthropic API.", float(ra) if ra else None) from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Anthropic API odmítlo požadavek: {e.message}") from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 or e.status_code == 529:
                raise LLMTransientError(f"Anthropic API je dočasně nedostupné ({e.status_code}).") from e
            raise LLMError(f"Chyba Anthropic API ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMTransientError("Nelze se spojit s Anthropic API (síťová chyba).") from e

        if msg.stop_reason == "refusal":
            raise LLMRefusalError("Model odmítl zpracovat tuto část přepisu.")
        text = "".join(b.text for b in msg.content if b.type == "text")
        return LLMResult(
            text=text,
            input_tokens=int(msg.usage.input_tokens or 0),
            output_tokens=int(msg.usage.output_tokens or 0),
            stop_reason=msg.stop_reason,
        )

    def check(self) -> dict[str, Any]:
        try:
            self.client.models.retrieve(self.model)
        except anthropic.AuthenticationError:
            return {"ok": False, "message": "API klíč je neplatný. " + KEY_HELP}
        except anthropic.NotFoundError:
            return {"ok": False, "message": f"Model {self.model} nebyl nalezen."}
        except anthropic.APIError as e:
            return {"ok": False, "message": f"Anthropic API nedostupné: {e}"}
        return {"ok": True, "message": "Připojeno k Anthropic API."}
