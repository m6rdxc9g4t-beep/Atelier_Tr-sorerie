"""Catégories de transactions (dépense, revenu, virement interne)."""
from __future__ import annotations

import sqlite3

from .validation import ConflictError, NotFoundError, Validator, update_row

CATEGORY_KINDS = ("depense", "revenu", "transfert")


def _validate(data: dict | None, partial: bool) -> dict:
    v = Validator(data, partial)
    v.text("name", required=True, max_len=60)
    v.choice("kind", CATEGORY_KINDS, required=True)
    v.color("color")
    v.text("icon", max_len=40)
    return v.result()


def list_categories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT c.id, c.name, c.kind, c.color, c.icon,
                  COUNT(t.id) AS transaction_count
           FROM categories c LEFT JOIN transactions t ON t.category_id = c.id
           GROUP BY c.id
           ORDER BY CASE c.kind WHEN 'revenu' THEN 0 WHEN 'depense' THEN 1 ELSE 2 END, c.name"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_category(conn: sqlite3.Connection, category_id: int) -> dict:
    row = conn.execute(
        "SELECT id, name, kind, color, icon FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("Catégorie introuvable.")
    return dict(row)


def _check_unique(conn, name: str, exclude_id: int | None = None) -> None:
    row = conn.execute(
        "SELECT id FROM categories WHERE lower(name) = lower(?) AND id IS NOT ?", (name, exclude_id)
    ).fetchone()
    if row:
        raise ConflictError("Une catégorie porte déjà ce nom.", {"name": "Nom déjà utilisé."})


def create_category(conn: sqlite3.Connection, data: dict | None) -> dict:
    clean = _validate(data, partial=False)
    _check_unique(conn, clean["name"])
    clean = {k: v for k, v in clean.items() if v is not None}
    cur = conn.execute(
        f"INSERT INTO categories ({', '.join(clean)}) VALUES ({', '.join('?' * len(clean))})",  # noqa: S608
        tuple(clean.values()),
    )
    conn.commit()
    return get_category(conn, cur.lastrowid)


def update_category(conn: sqlite3.Connection, category_id: int, data: dict | None) -> dict:
    get_category(conn, category_id)
    clean = _validate(data, partial=True)
    if "name" in clean:
        _check_unique(conn, clean["name"], category_id)
    update_row(conn, "categories", category_id, clean)
    conn.commit()
    return get_category(conn, category_id)


def delete_category(conn: sqlite3.Connection, category_id: int) -> None:
    """Les transactions concernées deviennent « non catégorisées » ; ses budgets sont supprimés."""
    get_category(conn, category_id)
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
