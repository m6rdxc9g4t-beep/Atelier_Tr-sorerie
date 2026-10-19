"""Client Claude (Anthropic), utilisé uniquement si l'utilisateur l'active dans Paramètres.

Deux modes :
  - « cli » : appelle Claude Code en mode non interactif (`claude -p`), avec le compte
    Claude déjà connecté sur ce Mac. Aucun outil n'est autorisé : Claude ne peut ni lire
    de fichiers ni lancer de commandes, il répond seulement au texte reçu.
  - « api » : appelle l'API Claude avec une clé créée dans la Claude Console.

C'est le seul module qui envoie des données hors de la machine. Ce qu'il envoie est
construit par services/ai_context.py (version agrégée) : à revoir avec soin.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODELS = {"cli": "sonnet", "api": "claude-sonnet-5-5"}
MAX_TOKENS = 2000

# Emplacements habituels de Claude Code sur macOS : une application lancée par double-clic
# n'hérite pas du PATH du terminal.
_CANDIDATES = [
    "~/.claude/local/claude",
    "~/.local/bin/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    "~/.npm-global/bin/claude",
    "~/.bun/bin/claude",
]
_EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", str(Path("~/.local/bin").expanduser())]


class ClaudeError(RuntimeError):
    """Claude injoignable, non connecté, clé invalide ou réponse inattendue."""


def find_claude(explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit).expanduser()
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _env() -> dict:
    env = dict(os.environ)
    parts = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(parts + [p for p in _EXTRA_PATH if p not in parts])
    return env


def _flatten(messages: list[dict]) -> str:
    """`claude -p` reçoit un seul message : on y replace l'historique de la conversation."""
    *history, last = messages
    if not history:
        return last["content"]
    lines = ["Historique de la conversation (pour le contexte) :", ""]
    for m in history:
        who = "Utilisateur" if m["role"] == "user" else "Assistant"
        lines.append(f"{who} : {m['content']}")
        lines.append("")
    lines += ["Nouvelle question de l'utilisateur :", last["content"]]
    return "\n".join(lines)


class ClaudeClient:
    local = False

    def __init__(self, mode: str = "cli", model: str | None = None, api_key: str | None = None,
                 cli_path: str | None = None, timeout: float = 180):
        if mode not in ("cli", "api"):
            raise ValueError(f"Mode Claude inconnu : {mode}")
        self.mode = mode
        self.model = model or DEFAULT_MODELS[mode]
        self.api_key = api_key
        self.cli_path = cli_path
        self.timeout = timeout

    @property
    def label(self) -> str:
        return "Claude (abonnement)" if self.mode == "cli" else "Claude (clé API)"

    # ------------------------------------------------------------------ état

    def status(self, deep: bool = False) -> dict:
        """État du moteur. `deep` vérifie réellement la connexion (plus lent). Ne lève jamais."""
        base = {"provider": "claude", "mode": self.mode, "label": self.label, "model": self.model, "local": False}
        if self.mode == "api":
            if not self.api_key:
                return {**base, "ready": False, "error": "Aucune clé API Claude enregistrée (Paramètres)."}
            if not deep:
                return {**base, "ready": True, "error": None}
            try:
                self.chat([{"role": "user", "content": "Réponds seulement : OK"}], system="Test de connexion.", max_tokens=5)
            except ClaudeError as exc:
                return {**base, "ready": False, "error": str(exc)}
            return {**base, "ready": True, "error": None}

        path = find_claude(self.cli_path)
        base["cli_path"] = path
        if not path:
            hint = f"« {self.cli_path} » n'est pas un exécutable." if self.cli_path else \
                "Claude Code est introuvable sur ce Mac. Indiquez son chemin dans Paramètres (commande : which claude)."
            return {**base, "ready": False, "error": hint}
        if not deep:
            return {**base, "ready": True, "error": None}
        try:
            out = subprocess.run([path, "auth", "status"], capture_output=True, text=True, timeout=20, env=_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {**base, "ready": False, "error": f"Impossible de lancer Claude Code : {exc}"}
        if out.returncode != 0:
            return {**base, "ready": False,
                    "error": "Claude Code n'est pas connecté. Lancez « claude » dans un terminal et connectez-vous."}
        try:
            info = json.loads(out.stdout)
            base["account"] = info.get("authMethod")
        except json.JSONDecodeError:
            pass
        return {**base, "ready": True, "error": None}

    # ------------------------------------------------------------------ conversation

    def chat(self, messages: list[dict], system: str | None = None, max_tokens: int = MAX_TOKENS) -> str:
        if not messages:
            raise ClaudeError("Aucun message à envoyer.")
        return self._chat_api(messages, system, max_tokens) if self.mode == "api" else self._chat_cli(messages, system)

    def _chat_cli(self, messages: list[dict], system: str | None) -> str:
        path = find_claude(self.cli_path)
        if not path:
            raise ClaudeError("Claude Code est introuvable sur ce Mac (voir Paramètres).")
        cmd = [
            path, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",                     # aucun outil : ni fichiers, ni commandes
            "--disallowedTools", "mcp__*",     # ni serveurs MCP
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",        # rien n'est conservé dans l'historique de Claude Code
            "--max-turns", "1",
        ]
        if system:
            cmd += ["--system-prompt", system]
        # Dossier vide : Claude Code ne charge ni CLAUDE.md ni configuration de projet
        with tempfile.TemporaryDirectory(prefix="atelier-claude-") as workdir:
            try:
                out = subprocess.run(cmd, input=_flatten(messages), capture_output=True, text=True,
                                     timeout=self.timeout, cwd=workdir, env=_env())
            except subprocess.TimeoutExpired as exc:
                raise ClaudeError(f"Claude n'a pas répondu en {int(self.timeout)} secondes.") from exc
            except OSError as exc:
                raise ClaudeError(f"Impossible de lancer Claude Code : {exc}") from exc
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            detail = (out.stderr or out.stdout or "").strip().splitlines()
            raise ClaudeError("Claude Code a échoué : " + (detail[-1] if detail else f"code {out.returncode}")) from None
        result = str(data.get("result") or "").strip()
        if data.get("is_error") or out.returncode != 0:
            raise ClaudeError(f"Claude Code : {result or 'erreur inconnue'}")
        if not result:
            raise ClaudeError("Réponse vide de Claude.")
        return result

    def _chat_api(self, messages: list[dict], system: str | None, max_tokens: int) -> str:
        if not self.api_key:
            raise ClaudeError("Aucune clé API Claude enregistrée (Paramètres).")
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json", "x-api-key": self.api_key, "anthropic-version": API_VERSION},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (URL fixe en https)
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
            except (json.JSONDecodeError, AttributeError):
                detail = ""
            messages_fr = {401: "Clé API invalide.", 403: "Accès refusé pour cette clé.",
                           404: f"Modèle « {self.model} » introuvable.", 429: "Limite d'utilisation atteinte, réessayez plus tard.",
                           529: "Claude est surchargé, réessayez dans un instant."}
            raise ClaudeError(messages_fr.get(exc.code, f"Erreur {exc.code} de l'API Claude.") +
                              (f" ({detail})" if detail else "")) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ClaudeError("API Claude injoignable : vérifiez la connexion Internet.") from exc
        except json.JSONDecodeError as exc:
            raise ClaudeError("Réponse de l'API Claude illisible.") from exc
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if not text:
            raise ClaudeError("Réponse vide de Claude.")
        return text
