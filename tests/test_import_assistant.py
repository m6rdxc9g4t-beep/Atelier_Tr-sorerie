"""Assistant d'import : commerçants, règles, classement en cascade, virements internes,
lots d'import (rapport, annulation), apprentissage, récurrences et montants inhabituels."""
import io
from datetime import date, timedelta

import database
from services import imports, insights
from services.merchants import identify, known_merchant, merchant_key


def _account(api, name="Courant", kind="courant"):
    return api.post("/api/accounts", json={"name": name, "type": kind}).get_json()["id"]


def _cat(api, name):
    return next(c["id"] for c in api.get("/api/categories").get_json()["items"] if c["name"] == name)


def _preview(api, account_id, csv_text, filename="releve.csv"):
    data = {"file": (io.BytesIO(csv_text.encode()), filename), "account_id": str(account_id)}
    res = api.post("/api/import/preview", data=data, content_type="multipart/form-data")
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _commit(api, preview, **extra):
    rows = [r for r in preview["rows"] if r["status"] == "ok"]
    payload = {"account_id": preview["account_id"], "filename": preview["filename"], "rows": [
        {"date": r["date"], "label": r["label"], "amount_cents": r["amount_cents"], "category_id": r["category_id"],
         "category_source": r["category_source"], "import_hash": r["import_hash"],
         "transfer_with": (r["transfer"] or {}).get("transaction_id")} for r in rows], **extra}
    res = api.post("/api/import/commit", json=payload)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


# --------------------------------------------------------------------------- commerçants

def test_merchant_extraction_from_french_bank_labels():
    assert merchant_key("CB CARREFOUR MARKET 12/10 X1234") == "carrefour market"
    assert merchant_key("PRELEVEMENT EUROPEEN 123 DE: FREE MOBILE ID: FR34ZZZ MOTIF: ABO") == "free mobile"
    assert merchant_key("VIR SEPA RECU /DE M JEAN DUPONT /MOTIF LOYER") == "jean dupont"
    assert merchant_key("PAIEMENT PAR CARTE X4974 PAYPAL *NETFLIX 04/10") == "netflix"
    assert identify("CB CARREFOUR CITY 04/10 PARIS", -1500) == {"key": "carrefour", "name": "Carrefour",
                                                                "category": "Courses"}
    assert identify("PRLV SEPA EDF CLIENTS PARTICULIERS", -8000)["name"] == "EDF"
    assert identify("CB UBER EATS PARIS", -2500)["category"] == "Restaurants"   # le plus précis d'abord
    assert identify("CB UBER TRIP", -1500)["category"] == "Transport"
    # Motifs courts : mot entier uniquement ; motifs réservés à un sens
    assert known_merchant("CB BOULEDF SARL", -100) is None
    assert known_merchant("COTISATION RETRAITE", -1000) is None
    assert known_merchant("VIR SALAIRE OCTOBRE", 285000)[1] == "Salaire"
    assert known_merchant("VIR SALAIRE OCTOBRE", -285000) is None


# --------------------------------------------------------------------------- classement en cascade

def test_cascade_rule_beats_history_and_dictionary(api):
    acc = _account(api)
    loisirs, courses = _cat(api, "Loisirs"), _cat(api, "Courses")
    csv = "Date;Libellé;Montant\n05/10/2026;CB CARREFOUR 05/10;-30,00\n06/10/2026;CB TRUC INCONNU;-12\n"
    rows = _preview(api, acc, csv)["rows"]
    assert (rows[0]["category_id"], rows[0]["category_source"], rows[0]["merchant"]) == (courses, "defaut", "Carrefour")
    assert rows[1]["category_id"] is None and rows[1]["category_source"] is None

    # L'historique l'emporte sur le dictionnaire
    api.post("/api/transactions", json={"account_id": acc, "date": "2026-09-01", "label": "CB CARREFOUR 01/09",
                                        "amount": "-20", "category_id": loisirs})
    assert _preview(api, acc, csv)["rows"][0]["category_source"] == "historique"

    # Une règle l'emporte sur tout ; « contient » ignore accents et casse
    rule = api.post("/api/rules", json={"pattern": "Carrefour", "category_id": courses}).get_json()
    assert rule["pattern"] == "carrefour" and rule["match_type"] == "contient"
    row = _preview(api, acc, csv)["rows"][0]
    assert (row["category_id"], row["category_source"], row["rule_id"]) == (courses, "regle", rule["id"])


def test_rules_crud_validation_and_apply(api):
    acc = _account(api)
    sante = _cat(api, "Santé")
    tx = api.post("/api/transactions", json={"account_id": acc, "date": "2026-10-01", "label": "CB DR MARTIN",
                                             "amount": "-25"}).get_json()
    assert tx["category_id"] is None
    assert api.post("/api/rules", json={"pattern": "a", "category_id": sante}).status_code == 400
    assert api.post("/api/rules", json={"pattern": "dr martin", "category_id": 999}).status_code == 400
    assert api.post("/api/rules", json={"pattern": "x", "match_type": "regex", "category_id": sante}).status_code == 400

    rule = api.post("/api/rules", json={"pattern": "DR MARTIN", "direction": "debit", "category_id": sante}).get_json()
    same = api.post("/api/rules", json={"pattern": "dr martin", "direction": "debit", "category_id": sante}).get_json()
    assert same["id"] == rule["id"]  # pas de doublon
    listed = api.get("/api/rules").get_json()["items"]
    assert len(listed) == 1 and listed[0]["matches"] == 1

    assert api.post("/api/rules/apply", json={}).get_json() == {"updated": 1}
    updated = api.get(f"/api/transactions/{tx['id']}").get_json()
    assert updated["category_id"] == sante
    # Une catégorie choisie à la main n'est jamais écrasée par une règle
    divers = _cat(api, "Divers")
    api.patch(f"/api/transactions/{tx['id']}", json={"category_id": divers})
    assert api.post("/api/rules/apply", json={}).get_json() == {"updated": 0}

    assert api.patch(f"/api/rules/{rule['id']}", json={"direction": "tous"}).get_json()["direction"] == "tous"
    assert api.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert api.get("/api/rules").get_json()["items"] == []


def test_rule_suggestion_from_transaction(api):
    acc = _account(api)
    tx = api.post("/api/transactions", json={"account_id": acc, "date": "2026-10-01",
                                             "label": "CB LE PETIT BISTROT 01/10", "amount": "-32"}).get_json()
    sug = api.get(f"/api/transactions/{tx['id']}/rule-suggestion").get_json()
    assert sug == {"pattern": "petit bistrot", "match_type": "commercant", "merchant": "Petit Bistrot"}


# --------------------------------------------------------------------------- virements internes

def test_transfer_between_own_accounts_is_detected_and_linked(api):
    courant = _account(api)
    livret = _account(api, "Livret A", "epargne")
    other = api.post("/api/transactions", json={"account_id": livret, "date": "2026-10-03",
                                                "label": "VIREMENT RECU", "amount": "200"}).get_json()
    csv = ("Date;Libellé;Montant\n02/10/2026;VIR VERS LIVRET A;-200,00\n"
           "02/10/2026;CB FNAC;-200,00\n")  # même montant, mais ce n'est pas un virement
    p = _preview(api, courant, csv)
    vir, fnac = p["rows"]
    assert vir["transfer"]["transaction_id"] == other["id"] and vir["category_source"] == "virement"
    assert fnac["transfer"] is None and fnac["category_source"] == "defaut"
    assert p["summary"]["transfers"] == 1

    res = _commit(api, p)
    assert res["transfers_linked"] == 1
    legs = api.get("/api/transactions?type=transfer").get_json()["items"]
    assert len(legs) == 2 and len({t["transfer_group"] for t in legs}) == 1
    # Exclus des revenus / dépenses
    totals = api.get("/api/transactions").get_json()
    assert (totals["income_cents"], totals["expense_cents"]) == (0, -20000)

    # Annuler l'import délie l'autre compte sans le supprimer
    assert api.delete(f"/api/imports/{res['batch_id']}").get_json() == {"deleted": 2}
    survivor = api.get(f"/api/transactions/{other['id']}").get_json()
    assert survivor["transfer_group"] is None and survivor["category_id"] is None


# --------------------------------------------------------------------------- lots, rapport, apprentissage

STATEMENT = """Date;Libellé;Montant
01/10/2026;VIR SALAIRE OCTOBRE;2850,00
03/10/2026;PRLV SEPA EDF CLIENTS;-82,10
04/10/2026;CB CARREFOUR 04/10;-67,45
05/10/2026;CB LE PETIT BISTROT 05/10;-38,00
07/10/2026;CB OBSCUR SHOP 07/10;-12,00
"""


def test_batch_report_learning_and_undo(api):
    acc = _account(api)
    loisirs = _cat(api, "Loisirs")
    p = _preview(api, acc, STATEMENT)
    assert p["summary"]["sources"] == {"defaut": 4, "aucune": 1}
    # L'utilisateur a classé « Obscur Shop » à la main dans l'aperçu : la correction devient une règle
    p["rows"][4].update(category_id=loisirs, category_source="manuel")
    res = _commit(api, p, learn=[{"pattern": "obscur shop", "category_id": loisirs}])
    assert (res["inserted"], res["rules_created"]) == (5, 1)

    batches = api.get("/api/imports").get_json()["items"]
    assert len(batches) == 1
    b = batches[0]
    assert (b["count"], b["start"], b["end"], b["filename"]) == (5, "2026-10-01", "2026-10-07", "releve.csv")
    assert (b["income_cents"], b["expense_cents"], b["uncategorized"]) == (285000, -19955, 0)

    r = api.get(f"/api/imports/{res['batch_id']}/report").get_json()
    assert (r["income_cents"], r["expense_cents"], r["net_cents"]) == (285000, -19955, 265045)
    assert r["balance_cents"] == 265045
    assert r["expenses_by_category"][0]["name"] == "Énergie & Internet"
    assert {s["source"]: s["count"] for s in r["sources"]} == {"defaut": 4, "manuel": 1}
    assert r["new_merchants_count"] == 5 and r["highlights"][0].startswith("5 opération(s) du 01/10/2026")

    # La règle apprise sert dès l'import suivant
    nxt = _preview(api, acc, "Date;Libellé;Montant\n10/10/2026;CB OBSCUR SHOP 10/10;-41,00\n")["rows"][0]
    assert (nxt["category_id"], nxt["category_source"]) == (loisirs, "regle")

    assert api.delete(f"/api/imports/{res['batch_id']}").get_json() == {"deleted": 5}
    assert api.get("/api/imports").get_json()["items"] == []
    assert api.get("/api/transactions").get_json()["total"] == 0
    assert api.get(f"/api/imports/{res['batch_id']}/report").status_code == 404


def test_ai_categorize_preview_rows_groups_by_merchant(api, monkeypatch):
    sent = []

    class FakeProvider:
        local, model, label = True, "fake", "Fake"

        def chat(self, messages, system=None, max_tokens=None):
            sent.append(messages[-1]["content"])
            return '[{"id": 1, "categorie": "Loisirs"}, {"id": 2, "categorie": "Salaire"}]'

    import api as api_module
    monkeypatch.setattr(api_module, "_provider", lambda: FakeProvider())
    items = [{"key": 0, "label": "CB CINEMA REX 01/10", "amount_cents": -1200},
             {"key": 1, "label": "CB CINEMA REX 08/10", "amount_cents": -1100},
             {"key": 2, "label": "CB TRUC 08/10", "amount_cents": -500}]
    res = api.post("/api/import/ai-categorize", json={"items": items}).get_json()
    assert res["asked"] == 2  # un seul envoi pour les deux séances de cinéma
    assert sent[0].count("CINEMA REX") == 1
    loisirs = _cat(api, "Loisirs")
    # « Salaire » (revenu) refusé pour une dépense
    assert res["items"] == [{"key": 0, "category_id": loisirs, "category_name": "Loisirs"},
                            {"key": 1, "category_id": loisirs, "category_name": "Loisirs"}]


# --------------------------------------------------------------------------- comprendre ses comptes

def _monthly(day0: date, n: int, step: int):
    return [day0 + timedelta(days=step * i) for i in range(n)]


def test_recurring_detection():
    today = date(2026, 11, 6)
    rows = []
    for d in _monthly(date(2026, 4, 6), 8, 30):
        rows.append({"date": d.isoformat(), "label": f"PRLV NETFLIX {d:%d/%m}", "amount_cents": -1349})
        rows.append({"date": d.isoformat(), "label": "PRLV EDF", "amount_cents": -8000 - (d.month % 3) * 500})
    for d in _monthly(date(2026, 9, 1), 9, 7):  # courses hebdomadaires, montants très variables
        rows.append({"date": d.isoformat(), "label": "CB CARREFOUR", "amount_cents": -(2000 + d.day * 300)})
    for d in _monthly(date(2026, 1, 5), 4, 30):  # arrêté depuis longtemps
        rows.append({"date": d.isoformat(), "label": "PRLV SALLE SPORT", "amount_cents": -2999})
    found = {i["merchant"]: i for i in insights.detect_recurring(rows, today)}
    assert set(found) == {"Netflix", "EDF"}
    assert found["Netflix"]["frequency"] == "mensuel" and found["Netflix"]["fixed"]
    assert found["Netflix"]["monthly_cents"] == -1349
    assert not found["EDF"]["fixed"]


def test_recurring_endpoint(api):
    acc = _account(api)
    today = date.today()
    for i in range(4):
        d = today - timedelta(days=30 * i + 2)
        api.post("/api/transactions", json={"account_id": acc, "date": d.isoformat(),
                                            "label": "PRLV SPOTIFY", "amount": "-10,99"})
    data = api.get("/api/insights/recurring").get_json()
    assert [i["merchant"] for i in data["items"]] == ["Spotify"]
    assert data["monthly_debit_cents"] == -1099


def test_unusual_amounts(app):
    with app.app_context():
        conn = database.get_db()
        acc = conn.execute("INSERT INTO accounts (name) VALUES ('C')").lastrowid
        today = date(2026, 11, 6)
        for i in range(4):
            conn.execute("INSERT INTO transactions (account_id, date, label, amount_cents) VALUES (?, ?, ?, ?)",
                         (acc, (today - timedelta(days=30 * i + 10)).isoformat(), "PRLV EDF", -8000))
        conn.commit()
        rows = [{"id": None, "date": "2026-11-05", "label": "PRLV EDF REGUL", "amount_cents": -24000},
                {"id": None, "date": "2026-11-05", "label": "PRLV EDF", "amount_cents": -8500},
                {"id": None, "date": "2026-11-05", "label": "CB BIJOUTERIE NOUVELLE", "amount_cents": -90000}]
        flagged = insights.unusual(conn, rows, today=today)
        assert [f["merchant"] for f in flagged] == ["Bijouterie Nouvelle", "EDF"]
        assert flagged[1]["reason"].startswith("3,0 × le montant habituel chez EDF")


def test_explain_prompt_aggregated_for_remote_engine(api):
    acc = _account(api)
    res = _commit(api, _preview(api, acc, STATEMENT))
    with api.c.application.app_context():
        report = imports.report(database.get_db(), res["batch_id"])
    remote = imports.explain_prompt(report, detailed=False)
    local = imports.explain_prompt(report, detailed=True)
    assert "CARREFOUR" not in remote and "EDF" not in remote and "Courses" in remote
    assert "CARREFOUR" in local


def test_migration_5_from_v4(tmp_path):
    path = tmp_path / "v4.db"
    conn = database.connect(path)
    conn.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    for v in (2, 3, 4):
        conn.executescript(database.MIGRATIONS[v])
    conn.execute("PRAGMA user_version = 4")
    conn.execute("INSERT INTO accounts (name) VALUES ('Ancien')")
    conn.execute("INSERT INTO transactions (account_id, date, label, amount_cents) VALUES (1, '2026-01-01', 'X', -1)")
    conn.commit()
    database.init_schema(conn)
    assert database.schema_version(conn) >= 5
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert {"import_batch_id", "category_source"} <= cols
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"category_rules", "import_batches"} <= tables
    conn.close()
