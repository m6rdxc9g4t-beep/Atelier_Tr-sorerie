"""Paramètres de l'application, stockés dans la table `settings` (clé / valeur texte).

La clé API Claude est conservée dans la base locale et n'est jamais renvoyée en entier.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .validation import Validator

PROVIDERS = ("ollama", "claude")
CLAUDE_MODES = ("cli", "api")
CLI_MODELS = ("sonnet", "opus", "haiku")

DEFAULTS = {
    "ai_provider": "ollama",
    "ollama_model": "",          # vide = OLLAMA_MODEL du fichier .env
    "claude_mode": "cli",
    "claude_cli_model": "sonnet",
    "claude_api_model": "claude-sonnet-5-5",
    "claude_cli_path": "",       # vide = détection automatique
    "anthropic_api_key": "",
}


def _raw(conn: sqlite3.Connection) -> dict[str, str]:
    values = dict(DEFAULTS)
    values.update({k: v for k, v in conn.execute("SELECT key, value FROM settings") if k in DEFAULTS and v is not None})
    return values


def effective(conn: sqlite3.Connection, config: dict) -> dict:
    """Paramètres complets (clé API comprise) pour construire le moteur d'IA. Usage interne."""
    values = _raw(conn)
    values["ollama_model"] = values["ollama_model"] or config["OLLAMA_MODEL"]
    return values


def get_settings(conn: sqlite3.Connection, config: dict) -> dict:
    """Paramètres affichables : la clé API est masquée."""
    values = effective(conn, config)
    key = values.pop("anthropic_api_key")
    values["anthropic_api_key_set"] = bool(key)
    values["anthropic_api_key_hint"] = f"{key[:7]}…{key[-4:]}" if len(key) > 12 else ("••••" if key else "")
    values["ollama_url"] = config["OLLAMA_URL"]
    values["database_path"] = str(config["DATABASE_PATH"])
    return values


def update_settings(conn: sqlite3.Connection, config: dict, data: dict | None) -> dict:
    v = Validator(data, partial=True)
    v.choice("ai_provider", PROVIDERS)
    v.choice("claude_mode", CLAUDE_MODES)
    v.text("ollama_model", max_len=100)
    v.choice("claude_cli_model", CLI_MODELS)
    v.text("claude_api_model", max_len=100)
    v.text("claude_cli_path", max_len=500)
    if (data or {}).get("anthropic_api_key") is None and "anthropic_api_key" in (data or {}):
        v.clean["anthropic_api_key"] = ""  # null = effacer la clé
    else:
        v.text("anthropic_api_key", max_len=300)
    key = v.clean.get("anthropic_api_key")
    if key and not key.startswith("sk-"):
        v.errors["anthropic_api_key"] = "Clé invalide : elle commence par « sk- » (Claude Console)."
    path = v.clean.get("claude_cli_path")
    if path:
        expanded = Path(path).expanduser()
        if not expanded.is_file() or not os.access(expanded, os.X_OK):
            v.errors["claude_cli_path"] = "Aucun exécutable à cet emplacement."
    clean = v.result()
    if "claude_api_model" in clean and not clean["claude_api_model"]:
        clean["claude_api_model"] = DEFAULTS["claude_api_model"]
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [(k, "" if val is None else str(val)) for k, val in clean.items()],
    )
    conn.commit()
    return get_settings(conn, config)

