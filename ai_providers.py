"""Choix du moteur d'IA selon les Paramètres : Ollama (local) ou Claude.

Chaque moteur expose : `local` (bool), `label`, `model`, `chat(messages, system, max_tokens)`
et lève une erreur dérivée de `AIErrors` en cas de problème.
"""
from __future__ import annotations

from claude_client import ClaudeClient, ClaudeError
from ollama_client import OllamaClient, OllamaError

AIErrors = (OllamaError, ClaudeError)


def build_provider(settings: dict, config: dict):
    if settings["ai_provider"] == "claude":
        mode = settings["claude_mode"]
        return ClaudeClient(
            mode=mode,
            model=settings["claude_cli_model"] if mode == "cli" else settings["claude_api_model"],
            api_key=settings["anthropic_api_key"] or None,
            cli_path=settings["claude_cli_path"] or None,
        )
    return OllamaClient(config["OLLAMA_URL"], settings["ollama_model"], config["OLLAMA_TIMEOUT"])


def provider_status(provider, deep: bool = False) -> dict:
    """État normalisé pour l'interface : {provider, label, model, local, ready, error, ...}."""
    if isinstance(provider, OllamaClient):
        raw = provider.status()
        return {
            "provider": "ollama", "label": provider.label, "model": provider.model, "local": True,
            "ready": raw["available"] and raw.get("model_installed", False),
            "error": raw["error"], "models": raw["models"],
        }
    return provider.status(deep=deep)
