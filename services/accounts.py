"""Comptes bancaires, d'épargne et d'investissement."""
from __future__ import annotations

import sqlite3

from .validation import ConflictError, NotFoundError, Validator, update_row

ACCOUNT_TYPES = ("courant", "epargne", "investissement", "credit", "especes")
TYPE_LABELS = {
    "courant": "Compte courant",
    "epargne": "Épargne",
    "investissement": "Investissement",
    "credit": "Crédit",
    "especes": "Espèces",
}


def _validate(data: dict | None, partial: bool) -> dict:
    v = Validator(data, partial)
    v.text("name", required=True, max_len=80)
    v.choice("type", ACCOUNT_TYPES)
    v.text("institution", max_len=80)
    v.text("currency", max_len=3)
    v.money("opening_balance", "opening_balance_cents")
    v.color("color")
    v.boolean("archived")
    clean = v.result()
    if clean.get("currency"):
        clean["currency"] = clean["currency"].upper()
    elif "currency" in clean:
        clean.pop("currency")  # colonne NOT NULL : on garde la valeur existante / par défaut
    return clean


def _serialize(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["archived"] = bool(data["archived"])
    data["type_label"] = TYPE_LABELS.get(data["type"], data["type"])
    return data


_SELECT = """
    SELECT a.id, a.name, a.type, a.institution, a.currency, a.color, a.archived,
           a.opening_balance_cents, a.created_at,
           b.balance_cents,
           (SELECT COUNT(*) FROM transactions t WHERE t.account_id = a.id) AS transaction_count,
           (SELECT MAX(date) FROM transactions t WHERE t.account_id = a.id) AS last_transaction_date
    FROM accounts a
    JOIN v_account_balances b ON b.id = a.id
"""


def list_accounts(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    where = "" if include_archived else "WHERE a.archived = 0"
    rows = conn.execute(f"{_SELECT} {where} ORDER BY a.archived, a.type, a.name").fetchall()  # noqa: S608
    return [_serialize(r) for r in rows]


def get_account(conn: sqlite3.Connection, account_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE a.id = ?", (account_id,)).fetchone()  # noqa: S608
    if not row:
        raise NotFoundError("Compte introuvable.")
    return _serialize(row)


def create_account(conn: sqlite3.Connection, data: dict | None) -> dict:
    clean = _validate(data, partial=False)
    clean.setdefault("type", "courant")
    clean.pop("archived", None)
    clean = {k: val for k, val in clean.items() if val is not None}
    cols = ", ".join(clean)
    cur = conn.execute(
        f"INSERT INTO accounts ({cols}) VALUES ({', '.join('?' * len(clean))})",  # noqa: S608
        tuple(clean.values()),
    )
    conn.commit()
    return get_account(conn, cur.lastrowid)


def update_account(conn: sqlite3.Connection, account_id: int, data: dict | None) -> dict:
    get_account(conn, account_id)
    update_row(conn, "accounts", account_id, _validate(data, partial=True))
    conn.commit()
    return get_account(conn, account_id)


def delete_account(conn: sqlite3.Connection, account_id: int, force: bool = False) -> None:
    account = get_account(conn, account_id)
    n = account["transaction_count"]
    if n and not force:
        raise ConflictError(
            f"Ce compte contient {n} transaction(s). Archivez-le, ou confirmez la suppression "
            "définitive de ses transactions.",
            {"transaction_count": str(n)},
        )
    # Un virement dont une jambe disparaît n'a plus de sens : on supprime aussi l'autre jambe
    conn.execute(
        """DELETE FROM transactions WHERE transfer_group IN (
               SELECT transfer_group FROM transactions
               WHERE account_id = ? AND transfer_group IS NOT NULL)""",
        (account_id,),
    )
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
