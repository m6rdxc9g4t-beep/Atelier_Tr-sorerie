"""Transactions : liste filtrée, CRUD, virements entre comptes, actions groupées."""
from __future__ import annotations

import re
import unicodedata
import sqlite3
import uuid
from collections import Counter, defaultdict

from .validation import NotFoundError, ValidationError, Validator, ensure_exists, update_row

STATUSES = ("valide", "en_attente", "rapproche")
SORTS = {"date": "t.date", "amount": "t.amount_cents", "label": "t.label COLLATE NOCASE"}
MAX_PER_PAGE = 200

_SELECT = """
    SELECT t.id, t.account_id, a.name AS account_name, a.color AS account_color,
           t.category_id, c.name AS category_name, c.color AS category_color, c.kind AS category_kind,
           t.date, t.label, t.amount_cents, t.status, t.notes, t.source, t.transfer_group,
           t.created_at, t.updated_at
    FROM transactions t
    JOIN accounts a ON a.id = t.account_id
    LEFT JOIN categories c ON c.id = t.category_id
"""

# Une opération est un « virement interne » si elle est liée à une autre ou classée comme telle
# COALESCE indispensable : sans catégorie, c.kind est NULL et « NOT (... OR NULL) » exclurait la ligne
_IS_TRANSFER = "(t.transfer_group IS NOT NULL OR COALESCE(c.kind, '') = 'transfert')"


# --------------------------------------------------------------------------- lecture

def _filters(args: dict) -> tuple[str, list]:
    clauses, params = [], []
    v = Validator(args, partial=True)
    v.integer_id("account_id")
    v.month("month")
    v.date("start")
    v.date("end")
    v.choice("type", ("income", "expense", "transfer"))
    v.choice("status", STATUSES)
    f = v.clean
    if v.errors:
        raise ValidationError("Filtres invalides.", v.errors)

    if f.get("account_id"):
        clauses.append("t.account_id = ?")
        params.append(f["account_id"])
    category = str(args.get("category_id") or "")
    if category == "none":
        clauses.append("t.category_id IS NULL")
    elif category:
        if not category.isdigit():
            raise ValidationError("Filtres invalides.", {"category_id": "Identifiant invalide."})
        clauses.append("t.category_id = ?")
        params.append(int(category))
    if f.get("month"):
        clauses.append("substr(t.date, 1, 7) = ?")
        params.append(f["month"])
    if f.get("start"):
        clauses.append("t.date >= ?")
        params.append(f["start"])
    if f.get("end"):
        clauses.append("t.date <= ?")
        params.append(f["end"])
    if f.get("status"):
        clauses.append("t.status = ?")
        params.append(f["status"])
    kind = f.get("type")
    if kind == "income":
        clauses.append(f"t.amount_cents > 0 AND NOT {_IS_TRANSFER}")
    elif kind == "expense":
        clauses.append(f"t.amount_cents < 0 AND NOT {_IS_TRANSFER}")
    elif kind == "transfer":
        clauses.append(_IS_TRANSFER)
    q = str(args.get("q") or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(t.label LIKE ? ESCAPE '\\' OR t.notes LIKE ? ESCAPE '\\')")
        params += [like, like]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_transactions(conn: sqlite3.Connection, args: dict | None = None) -> dict:
    args = args or {}
    where, params = _filters(args)
    try:
        page = max(1, int(args.get("page") or 1))
        per_page = min(MAX_PER_PAGE, max(1, int(args.get("per_page") or 50)))
    except ValueError as exc:
        raise ValidationError("Pagination invalide.") from exc
    sort = SORTS.get(str(args.get("sort") or "date"), SORTS["date"])
    order = "ASC" if str(args.get("order") or "").lower() == "asc" else "DESC"

    joins = "FROM transactions t JOIN accounts a ON a.id = t.account_id LEFT JOIN categories c ON c.id = t.category_id"
    totals = conn.execute(
        f"""SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN t.amount_cents > 0 AND NOT {_IS_TRANSFER} THEN t.amount_cents END), 0) AS income_cents,
                   COALESCE(SUM(CASE WHEN t.amount_cents < 0 AND NOT {_IS_TRANSFER} THEN t.amount_cents END), 0) AS expense_cents,
                   COALESCE(SUM(t.amount_cents), 0) AS net_cents
            {joins} {where}""",  # noqa: S608 (clauses construites en interne)
        params,
    ).fetchone()
    rows = conn.execute(
        f"{_SELECT} {where} ORDER BY {sort} {order}, t.id {order} LIMIT ? OFFSET ?",  # noqa: S608
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": totals["total"],
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-totals["total"] // per_page)),
        "income_cents": totals["income_cents"],
        "expense_cents": totals["expense_cents"],
        "net_cents": totals["net_cents"],
    }


def get_transaction(conn: sqlite3.Connection, transaction_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE t.id = ?", (transaction_id,)).fetchone()  # noqa: S608
    if not row:
        raise NotFoundError("Transaction introuvable.")
    return dict(row)


# --------------------------------------------------------------------------- catégorisation par l'historique

_NOISE = re.compile(r"[\d/.,:*#\-'()]+")
# Préfixes ajoutés par les banques, sans valeur pour reconnaître le commerçant
_BANK_WORDS = {
    "cb", "carte", "paiement", "achat", "prlv", "prelevement", "prel", "sepa", "vir", "virement", "inst",
    "recu", "emis", "retrait", "dab", "facture", "fact", "x", "du", "le", "de", "la",
}


def normalize_label(label: str) -> str:
    """'CB CARREFOUR 12/10 4532*' -> 'carrefour' : retire dates, numéros, accents et préfixes bancaires."""
    text = unicodedata.normalize("NFKD", label.lower()).encode("ascii", "ignore").decode()
    words = [w for w in _NOISE.sub(" ", text).split() if w not in _BANK_WORDS]
    return " ".join(words)


class CategoryGuesser:
    """Propose la catégorie la plus souvent utilisée pour des libellés similaires."""

    def __init__(self, conn: sqlite3.Connection, history: int = 5000):
        counts: dict[str, Counter] = defaultdict(Counter)
        for row in conn.execute(
            "SELECT label, category_id FROM transactions WHERE category_id IS NOT NULL "
            "ORDER BY date DESC LIMIT ?",
            (history,),
        ):
            counts[normalize_label(row["label"])][row["category_id"]] += 1
        self._best = {key: c.most_common(1)[0][0] for key, c in counts.items() if key}

    def guess(self, label: str) -> int | None:
        return self._best.get(normalize_label(label))


# --------------------------------------------------------------------------- écriture

def _validate(conn, data: dict | None, partial: bool) -> dict:
    v = Validator(data, partial)
    v.integer_id("account_id", required=True)
    v.date("date", required=True)
    v.text("label", required=True, max_len=200)
    v.money("amount", "amount_cents", required=True, non_zero=True)
    v.integer_id("category_id")
    v.choice("status", STATUSES)
    v.text("notes", max_len=1000)
    # Vérifie les références avant result() pour renvoyer toutes les erreurs en une fois
    for field, table, label in (("account_id", "accounts", "Compte"), ("category_id", "categories", "Catégorie")):
        if v.clean.get(field) and not conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (v.clean[field],)  # noqa: S608 (table fixe)
        ).fetchone():
            v.errors[field] = f"{label} introuvable."
    return v.result()


def create_transaction(conn: sqlite3.Connection, data: dict | None) -> dict:
    clean = _validate(conn, data, partial=False)
    if "category_id" not in clean or clean["category_id"] is None:
        clean["category_id"] = CategoryGuesser(conn).guess(clean["label"])
    clean = {k: v for k, v in clean.items() if v is not None}
    cur = conn.execute(
        f"INSERT INTO transactions ({', '.join(clean)}) VALUES ({', '.join('?' * len(clean))})",  # noqa: S608
        tuple(clean.values()),
    )
    conn.commit()
    return get_transaction(conn, cur.lastrowid)


def update_transaction(conn: sqlite3.Connection, transaction_id: int, data: dict | None) -> dict:
    current = get_transaction(conn, transaction_id)
    clean = _validate(conn, data, partial=True)
    group = current["transfer_group"]
    if group and "account_id" in clean:
        raise ValidationError("Le compte d'un virement ne peut pas être modifié : supprimez-le et recréez-le.")
    update_row(conn, "transactions", transaction_id, clean, touch=True)
    if group:  # garde les deux jambes du virement cohérentes
        mirror = {}
        if "date" in clean:
            mirror["date"] = clean["date"]
        if "amount_cents" in clean:
            mirror["amount_cents"] = -clean["amount_cents"]
        if mirror:
            sets = ", ".join(f"{k} = ?" for k in mirror)
            conn.execute(
                f"UPDATE transactions SET {sets}, updated_at = datetime('now') "  # noqa: S608
                "WHERE transfer_group = ? AND id != ?",
                (*mirror.values(), group, transaction_id),
            )
    conn.commit()
    return get_transaction(conn, transaction_id)


def delete_transaction(conn: sqlite3.Connection, transaction_id: int) -> int:
    """Supprime la transaction (et l'autre jambe s'il s'agit d'un virement). Renvoie le nombre supprimé."""
    current = get_transaction(conn, transaction_id)
    if current["transfer_group"]:
        cur = conn.execute("DELETE FROM transactions WHERE transfer_group = ?", (current["transfer_group"],))
    else:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    conn.commit()
    return cur.rowcount


def create_transfer(conn: sqlite3.Connection, data: dict | None) -> list[dict]:
    v = Validator(data)
    v.integer_id("from_account_id", required=True)
    v.integer_id("to_account_id", required=True)
    v.money("amount", "amount_cents", required=True, positive=True, non_zero=True)
    v.date("date", required=True)
    v.text("label", max_len=200)
    v.text("notes", max_len=1000)
    clean = v.result()
    if clean["from_account_id"] == clean["to_account_id"]:
        raise ValidationError("Choisissez deux comptes différents.", {"to_account_id": "Compte identique."})
    src = conn.execute("SELECT name FROM accounts WHERE id = ?", (clean["from_account_id"],)).fetchone()
    dst = conn.execute("SELECT name FROM accounts WHERE id = ?", (clean["to_account_id"],)).fetchone()
    if not src or not dst:
        raise ValidationError("Compte introuvable.")
    cat = conn.execute("SELECT id FROM categories WHERE kind = 'transfert' ORDER BY id LIMIT 1").fetchone()
    group = uuid.uuid4().hex
    label = clean.get("label")
    ids = []
    for account_id, amount, text in (
        (clean["from_account_id"], -clean["amount_cents"], label or f"Virement vers {dst['name']}"),
        (clean["to_account_id"], clean["amount_cents"], label or f"Virement depuis {src['name']}"),
    ):
        cur = conn.execute(
            "INSERT INTO transactions (account_id, category_id, date, label, amount_cents, notes, transfer_group) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, cat["id"] if cat else None, clean["date"], text, amount, clean.get("notes"), group),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return [get_transaction(conn, i) for i in ids]


def bulk_action(conn: sqlite3.Connection, data: dict | None) -> dict:
    """Actions groupées : {"action": "categorize"|"delete"|"status", "ids": [...], ...}."""
    data = data or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 5000:
        raise ValidationError("Sélectionnez entre 1 et 5000 transactions.", {"ids": "Liste invalide."})
    try:
        ids = sorted({int(i) for i in ids})
    except (TypeError, ValueError) as exc:
        raise ValidationError("Identifiants invalides.", {"ids": "Liste invalide."}) from exc
    marks = ", ".join("?" * len(ids))
    action = data.get("action")

    if action == "categorize":
        category_id = data.get("category_id")
        if category_id not in (None, ""):
            v = Validator({"category_id": category_id})
            v.integer_id("category_id", required=True)
            category_id = v.result()["category_id"]
            ensure_exists(conn, "categories", category_id, "Catégorie")
        else:
            category_id = None
        cur = conn.execute(
            f"UPDATE transactions SET category_id = ?, updated_at = datetime('now') WHERE id IN ({marks})",  # noqa: S608
            (category_id, *ids),
        )
    elif action == "status":
        v = Validator({"status": data.get("status")})
        v.choice("status", STATUSES, required=True)
        cur = conn.execute(
            f"UPDATE transactions SET status = ?, updated_at = datetime('now') WHERE id IN ({marks})",  # noqa: S608
            (v.result()["status"], *ids),
        )
    elif action == "delete":
        cur = conn.execute(
            f"""DELETE FROM transactions WHERE id IN ({marks}) OR transfer_group IN (
                    SELECT transfer_group FROM transactions
                    WHERE id IN ({marks}) AND transfer_group IS NOT NULL)""",  # noqa: S608
            (*ids, *ids),
        )
    else:
        raise ValidationError("Action inconnue (categorize, status ou delete).", {"action": "Invalide."})
    conn.commit()
    return {"action": action, "affected": cur.rowcount}
