"""Budgets mensuels par catégorie et objectifs d'épargne."""
from __future__ import annotations

import sqlite3
from datetime import date

from .validation import ConflictError, NotFoundError, ValidationError, Validator, ensure_exists, update_row


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def _month_or_current(month: str | None) -> str:
    v = Validator({"month": month or current_month()})
    v.month("month", required=True)
    return v.result()["month"]


def _status(percent: float | None) -> str:
    if percent is None:
        return "ok"
    if percent >= 100:
        return "depasse"
    if percent >= 80:
        return "attention"
    return "ok"


# --------------------------------------------------------------------------- budgets

def list_budgets(conn: sqlite3.Connection, month: str | None = None) -> dict:
    """Budgets du mois avec consommé / restant, + dépenses des catégories sans budget."""
    month = _month_or_current(month)
    # Dépense nette du mois par catégorie (un remboursement réduit la dépense)
    spent_rows = conn.execute(
        """SELECT t.category_id, -SUM(t.amount_cents) AS spent_cents
           FROM transactions t JOIN categories c ON c.id = t.category_id
           WHERE substr(t.date, 1, 7) = ? AND c.kind = 'depense' AND t.transfer_group IS NULL
           GROUP BY t.category_id""",
        (month,),
    ).fetchall()
    spent = {r["category_id"]: max(0, r["spent_cents"]) for r in spent_rows}

    items = []
    for row in conn.execute(
        """SELECT b.id, b.category_id, b.month, b.amount_limit_cents,
                  c.name AS category_name, c.color AS category_color
           FROM budgets b JOIN categories c ON c.id = b.category_id
           WHERE b.month = ? ORDER BY c.name""",
        (month,),
    ):
        used = spent.get(row["category_id"], 0)
        limit = row["amount_limit_cents"]
        percent = round(used / limit * 100, 1) if limit else None
        items.append({
            **dict(row),
            "spent_cents": used,
            "remaining_cents": limit - used,
            "percent": percent,
            "status": _status(percent if limit else (100 if used else 0)),
        })

    budgeted = {b["category_id"] for b in items}
    unbudgeted = [
        {"category_id": r["id"], "category_name": r["name"], "category_color": r["color"],
         "spent_cents": spent[r["id"]]}
        for r in conn.execute("SELECT id, name, color FROM categories WHERE kind = 'depense' ORDER BY name")
        if r["id"] not in budgeted and spent.get(r["id"])
    ]
    unbudgeted.sort(key=lambda x: -x["spent_cents"])

    total_limit = sum(b["amount_limit_cents"] for b in items)
    total_spent = sum(b["spent_cents"] for b in items)
    return {
        "month": month,
        "items": items,
        "unbudgeted": unbudgeted,
        "total_limit_cents": total_limit,
        "total_spent_cents": total_spent,
        "total_percent": round(total_spent / total_limit * 100, 1) if total_limit else None,
    }


def _get_budget(conn, budget_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()
    if not row:
        raise NotFoundError("Budget introuvable.")
    return row


def _budget_item(conn, budget_id: int) -> dict:
    row = _get_budget(conn, budget_id)
    return next(b for b in list_budgets(conn, row["month"])["items"] if b["id"] == budget_id)


def upsert_budget(conn: sqlite3.Connection, data: dict | None) -> dict:
    """Crée le budget (catégorie, mois) ou met à jour son plafond s'il existe déjà."""
    v = Validator(data)
    v.integer_id("category_id", required=True)
    v.month("month", required=True)
    v.money("amount_limit", "amount_limit_cents", required=True, positive=True)
    clean = v.result()
    ensure_exists(conn, "categories", clean["category_id"], "Catégorie")
    kind = conn.execute("SELECT kind FROM categories WHERE id = ?", (clean["category_id"],)).fetchone()[0]
    if kind != "depense":
        raise ValidationError("Un budget ne peut porter que sur une catégorie de dépense.",
                              {"category_id": "Catégorie de dépense attendue."})
    conn.execute(
        """INSERT INTO budgets (category_id, month, amount_limit_cents) VALUES (?, ?, ?)
           ON CONFLICT (category_id, month) DO UPDATE SET amount_limit_cents = excluded.amount_limit_cents""",
        (clean["category_id"], clean["month"], clean["amount_limit_cents"]),
    )
    conn.commit()
    budget_id = conn.execute(
        "SELECT id FROM budgets WHERE category_id = ? AND month = ?", (clean["category_id"], clean["month"])
    ).fetchone()[0]
    return _budget_item(conn, budget_id)


def update_budget(conn: sqlite3.Connection, budget_id: int, data: dict | None) -> dict:
    _get_budget(conn, budget_id)
    v = Validator(data, partial=True)
    v.money("amount_limit", "amount_limit_cents", required=True, positive=True)
    update_row(conn, "budgets", budget_id, v.result())
    conn.commit()
    return _budget_item(conn, budget_id)


def delete_budget(conn: sqlite3.Connection, budget_id: int) -> None:
    _get_budget(conn, budget_id)
    conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
    conn.commit()


def copy_budgets(conn: sqlite3.Connection, data: dict | None) -> dict:
    """Recopie les budgets d'un mois vers un autre (sans écraser ceux déjà définis)."""
    v = Validator(data)
    v.month("from_month", required=True)
    v.month("to_month", required=True)
    clean = v.result()
    if clean["from_month"] == clean["to_month"]:
        raise ValidationError("Choisissez deux mois différents.")
    cur = conn.execute(
        """INSERT OR IGNORE INTO budgets (category_id, month, amount_limit_cents)
           SELECT category_id, ?, amount_limit_cents FROM budgets WHERE month = ?""",
        (clean["to_month"], clean["from_month"]),
    )
    conn.commit()
    if cur.rowcount == 0 and not conn.execute(
        "SELECT 1 FROM budgets WHERE month = ?", (clean["from_month"],)
    ).fetchone():
        raise ConflictError("Aucun budget à recopier pour ce mois.")
    return {"copied": cur.rowcount, **list_budgets(conn, clean["to_month"])}


# --------------------------------------------------------------------------- objectifs

_GOAL_SELECT = """
    SELECT g.id, g.name, g.target_amount_cents, g.current_amount_cents, g.deadline, g.account_id,
           g.created_at, a.name AS account_name, b.balance_cents AS account_balance_cents
    FROM goals g
    LEFT JOIN accounts a ON a.id = g.account_id
    LEFT JOIN v_account_balances b ON b.id = g.account_id
"""


def _serialize_goal(row: sqlite3.Row) -> dict:
    goal = dict(row)
    # Objectif lié à un compte : la progression suit le solde du compte
    progress = goal["account_balance_cents"] if goal["account_id"] else goal["current_amount_cents"]
    progress = max(0, progress or 0)
    goal["progress_cents"] = progress
    goal["percent"] = round(min(progress / goal["target_amount_cents"] * 100, 100), 1)
    goal["remaining_cents"] = max(0, goal["target_amount_cents"] - progress)
    goal["months_left"] = None
    goal["monthly_needed_cents"] = None
    if goal["deadline"]:
        today = date.today()
        deadline = date.fromisoformat(goal["deadline"])
        months = (deadline.year - today.year) * 12 + deadline.month - today.month
        goal["months_left"] = max(0, months)
        if goal["remaining_cents"]:
            goal["monthly_needed_cents"] = -(-goal["remaining_cents"] // max(1, months))
    return goal


def _validate_goal(conn, data: dict | None, partial: bool) -> dict:
    v = Validator(data, partial)
    v.text("name", required=True, max_len=80)
    v.money("target_amount", "target_amount_cents", required=True, positive=True, non_zero=True)
    v.money("current_amount", "current_amount_cents", positive=True)
    v.date("deadline")
    v.integer_id("account_id")
    clean = v.result()
    if clean.get("account_id"):
        ensure_exists(conn, "accounts", clean["account_id"], "Compte")
    return clean


def list_goals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"{_GOAL_SELECT} ORDER BY g.deadline IS NULL, g.deadline, g.name").fetchall()  # noqa: S608
    return [_serialize_goal(r) for r in rows]


def get_goal(conn: sqlite3.Connection, goal_id: int) -> dict:
    row = conn.execute(f"{_GOAL_SELECT} WHERE g.id = ?", (goal_id,)).fetchone()  # noqa: S608
    if not row:
        raise NotFoundError("Objectif introuvable.")
    return _serialize_goal(row)


def create_goal(conn: sqlite3.Connection, data: dict | None) -> dict:
    clean = {k: v for k, v in _validate_goal(conn, data, partial=False).items() if v is not None}
    cur = conn.execute(
        f"INSERT INTO goals ({', '.join(clean)}) VALUES ({', '.join('?' * len(clean))})",  # noqa: S608
        tuple(clean.values()),
    )
    conn.commit()
    return get_goal(conn, cur.lastrowid)


def update_goal(conn: sqlite3.Connection, goal_id: int, data: dict | None) -> dict:
    get_goal(conn, goal_id)
    update_row(conn, "goals", goal_id, _validate_goal(conn, data, partial=True))
    conn.commit()
    return get_goal(conn, goal_id)


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    get_goal(conn, goal_id)
    conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
