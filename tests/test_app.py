import sqlite3
from datetime import date

import pytest

import database
from app import create_app
from finance import format_eur, savings_rate, to_cents


@pytest.fixture()
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE_PATH": tmp_path / "test.db",
        "OLLAMA_URL": "http://127.0.0.1:9",  # port fermé : simule Ollama hors ligne
    })


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.mark.parametrize("url", ["/", "/accounts", "/transactions", "/budgets", "/ai-insights", "/settings"])
def test_pages_render(client, url):
    res = client.get(url)
    assert res.status_code == 200
    assert "Atelier" in res.get_data(as_text=True)


def test_404_html_and_json(client):
    assert client.get("/inexistant").status_code == 404
    res = client.get("/api/inexistant")
    assert res.status_code == 404 and res.is_json


def test_health_reports_db_and_offline_ollama(client):
    data = client.get("/api/health").get_json()
    assert data["database"]["ok"] is True
    assert data["database"]["categories"] == len(database.DEFAULT_CATEGORIES)
    assert data["ollama"]["available"] is False
    assert "ollama serve" in data["ollama"]["error"]


def test_schema_is_idempotent(app):
    conn = database.connect(app.config["DATABASE_PATH"])
    database.init_schema(conn)  # deuxième passage : aucune erreur, aucun doublon
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"accounts", "transactions", "categories", "budgets", "goals", "v_account_balances"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()


def test_constraints(app):
    conn = database.connect(app.config["DATABASE_PATH"])
    with pytest.raises(sqlite3.IntegrityError):  # compte inexistant (clé étrangère)
        conn.execute("INSERT INTO transactions (account_id, date, label, amount_cents) VALUES (999, '2026-01-01', 'x', 1)")
    with pytest.raises(sqlite3.IntegrityError):  # date mal formée
        conn.execute("INSERT INTO accounts (name) VALUES ('A')")
        conn.execute("INSERT INTO transactions (account_id, date, label, amount_cents) VALUES (1, '01/01/2026', 'x', 1)")
    conn.close()


def test_seed_demo(app):
    conn = database.connect(app.config["DATABASE_PATH"])
    n = database.seed_demo(conn, today=date(2026, 10, 18))
    assert n > 100
    assert database.seed_demo(conn) == 0  # ne double pas les données
    balances = conn.execute("SELECT name, balance_cents FROM v_account_balances").fetchall()
    assert len(balances) == 3
    # Les virements internes s'annulent sur l'ensemble des comptes
    internal = conn.execute(
        "SELECT SUM(amount_cents) FROM transactions t JOIN categories c ON c.id = t.category_id "
        "WHERE c.name = 'Virement interne'"
    ).fetchone()[0]
    assert internal == 0
    conn.close()


def test_unwritable_db_path_raises_clear_error(tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("pas un dossier")
    with pytest.raises(database.DatabaseError, match="Impossible de créer le dossier"):
        database.connect(blocker / "sous" / "finance.db")


def test_money_helpers():
    assert to_cents("1 234,56") == 123456
    assert to_cents("1.234,56") == 123456
    assert to_cents("-12.5") == -1250
    assert to_cents(42) == 4200
    with pytest.raises(ValueError):
        to_cents("abc")
    assert format_eur(123456) == "1 234,56 €"
    assert format_eur(-500) == "-5,00 €"
    assert format_eur(1000, signed=True) == "+10,00 €"
    assert savings_rate(300000, -240000) == 20.0
    assert savings_rate(0, -1000) is None
