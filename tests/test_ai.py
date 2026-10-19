import json
import os
import stat
import sys
from datetime import date

import pytest

import database
from claude_client import ClaudeClient, ClaudeError
from services import ai_context


class FakeProvider:
    def __init__(self, local=True, answer="Réponse de test", fail=None):
        self.local = local
        self.label = "Ollama (local)" if local else "Claude (abonnement)"
        self.model = "fake-model"
        self.answer = answer
        self.fail = fail
        self.calls = []

    def chat(self, messages, system=None, max_tokens=None):
        self.calls.append({"messages": messages, "system": system})
        if self.fail:
            raise self.fail
        return self.answer(messages) if callable(self.answer) else self.answer


@pytest.fixture()
def fake(monkeypatch):
    holder = {"provider": FakeProvider()}
    monkeypatch.setattr("api.ai_providers.build_provider", lambda settings, config: holder["provider"])
    return holder


@pytest.fixture()
def demo(app):
    conn = database.connect(app.config["DATABASE_PATH"])
    database.seed_demo(conn)
    conn.close()


# --------------------------------------------------------------------------- paramètres

def test_settings_defaults_update_and_masked_key(api):
    s = api.get("/api/settings").get_json()
    assert s["ai_provider"] == "ollama" and s["claude_mode"] == "cli" and s["ollama_model"] == "llama3.1"
    assert s["anthropic_api_key_set"] is False and "anthropic_api_key" not in s

    res = api.patch("/api/settings", json={"ai_provider": "claude", "claude_mode": "api",
                                           "anthropic_api_key": "sk-ant-api03-abcdefghijklmnop1234"})
    s = res.get_json()
    assert s["ai_provider"] == "claude" and s["anthropic_api_key_set"] is True
    assert s["anthropic_api_key_hint"] == "sk-ant-…1234" and "abcdefghijklmnop" not in json.dumps(s)

    bad = api.patch("/api/settings", json={"ai_provider": "gpt", "anthropic_api_key": "nope",
                                           "claude_cli_path": "/nulle/part/claude"})
    assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"ai_provider", "anthropic_api_key", "claude_cli_path"}
    assert api.patch("/api/settings", json={"anthropic_api_key": None}).get_json()["anthropic_api_key_set"] is False


def test_status_reports_selected_provider(api):
    assert api.get("/api/ai/status").get_json()["provider"] == "ollama"
    api.patch("/api/settings", json={"ai_provider": "claude", "claude_mode": "api"})
    status = api.get("/api/ai/status").get_json()
    assert status["provider"] == "claude" and status["local"] is False and status["ready"] is False
    assert "clé" in status["error"].lower()
    health = api.get("/api/health").get_json()
    assert health["ai"]["provider"] == "claude"


# --------------------------------------------------------------------------- contexte

def test_context_detailed_vs_aggregated(app, demo):
    conn = database.connect(app.config["DATABASE_PATH"])
    detailed = ai_context.build_context(conn, detailed=True)
    aggregated = ai_context.build_context(conn, detailed=False)
    conn.close()
    for text in (detailed, aggregated):
        assert "## Patrimoine" in text and "## Revenus et dépenses des 6 derniers mois" in text
        assert "Logement" in text and "## Budgets" in text and "## Placements" in text
    # Le niveau local contient libellés, noms de comptes, positions et objectifs nommés
    for secret in ("Supermarché", "Livret A", "Air Liquide", "Fonds d'urgence"):
        assert secret in detailed, secret
        assert secret not in aggregated, secret
    # L'établissement bancaire n'est transmis à aucun moteur
    assert "Banque Locale" not in detailed and "Banque Locale" not in aggregated
    assert "Objectif 1" in aggregated and "Plus grosses dépenses" not in aggregated


# --------------------------------------------------------------------------- conversation

def test_ask_stores_history_and_uses_context(api, fake, demo):
    res = api.post("/api/ai/ask", json={"question": "Où est-ce que je dépense trop ?"})
    assert res.status_code == 200
    assert res.get_json()["answer"]["content"] == "Réponse de test"
    call = fake["provider"].calls[0]
    assert "Données financières" in call["system"] and "Supermarché" in call["system"]  # local : détaillé
    assert call["messages"][-1] == {"role": "user", "content": "Où est-ce que je dépense trop ?"}

    # Deuxième question : l'historique est renvoyé
    api.post("/api/ai/ask", json={"question": "Et le mois dernier ?"})
    assert [m["role"] for m in fake["provider"].calls[1]["messages"]] == ["user", "assistant", "user"]
    data = api.get("/api/ai/messages").get_json()
    assert len(data["items"]) == 4 and data["items"][1]["provider"] == "ollama" and data["suggestions"]

    assert api.delete("/api/ai/messages").get_json() == {"deleted": 4}
    assert api.post("/api/ai/ask", json={"question": ""}).status_code == 400


def test_claude_receives_only_aggregated_context(api, fake, demo):
    # Échange préalable avec Ollama, dont la réponse contient un détail local
    fake["provider"] = FakeProvider(answer="Votre Livret A et vos courses chez Supermarché…")
    api.post("/api/ai/ask", json={"question": "Détail de mes comptes ?"})

    fake["provider"] = FakeProvider(local=False)
    api.post("/api/ai/ask", json={"question": "Bilan ?"})
    sent = fake["provider"].calls[0]
    assert sent["messages"] == [{"role": "user", "content": "Bilan ?"}]  # pas l'historique d'Ollama
    system = sent["system"]
    assert "agrégé" in system and "Supermarché" not in system and "Livret A" not in system
    ctx = api.get("/api/ai/context").get_json()
    assert ctx["local"] is False and ctx["text"] == system


def test_ask_error_returns_502_and_stores_nothing(api, fake):
    fake["provider"] = FakeProvider(fail=ClaudeError("Claude Code n'est pas connecté."))
    res = api.post("/api/ai/ask", json={"question": "Test"})
    assert res.status_code == 502 and "connecté" in res.get_json()["error"]
    assert api.get("/api/ai/messages").get_json()["items"] == []


# --------------------------------------------------------------------------- catégorisation

def test_categorize_and_apply(api, fake):
    acc = api.post("/api/accounts", json={"name": "Courant"}).get_json()["id"]
    ids = [api.post("/api/transactions", json={"account_id": acc, "date": "2026-10-0%d" % (i + 1), "label": label,
                                               "amount": amount}).get_json()["id"]
           for i, (label, amount) in enumerate([("BOULANGERIE PAUL", "-4,80"), ("NETFLIX", "-13,49"),
                                                ("VIR CAF", "120"), ("TRUC BIZARRE", "-9")])]
    reply = "Voici :\n```json\n" + json.dumps([
        {"id": ids[0], "categorie": "courses"},          # casse différente : acceptée
        {"id": ids[1], "categorie": "Abonnements"},
        {"id": ids[2], "categorie": "Revenus annexes"},
        {"id": ids[3], "categorie": "Salaire"},          # revenu pour une dépense : rejeté
        {"id": 99999, "categorie": "Courses"},           # opération inconnue : ignorée
    ]) + "\n```"
    fake["provider"] = FakeProvider(answer=reply)
    data = api.post("/api/ai/categorize", json={}).get_json()
    assert {i["label"]: i["category_name"] for i in data["items"]} == {
        "BOULANGERIE PAUL": "Courses", "NETFLIX": "Abonnements", "VIR CAF": "Revenus annexes"}
    assert data["unmatched"] == 1 and data["remaining"] == 4
    prompt = fake["provider"].calls[0]["messages"][0]["content"]
    assert "Virement interne" not in prompt and "NETFLIX" in prompt

    res = api.post("/api/ai/categorize/apply", json={"items": [{"id": i["id"], "category_id": i["category_id"]} for i in data["items"]]})
    assert res.get_json() == {"applied": 3, "remaining": 1}
    assert api.get("/api/ai/messages").get_json()["uncategorized"] == 1

    fake["provider"] = FakeProvider(answer="Je ne sais pas.")
    assert api.post("/api/ai/categorize", json={}).status_code == 400


# --------------------------------------------------------------------------- sauvegarde

def test_backup_download(client, demo):
    res = client.get("/api/system/backup")
    assert res.status_code == 200 and res.data.startswith(b"SQLite format 3")
    assert "atelier-tresorerie-" in res.headers["Content-Disposition"]


# --------------------------------------------------------------------------- client Claude

def _fake_claude(tmp_path, payload, code=0):
    """Faux exécutable « claude » : enregistre ses arguments et renvoie `payload`."""
    log = tmp_path / "argv.json"
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}}, open({str(log)!r}, 'w'))\n"
        f"print({json.dumps(json.dumps(payload))})\n"
        f"sys.exit({code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def test_claude_cli_runs_without_tools(tmp_path):
    script, log = _fake_claude(tmp_path, {"type": "result", "is_error": False, "result": "Bonjour !"})
    client = ClaudeClient(mode="cli", cli_path=str(script))
    answer = client.chat([{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "R1"},
                          {"role": "user", "content": "Q2"}], system="Contexte")
    assert answer == "Bonjour !"
    called = json.loads(log.read_text())
    argv = called["argv"]
    assert argv[:1] == ["-p"] and argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == "Contexte" and "--no-session-persistence" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "Q1" in called["stdin"] and called["stdin"].rstrip().endswith("Q2")
    assert os.path.realpath(called["cwd"]) != os.path.realpath(os.getcwd())  # dossier vide temporaire
    assert client.status()["ready"] is True


def test_claude_cli_errors(tmp_path):
    script, _ = _fake_claude(tmp_path, {"type": "result", "is_error": True, "result": "Not logged in"}, code=1)
    with pytest.raises(ClaudeError, match="Not logged in"):
        ClaudeClient(mode="cli", cli_path=str(script)).chat([{"role": "user", "content": "x"}])
    missing = ClaudeClient(mode="cli", cli_path=str(tmp_path / "absent"))
    assert missing.status()["ready"] is False
    with pytest.raises(ClaudeError, match="introuvable"):
        missing.chat([{"role": "user", "content": "x"}])


def test_claude_api_request(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "Analyse"}]}).encode()

    def fake_urlopen(req, timeout):
        sent["url"], sent["headers"], sent["body"] = req.full_url, dict(req.headers), json.loads(req.data)
        return Resp()

    monkeypatch.setattr("claude_client.urllib.request.urlopen", fake_urlopen)
    client = ClaudeClient(mode="api", api_key="sk-ant-test")
    assert client.chat([{"role": "user", "content": "Q"}], system="S") == "Analyse"
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["X-api-key"] == "sk-ant-test" and sent["body"]["system"] == "S"
    assert sent["body"]["model"] == "claude-sonnet-5-5"
    with pytest.raises(ClaudeError, match="clé"):
        ClaudeClient(mode="api").chat([{"role": "user", "content": "Q"}])
