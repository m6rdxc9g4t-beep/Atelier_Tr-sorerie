from datetime import date

import database
from services import dashboard

TODAY = date(2026, 10, 18)


def _conn(app):
    return database.connect(app.config["DATABASE_PATH"])


def _cat(conn, name):
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def _setup(conn):
    acc = conn.execute("INSERT INTO accounts (name, opening_balance_cents) VALUES ('Courant', 100000)").lastrowid
    inv = conn.execute("INSERT INTO accounts (name, type) VALUES ('Bourse', 'investissement')").lastrowid
    rows = [
        (acc, "Salaire", "2026-09-01", 300000), (acc, "Courses", "2026-09-10", -40000),
        (acc, "Courses", "2026-09-25", -20000),                     # après le 18 : exclu de la comparaison « à date »
        (acc, "Salaire", "2026-10-01", 300000), (acc, "Courses", "2026-10-05", -50000),
        (acc, "Restaurants", "2026-10-06", -10000), (acc, None, "2026-10-07", -5000),
        (acc, "Courses", "2026-10-08", 2000),                       # remboursement : réduit la dépense
    ]
    for account, cat, day, cents in rows:
        conn.execute("INSERT INTO transactions (account_id, category_id, date, label, amount_cents) VALUES (?, ?, ?, ?, ?)",
                     (account, _cat(conn, cat) if cat else None, day, cat or "Divers", cents))
    # Virement lié vers le compte d'investissement : ni revenu ni dépense
    for account, cents in ((acc, -100000), (inv, 100000)):
        conn.execute("INSERT INTO transactions (account_id, category_id, date, label, amount_cents, transfer_group) "
                     "VALUES (?, ?, '2026-09-15', 'Virement', ?, 'g1')", (account, _cat(conn, "Virement interne"), cents))
    # Achat de 10 titres à 50 € en septembre (liquidités du compte bourse -> position), cours à 60 € en octobre
    tx = conn.execute("INSERT INTO transactions (account_id, category_id, date, label, amount_cents) VALUES (?, ?, '2026-09-16', 'Achat', -50000)",
                      (inv, _cat(conn, "Achat / vente de titres"))).lastrowid
    h = conn.execute("INSERT INTO holdings (account_id, name, quantity, cost_basis_cents, price_cents) VALUES (?, 'ETF', 10, 50000, 6000)", (inv,)).lastrowid
    conn.execute("INSERT INTO trades (holding_id, transaction_id, date, side, quantity, amount_cents) VALUES (?, ?, '2026-09-16', 'achat', 10, 50000)", (h, tx))
    conn.executemany("INSERT INTO holding_prices (holding_id, date, price_cents) VALUES (?, ?, ?)",
                     [(h, "2026-09-16", 5000), (h, "2026-10-10", 6000)])
    conn.commit()


def test_history_cash_and_investments(app):
    conn = _conn(app)
    _setup(conn)
    hist = dashboard.history(conn, 3, TODAY)
    assert [m["month"] for m in hist] == ["2026-08", "2026-09", "2026-10"]
    aug, sep, oct_ = hist
    assert aug["total_cents"] == 100000 and aug["investments_cents"] == 0  # avant l'achat : pas de position
    # Septembre : 1000 + 3000 - 400 - 200 - 500 (achat) = 2900 € de liquidités, 10 × 50 € de titres
    assert sep["cash_cents"] == 290000 and sep["investments_cents"] == 50000 and sep["total_cents"] == 340000
    assert sep["income_cents"] == 300000 and sep["expense_cents"] == -60000  # ni virement ni achat de titres
    assert not sep["partial"] and oct_["partial"]
    # Octobre : liquidités 2900 + 3000 - 500 - 100 - 50 + 20 = 5270 €, titres 10 × 60 €
    assert oct_["cash_cents"] == 527000 and oct_["investments_cents"] == 60000
    conn.close()


def test_dashboard_kpis_and_categories(app):
    conn = _conn(app)
    _setup(conn)
    d = dashboard.dashboard(conn, 6, TODAY)
    k = d["kpis"]
    assert k["net_worth_cents"] == 527000 + 60000
    assert k["net_worth_change_cents"] == 587000 - 340000
    assert k["income_cents"] == 300000 and k["expense_cents"] == -63000
    # Comparaison au 18 septembre : 400 € de courses (celles du 25 sont exclues)
    assert d["comparison_day"] == 18 and k["expense_change_percent"] == round((63000 - 40000) / 40000 * 100, 1)
    assert k["savings_rate"] == 79.0 and k["savings_rate_change"] == round(79.0 - 86.7, 1)

    cats = {c["name"]: c["amount_cents"] for c in d["categories"]["items"]}
    assert cats == {"Courses": 48000, "Restaurants": 10000, "Non catégorisées": 5000}
    assert d["categories"]["total_cents"] == 63000
    assert len(d["recent"]) == 8 and d["budgets"]["count"] == 0
    conn.close()


def test_categories_folded_into_others(app):
    conn = _conn(app)
    acc = conn.execute("INSERT INTO accounts (name) VALUES ('C')").lastrowid
    names = ["Courses", "Restaurants", "Loisirs", "Shopping", "Santé", "Transport", "Abonnements", "Divers"]
    for i, name in enumerate(names):
        conn.execute("INSERT INTO transactions (account_id, category_id, date, label, amount_cents) VALUES (?, ?, '2026-10-02', 'x', ?)",
                     (acc, _cat(conn, name), -(1000 * (i + 1))))
    conn.commit()
    c = dashboard.expenses_by_category(conn, "2026-10", limit=6)
    assert len(c["items"]) == 6 and c["items"][-1]["name"] == "Autres (3)"
    assert c["items"][-1]["amount_cents"] == 1000 + 2000 + 3000
    assert round(sum(i["percent"] for i in c["items"])) == 100
    conn.close()


def test_dashboard_api_on_demo_data(api, app):
    conn = _conn(app)
    database.seed_demo(conn)
    conn.close()
    data = api.get("/api/dashboard?months=12").get_json()
    assert len(data["history"]) == 12
    assert data["kpis"]["net_worth_cents"] == sum(a["total_value_cents"] for a in data["accounts"])
    assert data["history"][-1]["total_cents"] == data["kpis"]["net_worth_cents"]
    assert data["categories"]["items"] and data["budgets"]["count"] == 5
