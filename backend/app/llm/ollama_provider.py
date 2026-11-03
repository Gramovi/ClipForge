"""Ollama (local models) provider over its HTTP API."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.llm.base import LLMConfigError, LLMError, LLMProvider, LLMResult, LLMTransientError

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str, model: str, num_ctx: int = 16384, timeout: float = 900,
                 auto_pull: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.auto_pull = auto_pull
        self._pulled = False

    def _pull(self) -> None:
        log.info("Pulling Ollama model %s", self.model)
        try:
            with httpx.stream("POST", f"{self.base_url}/api/pull", json={"model": self.model},
                              timeout=httpx.Timeout(3600, connect=10)) as r:
                for line in r.iter_lines():
                    if line and '"error"' in line:
                        raise LLMConfigError(f"Model {self.model} nelze stáhnout: {json.loads(line)['error']}")
        except httpx.HTTPError as e:
            raise LLMConfigError(f"Stažení modelu {self.model} selhalo: {e}") from e
        self._pulled = True

    def complete_json(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000) -> LLMResult:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,  # structured outputs (Ollama >= 0.5)
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_ctx": self.num_ctx, "temperature": 0.2, "num_predict": max_tokens},
        }
        for attempt in range(2):
            try:
                r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=httpx.Timeout(self.timeout, connect=10))
            except httpx.ConnectError as e:
                raise LLMConfigError(
                    f"Ollama na adrese {self.base_url} neběží. Spusťte ji (docker compose --profile ollama up) "
                    "nebo nastavte OLLAMA_BASE_URL."
                ) from e
            except httpx.TimeoutException as e:
                raise LLMTransientError("Lokální model neodpověděl včas.") from e
            except httpx.HTTPError as e:
                raise LLMTransientError(f"Chyba spojení s Ollama: {e}") from e
            if r.status_code == 404 and attempt == 0 and self.auto_pull and not self._pulled:
                self._pull()
                continue
            if r.status_code == 404:
                raise LLMConfigError(f"Model {self.model} není v Ollama k dispozici. Spusťte: ollama pull {self.model}")
            if r.status_code >= 500:
                raise LLMTransientError(f"Ollama vrátila chybu {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                raise LLMError(f"Ollama odmítla požadavek ({r.status_code}): {r.text[:200]}")
            data = r.json()
            return LLMResult(
                text=str(data.get("message", {}).get("content", "")),
                input_tokens=int(data.get("prompt_eval_count") or 0),
                output_tokens=int(data.get("eval_count") or 0),
                stop_reason=str(data.get("done_reason") or ""),
            )
        raise LLMError("Ollama: neočekávaný stav")

    def check(self) -> dict[str, Any]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
        except httpx.HTTPError:
            return {"ok": False, "message": f"Ollama na {self.base_url} není dostupná."}
        names = {m.get("name") for m in r.json().get("models", [])}
        if self.model in names or f"{self.model}:latest" in names:
            return {"ok": True, "message": f"Ollama běží, model {self.model} je stažený."}
        return {"ok": True, "message": f"Ollama běží; model {self.model} se stáhne při prvním použití."}
