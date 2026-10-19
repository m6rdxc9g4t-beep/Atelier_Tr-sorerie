"""Client minimal pour l'API locale d'Ollama (http://localhost:11434).

Uniquement la bibliothèque standard, et les proxys système sont volontairement
ignorés : les requêtes partent directement vers la machine locale, jamais ailleurs.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class OllamaError(RuntimeError):
    """Ollama injoignable, modèle absent ou réponse inattendue."""


class OllamaClient:
    local = True
    label = "Ollama (local)"

    def __init__(self, base_url: str, model: str, timeout: float = 90):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # ProxyHandler({}) : on n'utilise jamais HTTP(S)_PROXY pour parler à l'IA locale
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST" if data else "GET",
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise OllamaError(f"Ollama a répondu {exc.code} : {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise OllamaError(
                f"Ollama est injoignable sur {self.base_url}. Lancez-le avec « ollama serve »."
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Réponse d'Ollama illisible (JSON invalide).") from exc

    # ------------------------------------------------------------------ API publique

    def list_models(self) -> list[str]:
        data = self._request("/api/tags", timeout=3)
        return [m.get("name", "") for m in data.get("models", [])]

    def status(self) -> dict:
        """État pour /api/health et la pastille de la sidebar. Ne lève jamais."""
        try:
            models = self.list_models()
        except OllamaError as exc:
            return {"available": False, "model": self.model, "models": [], "error": str(exc)}
        installed = any(m == self.model or m.split(":")[0] == self.model for m in models)
        return {
            "available": True,
            "model": self.model,
            "model_installed": installed,
            "models": models,
            "error": None if installed else f"Modèle « {self.model} » absent : ollama pull {self.model}",
        }

    def chat(self, messages: list[dict], system: str | None = None, temperature: float = 0.3,
             max_tokens: int | None = None) -> str:
        """Envoie une conversation et renvoie la réponse texte complète (sans streaming)."""
        if system:
            messages = [{"role": "system", "content": system}, *messages]
        options = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        data = self._request(
            "/api/chat",
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": options,
            },
        )
        try:
            return data["message"]["content"].strip()
        except (KeyError, TypeError, AttributeError) as exc:
            raise OllamaError("Réponse d'Ollama inattendue (champ « message » manquant).") from exc
