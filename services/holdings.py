"""Positions des comptes d'investissement : titres, fonds, crypto et métaux précieux.

Valorisation : quantité × dernier prix unitaire connu. Sans prix, la position est
valorisée à son prix de revient (aucune plus-value affichée).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date

from .validation import NotFoundError, ValidationError, Validator, update_row

ASSET_TYPES = ("action", "etf", "fonds", "obligation", "crypto", "metal", "autre")
ASSET_LABELS = {
    "action": "Action", "etf": "ETF", "fonds": "Fonds", "obligation": "Obligation",
    "crypto": "Crypto", "metal": "Métal précieux", "autre": "Autre",
}
METALS = ("or", "argent", "platine", "palladium")
UNITS = ("titre", "g", "oz", "piece")
UNIT_LABELS = {"titre": "titre", "g": "g", "oz": "oz", "piece": "pièce"}
TROY_OUNCE_G = 31.1034768
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Valeur d'une position en centimes (SQL) — réutilisée par les comptes et les objectifs
VALUE_SQL = "CAST(ROUND(CASE WHEN h.price_cents IS NULL THEN h.cost_basis_cents ELSE h.quantity * h.price_cents END) AS INTEGER)"


def holdings_value_by_account(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(f"SELECT h.account_id, SUM({VALUE_SQL}) FROM holdings h GROUP BY h.account_id")  # noqa: S608
    return {account_id: value or 0 for account_id, value in rows}


# --------------------------------------------------------------------------- lecture

_SELECT = f"""
    SELECT h.*, a.name AS account_name, a.color AS account_color, {VALUE_SQL} AS value_cents,
           (SELECT COUNT(*) FROM trades t WHERE t.holding_id = h.id) AS trade_count
    FROM holdings h JOIN accounts a ON a.id = h.account_id
"""


def fine_grams(h: dict) -> float | None:
    """Poids de métal fin détenu (utile pour comparer au cours de l'or / de l'argent)."""
    if h["asset_type"] != "metal":
        return None
    per_unit = {"g": 1.0, "oz": TROY_OUNCE_G, "piece": h.get("weight_g") or 0.0}.get(h["unit"], 0.0)
    return round(h["quantity"] * per_unit * (h.get("purity") or 1000) / 1000, 3)


def _serialize(row: sqlite3.Row) -> dict:
    h = dict(row)
    h["asset_label"] = ASSET_LABELS.get(h["asset_type"], h["asset_type"])
    h["unit_label"] = UNIT_LABELS.get(h["unit"], h["unit"])
    h["gain_cents"] = h["value_cents"] - h["cost_basis_cents"]
    h["gain_percent"] = round(h["gain_cents"] / h["cost_basis_cents"] * 100, 2) if h["cost_basis_cents"] else None
    h["average_price_cents"] = round(h["cost_basis_cents"] / h["quantity"]) if h["quantity"] else None
    h["fine_grams"] = fine_grams(h)
    h["closed"] = h["quantity"] == 0
    return h


def list_holdings(conn: sqlite3.Connection, account_id: int | None = None, include_closed: bool = False) -> dict:
    clauses, params = [], []
    if account_id:
        clauses.append("h.account_id = ?")
        params.append(account_id)
    if not include_closed:
        clauses.append("h.quantity > 0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    items = [_serialize(r) for r in conn.execute(
        f"{_SELECT} {where} ORDER BY {VALUE_SQL} DESC, h.name", params  # noqa: S608
    )]
    value = sum(h["value_cents"] for h in items)
    cost = sum(h["cost_basis_cents"] for h in items)
    for h in items:
        h["weight_percent"] = round(h["value_cents"] / value * 100, 1) if value else 0
    by_type: dict[str, int] = {}
    for h in items:
        by_type[h["asset_type"]] = by_type.get(h["asset_type"], 0) + h["value_cents"]
    return {
        "items": items,
        "totals": {
            "value_cents": value,
            "cost_cents": cost,
            "gain_cents": value - cost,
            "gain_percent": round((value - cost) / cost * 100, 2) if cost else None,
        },
        "by_type": [{"asset_type": k, "label": ASSET_LABELS[k], "value_cents": v}
                    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
    }


def get_holding(conn: sqlite3.Connection, holding_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE h.id = ?", (holding_id,)).fetchone()  # noqa: S608
    if not row:
        raise NotFoundError("Position introuvable.")
    return _serialize(row)


# --------------------------------------------------------------------------- écriture

def _check_account(conn, account_id: int, errors: dict) -> None:
    row = conn.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not row:
        errors["account_id"] = "Compte introuvable."
    elif row["type"] != "investissement":
        errors["account_id"] = "Choisissez un compte de type Investissement."


def _validate(conn, data: dict | None, partial: bool, current: dict | None = None) -> dict:
    v = Validator(data, partial)
    v.integer_id("account_id", required=True)
    v.text("name", required=True, max_len=120)
    v.choice("asset_type", ASSET_TYPES)
    v.text("symbol", max_len=20)
    v.text("isin", max_len=12)
    v.choice("metal", METALS)
    v.choice("unit", UNITS)
    v.decimal("purity", minimum=0, maximum=1000, exclusive_min=True, nullable=True)
    v.decimal("weight_g", minimum=0, exclusive_min=True, nullable=True)
    v.decimal("quantity", required=True, minimum=0)
    v.money("cost_basis", "cost_basis_cents", positive=True)
    v.money("price", "price_cents", positive=True)
    v.text("notes", max_len=1000)
    if v.clean.get("account_id"):
        _check_account(conn, v.clean["account_id"], v.errors)
    if v.clean.get("isin"):
        v.clean["isin"] = v.clean["isin"].upper()
        if not _ISIN_RE.match(v.clean["isin"]):
            v.errors["isin"] = "ISIN invalide (12 caractères, ex. IE00BK5BQT80)."
    if v.clean.get("symbol"):
        v.clean["symbol"] = v.clean["symbol"].upper()

    # Cohérence type / unité / métal, en tenant compte des valeurs déjà enregistrées
    merged = {**(current or {}), **v.clean}
    asset_type = merged.get("asset_type") or "action"
    if asset_type != "metal" and "unit" not in v.clean:
        unit = "titre"  # passage d'un métal à un titre : l'unité suit
        if current and current.get("unit") != "titre":
            v.clean["unit"] = "titre"
    else:
        unit = merged.get("unit") or ("g" if asset_type == "metal" else "titre")
    if asset_type == "metal":
        if not merged.get("metal"):
            v.errors["metal"] = "Précisez le métal."
        if unit == "titre":
            v.errors["unit"] = "Unité attendue : gramme, once ou pièce."
        if unit == "piece" and not merged.get("weight_g"):
            v.errors["weight_g"] = "Indiquez le poids d'une pièce (en grammes)."
    else:
        if unit != "titre":
            v.errors["unit"] = "Les unités g / oz / pièce sont réservées aux métaux précieux."
        if not partial or "asset_type" in v.clean or v.clean.get("metal"):
            v.clean["metal"] = None
    clean = v.result()
    if not partial:
        clean.setdefault("asset_type", asset_type)
        clean.setdefault("unit", unit)
    if "price_cents" in clean:
        clean["price_updated_at"] = date.today().isoformat()
    return clean


def _record_price(conn, holding_id: int, price_cents: int, day: str | None = None) -> None:
    conn.execute(
        "INSERT INTO holding_prices (holding_id, date, price_cents) VALUES (?, ?, ?) "
        "ON CONFLICT (holding_id, date) DO UPDATE SET price_cents = excluded.price_cents",
        (holding_id, day or date.today().isoformat(), price_cents),
    )


def create_holding(conn: sqlite3.Connection, data: dict | None) -> dict:
    clean = {k: v for k, v in _validate(conn, data, partial=False).items() if v is not None}
    cur = conn.execute(
        f"INSERT INTO holdings ({', '.join(clean)}) VALUES ({', '.join('?' * len(clean))})",  # noqa: S608
        tuple(clean.values()),
    )
    if clean.get("price_cents") is not None:
        _record_price(conn, cur.lastrowid, clean["price_cents"])
    conn.commit()
    return get_holding(conn, cur.lastrowid)


def update_holding(conn: sqlite3.Connection, holding_id: int, data: dict | None) -> dict:
    current = get_holding(conn, holding_id)
    clean = _validate(conn, data, partial=True, current=current)
    if current["trade_count"] and ({"quantity", "cost_basis_cents"} & set(clean)):
        raise ValidationError(
            "Quantité et prix de revient sont calculés à partir des achats / ventes importés : "
            "réimportez l'historique plutôt que de les modifier à la main."
        )
    update_row(conn, "holdings", holding_id, clean, touch=True)
    if clean.get("price_cents") is not None:
        _record_price(conn, holding_id, clean["price_cents"])
    conn.commit()
    return get_holding(conn, holding_id)


def delete_holding(conn: sqlite3.Connection, holding_id: int) -> None:
    get_holding(conn, holding_id)
    conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
    conn.commit()


def update_prices(conn: sqlite3.Connection, data: dict | None) -> dict:
    """Mise à jour groupée : {"prices": [{"id": 1, "price": "84,12"}, ...]}."""
    prices = (data or {}).get("prices")
    if not isinstance(prices, list) or not prices:
        raise ValidationError("Aucun prix à mettre à jour.")
    errors, updates = {}, []
    for item in prices:
        v = Validator(item if isinstance(item, dict) else None)
        v.integer_id("id", required=True)
        v.money("price", "price_cents", required=True, positive=True)
        try:
            clean = v.result()
        except ValidationError as exc:
            errors[str((item or {}).get("id") if isinstance(item, dict) else "?")] = next(iter(exc.fields.values()), exc.message)
            continue
        updates.append(clean)
    if errors:
        raise ValidationError("Certains prix sont invalides.", errors)
    today = date.today().isoformat()
    updated = 0
    for u in updates:
        cur = conn.execute(
            "UPDATE holdings SET price_cents = ?, price_updated_at = ?, updated_at = datetime('now') WHERE id = ?",
            (u["price_cents"], today, u["id"]),
        )
        if cur.rowcount:
            _record_price(conn, u["id"], u["price_cents"], today)
            updated += cur.rowcount
    conn.commit()
    return {"updated": updated}


# --------------------------------------------------------------------------- recalcul depuis les opérations

def recompute_from_trades(conn: sqlite3.Connection, holding_id: int) -> None:
    """Quantité et prix de revient au coût moyen pondéré, dans l'ordre chronologique."""
    quantity, cost = 0.0, 0.0
    last = None
    for t in conn.execute(
        "SELECT date, side, quantity, amount_cents FROM trades WHERE holding_id = ? ORDER BY date, id", (holding_id,)
    ):
        if t["side"] == "achat":
            quantity += t["quantity"]
            cost += t["amount_cents"]
        elif quantity > 0:
            sold = min(t["quantity"], quantity)
            cost -= cost * sold / quantity
            quantity -= sold
        if quantity < 1e-9:
            quantity, cost = 0.0, 0.0
        last = t
    if last is None:
        return
    holding = conn.execute("SELECT price_updated_at FROM holdings WHERE id = ?", (holding_id,)).fetchone()
    sets = {"quantity": round(quantity, 10), "cost_basis_cents": int(round(cost))}
    # Sans prix plus récent saisi à la main, le dernier prix d'exécution sert de cours
    if not holding["price_updated_at"] or holding["price_updated_at"] <= last["date"]:
        unit_price = int(round(last["amount_cents"] / last["quantity"]))
        sets.update(price_cents=unit_price, price_updated_at=last["date"])
        _record_price(conn, holding_id, unit_price, last["date"])
    update_row(conn, "holdings", holding_id, sets, touch=True)
