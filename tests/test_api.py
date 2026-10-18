import sqlite3

import database


def _account(api, **kw):
    res = api.post("/api/accounts", json={"name": "Courant", "type": "courant", "opening_balance": "1000", **kw})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def _category_id(app, name):
    conn = database.connect(app.config["DATABASE_PATH"])
    try:
        return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- sécurité

def test_mutations_require_header(client):
    res = client.post("/api/accounts", json={"name": "X"})
    assert res.status_code == 403


# --------------------------------------------------------------------------- comptes

def test_account_crud_and_balance(api):
    acc = _account(api, institution="Ma banque")
    assert acc["balance_cents"] == 100000 and acc["type_label"] == "Compte courant"

    api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-01",
                                        "label": "Courses", "amount": "-45,90"})
    assert api.get(f"/api/accounts/{acc['id']}").get_json()["balance_cents"] == 100000 - 4590

    res = api.patch(f"/api/accounts/{acc['id']}", json={"name": "Compte joint", "archived": True})
    assert res.get_json()["name"] == "Compte joint" and res.get_json()["archived"] is True
    assert api.get("/api/accounts").get_json()["items"] == []
    assert len(api.get("/api/accounts?archived=1").get_json()["items"]) == 1

    # Suppression refusée tant que le compte a des transactions, sauf confirmation
    assert api.delete(f"/api/accounts/{acc['id']}").status_code == 409
    assert api.delete(f"/api/accounts/{acc['id']}?force=1").status_code == 204
    assert api.get(f"/api/accounts/{acc['id']}").status_code == 404


def test_account_validation(api):
    res = api.post("/api/accounts", json={"name": "", "type": "inconnu", "opening_balance": "abc"})
    assert res.status_code == 400
    assert set(res.get_json()["fields"]) == {"name", "type", "opening_balance"}
    assert api.post("/api/accounts", data="pas du json", content_type="application/json").status_code == 400
    acc = _account(api)
    assert api.patch(f"/api/accounts/{acc['id']}", json={"name": ""}).status_code == 400
    assert api.patch(f"/api/accounts/{acc['id']}", json={}).status_code == 400


# --------------------------------------------------------------------------- transactions

def test_transactions_filters_and_totals(app, api):
    acc = _account(api)
    courses = _category_id(app, "Courses")
    salaire = _category_id(app, "Salaire")
    for date, label, amount, cat in [
        ("2026-09-28", "Supermarché", "-60", courses),
        ("2026-10-01", "Salaire octobre", "2500", salaire),
        ("2026-10-04", "Supermarché", "-80,50", courses),
        ("2026-10-05", "Cinéma 100% fun", "-12", None),
    ]:
        assert api.post("/api/transactions", json={"account_id": acc["id"], "date": date, "label": label,
                                                   "amount": amount, "category_id": cat}).status_code == 201

    data = api.get("/api/transactions?month=2026-10").get_json()
    assert data["total"] == 3
    assert data["income_cents"] == 250000 and data["expense_cents"] == -9250
    assert [t["date"] for t in data["items"]] == ["2026-10-05", "2026-10-04", "2026-10-01"]

    assert api.get("/api/transactions?type=expense").get_json()["total"] == 3
    assert api.get(f"/api/transactions?category_id={courses}").get_json()["total"] == 2
    assert api.get("/api/transactions?category_id=none").get_json()["total"] == 1
    assert api.get("/api/transactions?q=100%").get_json()["total"] == 1  # % échappé
    assert api.get("/api/transactions?q=super&sort=amount&order=asc").get_json()["items"][0]["amount_cents"] == -8050
    page = api.get("/api/transactions?per_page=2&page=2").get_json()
    assert page["pages"] == 2 and len(page["items"]) == 2
    assert api.get("/api/transactions?month=2026-13").status_code == 400


def test_transaction_category_learned_from_history(app, api):
    acc = _account(api)
    courses = _category_id(app, "Courses")
    api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-01",
                                        "label": "CB CARREFOUR 01/10", "amount": "-30", "category_id": courses})
    res = api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-08",
                                              "label": "CB CARREFOUR 08/10", "amount": "-42"})
    assert res.get_json()["category_id"] == courses


def test_transaction_update_delete_and_errors(api):
    acc = _account(api)
    res = api.post("/api/transactions", json={"account_id": 999, "date": "2026-13-01", "label": "", "amount": 0})
    assert res.status_code == 400
    assert set(res.get_json()["fields"]) == {"account_id", "date", "label", "amount"}

    tx = api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-01",
                                             "label": "Test", "amount": -10}).get_json()
    updated = api.patch(f"/api/transactions/{tx['id']}", json={"amount": "-12,34", "status": "rapproche",
                                                                 "category_id": None}).get_json()
    assert updated["amount_cents"] == -1234 and updated["status"] == "rapproche" and updated["category_id"] is None
    assert api.delete(f"/api/transactions/{tx['id']}").get_json() == {"deleted": 1}
    assert api.get(f"/api/transactions/{tx['id']}").status_code == 404


def test_transfer_creates_linked_legs(api):
    a = _account(api, name="Courant")
    b = _account(api, name="Livret", type="epargne", opening_balance="0")
    res = api.post("/api/transfers", json={"from_account_id": a["id"], "to_account_id": b["id"],
                                           "amount": "150", "date": "2026-10-10"})
    assert res.status_code == 201
    legs = res.get_json()["items"]
    assert [leg["amount_cents"] for leg in legs] == [-15000, 15000]
    assert legs[0]["label"] == "Virement vers Livret"

    # Les virements ne comptent ni en revenu ni en dépense
    data = api.get("/api/transactions").get_json()
    assert data["income_cents"] == 0 and data["expense_cents"] == 0
    assert api.get("/api/transactions?type=transfer").get_json()["total"] == 2

    # Modifier une jambe met l'autre à jour ; supprimer une jambe supprime les deux
    api.patch(f"/api/transactions/{legs[0]['id']}", json={"amount": "-200", "date": "2026-10-11"})
    other = api.get(f"/api/transactions/{legs[1]['id']}").get_json()
    assert other["amount_cents"] == 20000 and other["date"] == "2026-10-11"
    assert api.patch(f"/api/transactions/{legs[0]['id']}", json={"account_id": b["id"]}).status_code == 400
    assert api.delete(f"/api/transactions/{legs[1]['id']}").get_json() == {"deleted": 2}

    same = api.post("/api/transfers", json={"from_account_id": a["id"], "to_account_id": a["id"],
                                            "amount": "1", "date": "2026-10-10"})
    assert same.status_code == 400


def test_bulk_actions(app, api):
    acc = _account(api)
    ids = [api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-01",
                                               "label": f"Op {i}", "amount": -i - 1}).get_json()["id"]
           for i in range(3)]
    loisirs = _category_id(app, "Loisirs")
    res = api.post("/api/transactions/bulk", json={"action": "categorize", "ids": ids[:2], "category_id": loisirs})
    assert res.get_json()["affected"] == 2
    assert api.get(f"/api/transactions?category_id={loisirs}").get_json()["total"] == 2
    assert api.post("/api/transactions/bulk", json={"action": "status", "ids": ids, "status": "rapproche"}).status_code == 200
    assert api.post("/api/transactions/bulk", json={"action": "delete", "ids": ids}).get_json()["affected"] == 3
    assert api.post("/api/transactions/bulk", json={"action": "boom", "ids": [1]}).status_code == 400
    assert api.post("/api/transactions/bulk", json={"action": "delete", "ids": []}).status_code == 400


# --------------------------------------------------------------------------- catégories

def test_categories(api):
    items = api.get("/api/categories").get_json()["items"]
    assert len(items) == len(database.DEFAULT_CATEGORIES)
    res = api.post("/api/categories", json={"name": "Animaux", "kind": "depense", "color": "#AABBCC"})
    assert res.status_code == 201 and res.get_json()["color"] == "#aabbcc"
    assert api.post("/api/categories", json={"name": "animaux", "kind": "depense"}).status_code == 409
    cid = res.get_json()["id"]
    assert api.patch(f"/api/categories/{cid}", json={"name": "Animaux de compagnie"}).status_code == 200
    assert api.delete(f"/api/categories/{cid}").status_code == 204


# --------------------------------------------------------------------------- budgets & objectifs

def test_budgets(app, api):
    acc = _account(api)
    courses = _category_id(app, "Courses")
    resto = _category_id(app, "Restaurants")
    for amount in ("-150", "-120", "40"):  # 40 € = remboursement
        api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-05", "label": "Courses",
                                            "amount": amount, "category_id": courses})
    api.post("/api/transactions", json={"account_id": acc["id"], "date": "2026-10-06", "label": "Resto",
                                        "amount": "-35", "category_id": resto})

    res = api.post("/api/budgets", json={"category_id": courses, "month": "2026-10", "amount_limit": "250"})
    assert res.status_code == 201
    budget = res.get_json()
    assert budget["spent_cents"] == 23000 and budget["percent"] == 92.0 and budget["status"] == "attention"

    # Même catégorie + même mois : mise à jour, pas de doublon
    again = api.post("/api/budgets", json={"category_id": courses, "month": "2026-10", "amount_limit": "200"}).get_json()
    assert again["id"] == budget["id"] and again["status"] == "depasse"

    data = api.get("/api/budgets?month=2026-10").get_json()
    assert len(data["items"]) == 1
    assert data["unbudgeted"][0]["category_name"] == "Restaurants"

    salaire = _category_id(app, "Salaire")
    assert api.post("/api/budgets", json={"category_id": salaire, "month": "2026-10", "amount_limit": "1"}).status_code == 400

    copy = api.post("/api/budgets/copy", json={"from_month": "2026-10", "to_month": "2026-11"}).get_json()
    assert copy["copied"] == 1 and copy["items"][0]["amount_limit_cents"] == 20000
    assert api.post("/api/budgets/copy", json={"from_month": "2025-01", "to_month": "2026-11"}).status_code == 409

    assert api.patch(f"/api/budgets/{budget['id']}", json={"amount_limit": "300"}).get_json()["amount_limit_cents"] == 30000
    assert api.delete(f"/api/budgets/{budget['id']}").status_code == 204


def test_goals(api):
    acc = _account(api, name="Livret", type="epargne", opening_balance="2500")
    manual = api.post("/api/goals", json={"name": "Vacances", "target_amount": "2000", "current_amount": "500",
                                          "deadline": "2099-06-30"}).get_json()
    assert manual["percent"] == 25.0 and manual["remaining_cents"] == 150000 and manual["monthly_needed_cents"] > 0
    linked = api.post("/api/goals", json={"name": "Matelas", "target_amount": "5000",
                                          "account_id": acc["id"]}).get_json()
    assert linked["progress_cents"] == 250000 and linked["percent"] == 50.0
    assert api.patch(f"/api/goals/{manual['id']}", json={"deadline": None}).get_json()["deadline"] is None
    assert len(api.get("/api/goals").get_json()["items"]) == 2
    assert api.post("/api/goals", json={"name": "X", "target_amount": "0"}).status_code == 400
    assert api.delete(f"/api/goals/{manual['id']}").status_code == 204


def test_migration_from_v1(tmp_path):
    """Une base créée à l'étape 1 (version 1) est mise à jour sans perte de données."""
    path = tmp_path / "v1.db"
    conn = sqlite3.connect(path)
    conn.executescript(database.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO accounts (name) VALUES ('Ancien')")
    conn.commit()
    conn.close()

    conn = database.connect(path)
    database.init_schema(conn)
    assert database.schema_version(conn) == database.LATEST_VERSION
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert "transfer_group" in cols
    assert conn.execute("SELECT name FROM accounts").fetchone()[0] == "Ancien"
    database.init_schema(conn)  # rejouable
    conn.close()
