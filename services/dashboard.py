"""Agrégations du tableau de bord : indicateurs du mois, historique du patrimoine,
répartition des dépenses, dernières opérations et budgets."""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from finance import month_ends, pct_change, savings_rate

from . import accounts as accounts_service
from . import budgets as budgets_service
from . import transactions as transactions_service

# Une opération compte comme revenu / dépense si elle n'est ni un virement lié, ni classée « transfert »
_NOT_TRANSFER = "t.transfer_group IS NULL AND COALESCE(c.kind, '') != 'transfert'"
MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTHS_FR_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                  "septembre", "octobre", "novembre", "décembre"]


def _flows(conn, start: str, end: str) -> tuple[int, int]:
    """(revenus, dépenses) nets entre deux dates incluses, dépenses en négatif.

    Le classement suit la catégorie : un remboursement dans « Courses » réduit les dépenses
    (il ne compte pas comme un revenu). Sans catégorie, le signe décide.
    """
    row = conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN c.kind = 'revenu' OR (c.id IS NULL AND t.amount_cents > 0)
                                     THEN t.amount_cents END), 0),
                   COALESCE(SUM(CASE WHEN c.kind = 'depense' OR (c.id IS NULL AND t.amount_cents < 0)
                                     THEN t.amount_cents END), 0)
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.date BETWEEN ? AND ? AND {_NOT_TRANSFER}""",  # noqa: S608
        (start, end),
    ).fetchone()
    return row[0], row[1]


# --------------------------------------------------------------------------- historique du patrimoine

def _holdings_value_at(conn, dates: list[date]) -> list[int]:
    """Valeur des positions à chaque date : quantité détenue à cette date × dernier cours connu."""
    holdings = conn.execute(
        """SELECT h.id, h.quantity, h.cost_basis_cents, h.price_cents
           FROM holdings h JOIN accounts a ON a.id = h.account_id WHERE a.archived = 0"""
    ).fetchall()
    trades = defaultdict(list)
    for t in conn.execute("SELECT holding_id, date, side, quantity FROM trades ORDER BY date, id"):
        trades[t["holding_id"]].append(t)
    prices = defaultdict(list)
    for p in conn.execute("SELECT holding_id, date, price_cents FROM holding_prices ORDER BY date"):
        prices[p["holding_id"]].append((p["date"], p["price_cents"]))

    totals = [0] * len(dates)
    for h in holdings:
        history = prices[h["id"]]
        history_dates = [d for d, _ in history]
        for i, day in enumerate(dates):
            iso = day.isoformat()
            if trades[h["id"]]:
                qty = sum(t["quantity"] if t["side"] == "achat" else -t["quantity"]
                          for t in trades[h["id"]] if t["date"] <= iso)
                qty = max(qty, 0.0)
            else:
                qty = h["quantity"]  # saisie manuelle : on suppose la quantité détenue sur toute la période
            if qty <= 0:
                continue
            pos = bisect_right(history_dates, iso)
            if pos:
                price = history[pos - 1][1]
            elif h["quantity"] and h["cost_basis_cents"]:
                price = h["cost_basis_cents"] / h["quantity"]  # avant le premier cours connu : prix de revient
            else:
                price = h["price_cents"] or 0
            totals[i] += int(round(qty * price))
    return totals


def history(conn: sqlite3.Connection, months: int = 6, today: date | None = None) -> list[dict]:
    today = today or date.today()
    periods = month_ends(today, months)
    ends = [end for _, end in periods]
    opening = conn.execute("SELECT COALESCE(SUM(opening_balance_cents), 0) FROM accounts WHERE archived = 0").fetchone()[0]
    investments = _holdings_value_at(conn, ends)
    out = []
    for (month, end), invest in zip(periods, investments):
        cash = opening + conn.execute(
            """SELECT COALESCE(SUM(t.amount_cents), 0) FROM transactions t
               JOIN accounts a ON a.id = t.account_id WHERE a.archived = 0 AND t.date <= ?""",
            (end.isoformat(),),
        ).fetchone()[0]
        income, expense = _flows(conn, f"{month}-01", end.isoformat())
        y, m = map(int, month.split("-"))
        out.append({
            "month": month,
            "label": f"{MONTHS_FR[m - 1]} {str(y)[2:]}",
            "end_date": end.isoformat(),
            "cash_cents": cash,
            "investments_cents": invest,
            "total_cents": cash + invest,
            "income_cents": income,
            "expense_cents": expense,
            "partial": end < (end.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1),
        })
    return out


# --------------------------------------------------------------------------- répartition des dépenses

def expenses_by_category(conn: sqlite3.Connection, month: str, limit: int = 6) -> dict:
    rows = conn.execute(
        f"""SELECT c.id, COALESCE(c.name, 'Non catégorisées') AS name, COALESCE(c.color, '#cbd5e1') AS color,
                   -SUM(t.amount_cents) AS amount
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE substr(t.date, 1, 7) = ? AND {_NOT_TRANSFER}
              AND (c.kind = 'depense' OR (c.id IS NULL AND t.amount_cents < 0))
            GROUP BY c.id""",  # noqa: S608
        (month,),
    ).fetchall()
    items = sorted(({"category_id": r["id"], "name": r["name"], "color": r["color"], "amount_cents": r["amount"]}
                    for r in rows if r["amount"] > 0), key=lambda x: -x["amount_cents"])
    total = sum(i["amount_cents"] for i in items)
    # Au-delà de `limit` catégories, les plus petites sont regroupées dans « Autres »
    if len(items) > limit:
        rest = items[limit - 1:]
        items = items[:limit - 1] + [{"category_id": None, "name": f"Autres ({len(rest)})", "color": "#94a3b8",
                                      "amount_cents": sum(i["amount_cents"] for i in rest), "other": True}]
    for i in items:
        i["percent"] = round(i["amount_cents"] / total * 100, 1) if total else 0
    return {"month": month, "total_cents": total, "items": items}


# --------------------------------------------------------------------------- synthèse

def dashboard(conn: sqlite3.Connection, months: int = 6, today: date | None = None) -> dict:
    today = today or date.today()
    months = max(2, min(int(months), 24))
    hist = history(conn, months, today)
    current, previous = hist[-1], hist[-2]

    # Comparaison « à date » : du 1er au même jour du mois précédent (sinon on compare un mois entamé à un mois complet)
    prev_start = date.fromisoformat(f"{previous['month']}-01")
    prev_last_day = date.fromisoformat(previous["end_date"]).day
    prev_end = prev_start.replace(day=min(today.day, prev_last_day))
    prev_income, prev_expense = _flows(conn, prev_start.isoformat(), prev_end.isoformat())

    accounts = accounts_service.list_accounts(conn)
    net_worth = sum(a["total_value_cents"] for a in accounts)
    income, expense = current["income_cents"], current["expense_cents"]
    rate = savings_rate(income, expense)
    prev_rate = savings_rate(prev_income, prev_expense)
    y, m = map(int, previous["month"].split("-"))

    budgets = budgets_service.list_budgets(conn, current["month"])
    return {
        "today": today.isoformat(),
        "month": current["month"],
        "previous_month_label": MONTHS_FR_LONG[m - 1],
        "comparison_day": prev_end.day,
        "kpis": {
            "net_worth_cents": net_worth,
            "net_worth_change_cents": current["total_cents"] - previous["total_cents"],
            "net_worth_change_percent": pct_change(current["total_cents"], previous["total_cents"]),
            "investments_cents": current["investments_cents"],
            "income_cents": income,
            "income_change_percent": pct_change(income, prev_income),
            "expense_cents": expense,
            "expense_change_percent": pct_change(-expense, -prev_expense),
            "savings_rate": rate,
            "savings_rate_change": round(rate - prev_rate, 1) if rate is not None and prev_rate is not None else None,
        },
        "history": hist,
        "categories": expenses_by_category(conn, current["month"]),
        "recent": transactions_service.list_transactions(conn, {"per_page": 8})["items"],
        "budgets": {
            "items": sorted(budgets["items"], key=lambda b: -(b["percent"] or 0))[:5],
            "count": len(budgets["items"]),
            "total_limit_cents": budgets["total_limit_cents"],
            "total_spent_cents": budgets["total_spent_cents"],
        },
        "accounts": [{"id": a["id"], "name": a["name"], "type": a["type"], "color": a["color"],
                      "total_value_cents": a["total_value_cents"]} for a in accounts],
    }
