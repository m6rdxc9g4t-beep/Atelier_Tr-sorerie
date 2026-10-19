import io

import pytest

T212_CSV = """Action,Time,ISIN,Ticker,Name,No. of shares,Price / share,Currency (Price / share),Exchange rate,Result,Currency (Result),Total,Currency (Total),Withholding tax,Currency (Withholding tax),Notes,ID,Currency conversion fee,Currency (Currency conversion fee)
Deposit,2026-01-05 09:00:00,,,,,,,,,,2000.00,EUR,,,Bank Transfer,dep-1,,
Market buy,2026-01-06 10:00:00,IE00BK5BQT80,VWCE,Vanguard FTSE All-World UCITS ETF (Acc),5,110.00,EUR,1.00,,,550.00,EUR,,,,EOF1,,
Currency conversion,2026-02-06 09:59:00,,,,,,,,,,426.50,EUR,,,,conv-1,,
Market buy,2026-02-06 10:00:00,US0378331005,AAPL,Apple,2,230.00,USD,1.08,,,426.50,EUR,,,,EOF2,0.64,EUR
Limit buy,2026-03-06 10:00:00.123,IE00BK5BQT80,VWCE,Vanguard FTSE All-World UCITS ETF (Acc),2.5,120.00,EUR,1.00,,,300.00,EUR,,,,EOF3,,
Market sell,2026-04-01 10:00:00,IE00BK5BQT80,VWCE,Vanguard FTSE All-World UCITS ETF (Acc),1.5,125.00,EUR,1.00,10.50,EUR,187.50,EUR,,,,EOF4,,
Dividend (Dividend),2026-05-10 08:00:00,US0378331005,AAPL,Apple,2,0.25,USD,1.08,,,0.39,EUR,0.07,USD,,,,
Interest on cash,2026-05-31 23:00:00,,,,,,,,,,1.23,EUR,,,,int-may,,
Withdrawal,2026-06-01 12:00:00,,,,,,,,,,-100.00,EUR,,,,wd-1,,
Something new,2026-06-02 12:00:00,,,,,,,,,,5.00,EUR,,,,odd-1,,
"""


def _investment_account(api, name="Trading 212"):
    res = api.post("/api/accounts", json={"name": name, "type": "investissement"})
    return res.get_json()["id"]


def _t212(api, account_id, csv=T212_CSV, dry_run=True):
    return api.post("/api/import/trading212", data={
        "file": (io.BytesIO(csv.encode()), "from_2026.csv"),
        "account_id": str(account_id),
        "dry_run": "1" if dry_run else "0",
    }, content_type="multipart/form-data")


# --------------------------------------------------------------------------- positions manuelles

def test_manual_metal_and_valuation(api):
    acc = _investment_account(api, "Or physique")
    res = api.post("/api/holdings", json={
        "account_id": acc, "name": "Napoléon 20 F", "asset_type": "metal", "metal": "or",
        "unit": "piece", "weight_g": "6,45", "purity": 900, "quantity": 4, "cost_basis": "1600", "price": "520",
    })
    assert res.status_code == 201, res.get_json()
    h = res.get_json()
    assert h["value_cents"] == 208000 and h["gain_cents"] == 48000 and h["gain_percent"] == 30.0
    assert h["fine_grams"] == pytest.approx(23.22) and h["average_price_cents"] == 40000

    # La valeur des positions s'ajoute au solde du compte
    account = api.get(f"/api/accounts/{acc}").get_json()
    assert account["holdings_value_cents"] == 208000 and account["total_value_cents"] == 208000
    assert api.get("/api/accounts").get_json()["total_balance_cents"] == 208000

    # Mise à jour groupée des prix + historique
    assert api.post("/api/holdings/prices", json={"prices": [{"id": h["id"], "price": "535,50"}]}).get_json() == {"updated": 1}
    assert api.get(f"/api/holdings/{h['id']}").get_json()["value_cents"] == 214200

    # Un objectif lié au compte suit sa valeur totale
    goal = api.post("/api/goals", json={"name": "Or", "target_amount": "4284", "account_id": acc}).get_json()
    assert goal["percent"] == 50.0


def test_holding_validation(api):
    inv = _investment_account(api)
    courant = api.post("/api/accounts", json={"name": "Courant"}).get_json()["id"]

    res = api.post("/api/holdings", json={"account_id": courant, "name": "X", "quantity": 1})
    assert "account_id" in res.get_json()["fields"]
    res = api.post("/api/holdings", json={"account_id": inv, "name": "Lingot", "asset_type": "metal", "quantity": 1,
                                          "unit": "titre"})
    assert set(res.get_json()["fields"]) == {"metal", "unit"}
    res = api.post("/api/holdings", json={"account_id": inv, "name": "Pièces", "asset_type": "metal", "metal": "argent",
                                          "unit": "piece", "quantity": 10})
    assert "weight_g" in res.get_json()["fields"]
    res = api.post("/api/holdings", json={"account_id": inv, "name": "ETF", "unit": "g", "quantity": 1, "isin": "FR123"})
    assert {"unit", "isin"} <= set(res.get_json()["fields"])
    assert api.post("/api/holdings", json={"account_id": inv, "name": "Q", "quantity": "-1"}).status_code == 400

    ok = api.post("/api/holdings", json={"account_id": inv, "name": "Lingot 100 g", "asset_type": "metal",
                                         "metal": "or", "quantity": "100", "purity": "999,9"}).get_json()
    assert ok["unit"] == "g" and ok["value_cents"] == 0 and ok["fine_grams"] == pytest.approx(99.99)
    # Passer d'un métal à une action remet l'unité à « titre » et efface le métal
    changed = api.patch(f"/api/holdings/{ok['id']}", json={"asset_type": "action"}).get_json()
    assert changed["unit"] == "titre" and changed["metal"] is None
    assert api.delete(f"/api/holdings/{ok['id']}").status_code == 204


# --------------------------------------------------------------------------- Trading 212

def test_trading212_preview(api):
    acc = _investment_account(api)
    res = _t212(api, acc)
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert data["summary"]["new"] == 8 and data["summary"]["ignored"] == 2  # conversion + action inconnue
    kinds = {k["kind"]: k for k in data["by_kind"]}
    assert kinds["achat"]["count"] == 3 and kinds["achat"]["amount_cents"] == -127650
    assert kinds["retrait"]["amount_cents"] == -10000  # signe déduit du type, pas du fichier
    vwce = next(p for p in data["positions"] if p["key"] == "IE00BK5BQT80")
    assert vwce["quantity"] == 6 and vwce["cost_basis_cents"] == 68000
    # Un aperçu n'écrit rien
    assert api.get(f"/api/transactions?account_id={acc}").get_json()["total"] == 0


def test_trading212_commit_positions_and_dedupe(app, api):
    acc = _investment_account(api)
    res = _t212(api, acc, dry_run=False)
    assert res.status_code == 201
    assert res.get_json() == {"inserted": 8, "trades": 4, "positions_updated": 2}

    holdings = api.get(f"/api/holdings?account_id={acc}").get_json()
    vwce = next(h for h in holdings["items"] if h["isin"] == "IE00BK5BQT80")
    assert vwce["quantity"] == 6 and vwce["cost_basis_cents"] == 68000
    assert vwce["price_cents"] == 12500 and vwce["value_cents"] == 75000 and vwce["gain_cents"] == 7000
    assert vwce["asset_type"] == "etf" and vwce["source"] == "trading212"
    assert holdings["totals"]["value_cents"] == 75000 + 42650

    account = api.get(f"/api/accounts/{acc}").get_json()
    assert account["balance_cents"] == 81262                     # liquidités
    assert account["total_value_cents"] == 81262 + 75000 + 42650  # + positions

    # Achats / ventes et dépôts ne sont ni des revenus ni des dépenses ; dividendes et intérêts sont des revenus
    tx = api.get(f"/api/transactions?account_id={acc}").get_json()
    assert tx["expense_cents"] == 0 and tx["income_cents"] == 39 + 123

    # Réimport : rien n'est dupliqué
    again = _t212(api, acc, dry_run=False).get_json()
    assert again["inserted"] == 0 and again["trades"] == 0
    assert api.get(f"/api/holdings/{vwce['id']}").get_json()["quantity"] == 6

    # Export suivant qui chevauche le précédent : seule la nouvelle ligne est ajoutée
    newer = T212_CSV + "Market buy,2026-07-01 10:00:00,IE00BK5BQT80,VWCE,Vanguard FTSE All-World UCITS ETF (Acc),1,130.00,EUR,1.00,,,130.00,EUR,,,,EOF5,,\n"
    assert _t212(api, acc, newer, dry_run=False).get_json()["inserted"] == 1
    vwce = api.get(f"/api/holdings/{vwce['id']}").get_json()
    assert vwce["quantity"] == 7 and vwce["cost_basis_cents"] == 81000 and vwce["price_cents"] == 13000

    # Quantité calculée depuis l'historique : modification manuelle refusée, prix autorisé
    assert api.patch(f"/api/holdings/{vwce['id']}", json={"quantity": 10}).status_code == 400
    assert api.patch(f"/api/holdings/{vwce['id']}", json={"price": "140"}).get_json()["value_cents"] == 98000


def test_trading212_errors(api):
    acc = _investment_account(api)
    courant = api.post("/api/accounts", json={"name": "Courant"}).get_json()["id"]
    assert _t212(api, courant).status_code == 400
    res = _t212(api, acc, "Date;Libellé;Montant\n01/01/2026;X;-1\n")
    assert res.status_code == 400 and "Trading 212" in res.get_json()["error"]
    usd = "Action,Time,Total,Currency (Total)\nDeposit,2026-01-01 10:00:00,100,USD\n"
    data = _t212(api, acc, usd).get_json()
    assert data["summary"]["new"] == 0 and "USD" in data["ignored"][0]["reason"]
