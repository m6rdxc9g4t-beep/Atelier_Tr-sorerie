"""Règles de classement : « si le libellé contient X, classer dans Y ».

Première étape du classement en cascade (voir services/classifier.py) : une règle de
l'utilisateur l'emporte toujours sur l'historique, le dictionnaire et l'IA.

Trois façons de reconnaître une opération :
  - contient   : le libellé (sans accents ni ponctuation) contient le motif ;
  - commence   : le libellé commence par le motif ;
  - commercant : le commerçant reconnu (services/merchants.identify) est exactement le motif.
    C'est le type des règles apprises depuis les corrections de l'utilisateur.
"""
from __future__ import annotations

import sqlite3

from .merchants import identify, normalize_text
from .validation import ConflictError, NotFoundError, ValidationError, Validator, update_row

MATCH_TYPES = ("contient", "commence", "commercant")
DIRECTIONS = ("tous", "debit", "credit")
MATCH_LABELS = {"contient": "contient", "commence": "commence par", "commercant": "commerçant ="}
MAX_RULES = 2000

_SELECT = """
    SELECT r.id, r.pattern, r.match_type, r.direction, r.account_id, a.name AS account_name,
           r.category_id, c.name AS category_name, c.color AS category_color, c.kind AS category_kind, r.created_at
    FROM category_rules r
    JOIN categories c ON c.id = r.category_id
    LEFT JOIN accounts a ON a.id = r.account_id
"""


# --------------------------------------------------------------------------- correspondance

class RuleSet:
    """Règles chargées une fois, appliquées à de nombreuses opérations (import, rétroaction)."""

    def __init__(self, conn: sqlite3.Connection):
        rows = [dict(r) for r in conn.execute(_SELECT)]
        # Plus spécifique d'abord : règle propre à un compte, puis commerçant exact, puis motif le plus long
        rows.sort(key=lambda r: (r["account_id"] is None, r["match_type"] != "commercant", -len(r["pattern"]), r["id"]))
        self.rules = rows

    def __bool__(self) -> bool:
        return bool(self.rules)

    def match(self, label: str, amount_cents: int, account_id: int | None = None,
              merchant_key: str | None = None) -> dict | None:
        if not self.rules:
            return None
        text = normalize_text(label)
        key = merchant_key if merchant_key is not None else None
        for rule in self.rules:
            if rule["account_id"] is not None and rule["account_id"] != account_id:
                continue
            if rule["direction"] == "debit" and amount_cents > 0:
                continue
            if rule["direction"] == "credit" and amount_cents < 0:
                continue
            kind, pattern = rule["match_type"], rule["pattern"]
            if kind == "contient" and pattern in text:
                return rule
            if kind == "commence" and text.startswith(pattern):
                return rule
            if kind == "commercant":
                if key is None:
                    key = identify(label, amount_cents)["key"]
                if key == pattern:
                    return rule
        return None


# --------------------------------------------------------------------------- CRUD

def _validate(conn, data: dict | None, partial: bool) -> dict:
    v = Validator(data, partial)
    v.text("pattern", required=True, max_len=120)
    v.choice("match_type", MATCH_TYPES)
    v.choice("direction", DIRECTIONS)
    v.integer_id("account_id")
    v.integer_id("category_id", required=True)
    for field, table, label in (("account_id", "accounts", "Compte"), ("category_id", "categories", "Catégorie")):
        if v.clean.get(field) and not conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (v.clean[field],)  # noqa: S608 (table fixe)
        ).fetchone():
            v.errors[field] = f"{label} introuvable."
    clean = v.result()
    if "pattern" in clean:
        clean["pattern"] = normalize_text(clean["pattern"])
        if len(clean["pattern"]) < 2:
            raise ValidationError("Motif trop court.", {"pattern": "Au moins deux lettres ou chiffres."})
    return clean


def _find_same(conn, pattern: str, match_type: str, direction: str, account_id, exclude_id=None):
    return conn.execute(
        "SELECT id FROM category_rules WHERE pattern = ? AND match_type = ? AND direction = ? "
        "AND account_id IS ? AND id IS NOT ?",
        (pattern, match_type, direction, account_id, exclude_id),
    ).fetchone()


def get_rule(conn: sqlite3.Connection, rule_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE r.id = ?", (rule_id,)).fetchone()  # noqa: S608
    if not row:
        raise NotFoundError("Règle introuvable.")
    return dict(row)


def list_rules(conn: sqlite3.Connection) -> list[dict]:
    """Règles, avec le nombre d'opérations existantes qu'elles reconnaissent."""
    rules = RuleSet(conn)
    counts: dict[int, int] = dict.fromkeys((r["id"] for r in rules.rules), 0)
    if rules:
        for t in conn.execute("SELECT label, amount_cents, account_id FROM transactions WHERE transfer_group IS NULL"):
            hit = rules.match(t["label"], t["amount_cents"], t["account_id"])
            if hit:
                counts[hit["id"]] += 1
    items = [dict(r) for r in conn.execute(f"{_SELECT} ORDER BY c.name, r.pattern")]  # noqa: S608
    for item in items:
        item["matches"] = counts.get(item["id"], 0)
    return items


def create_rule(conn: sqlite3.Connection, data: dict | None, commit: bool = True) -> dict:
    clean = _validate(conn, data, partial=False)
    clean.setdefault("match_type", "contient")
    clean["match_type"] = clean["match_type"] or "contient"
    clean["direction"] = clean.get("direction") or "tous"
    clean.setdefault("account_id", None)
    same = _find_same(conn, clean["pattern"], clean["match_type"], clean["direction"], clean["account_id"])
    if same:
        # Même motif : on met à jour la catégorie plutôt que de créer un doublon
        conn.execute("UPDATE category_rules SET category_id = ? WHERE id = ?", (clean["category_id"], same["id"]))
        if commit:
            conn.commit()
        return get_rule(conn, same["id"])
    if conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] >= MAX_RULES:
        raise ConflictError(f"{MAX_RULES} règles maximum.")
    cur = conn.execute(
        "INSERT INTO category_rules (pattern, match_type, direction, account_id, category_id) VALUES (?, ?, ?, ?, ?)",
        (clean["pattern"], clean["match_type"], clean["direction"], clean["account_id"], clean["category_id"]),
    )
    if commit:
        conn.commit()
    return get_rule(conn, cur.lastrowid)


def update_rule(conn: sqlite3.Connection, rule_id: int, data: dict | None) -> dict:
    current = get_rule(conn, rule_id)
    clean = _validate(conn, data, partial=True)
    merged = {**current, **clean}
    if _find_same(conn, merged["pattern"], merged["match_type"], merged["direction"], merged["account_id"], rule_id):
        raise ConflictError("Une règle identique existe déjà.", {"pattern": "Règle déjà existante."})
    update_row(conn, "category_rules", rule_id, clean)
    conn.commit()
    return get_rule(conn, rule_id)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    get_rule(conn, rule_id)
    conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()


# --------------------------------------------------------------------------- application aux opérations existantes

def apply_rules(conn: sqlite3.Connection, data: dict | None = None) -> dict:
    """Applique les règles aux opérations existantes.

    Par défaut, seules les opérations sans catégorie, ou classées automatiquement (historique,
    dictionnaire, IA), sont modifiées : une catégorie choisie à la main ou par une règle n'est
    jamais écrasée. `rule_id` limite l'application à une seule règle.
    """
    v = Validator(data or {})
    v.integer_id("rule_id")
    rule_id = v.result().get("rule_id")
    rules = RuleSet(conn)
    if rule_id:
        get_rule(conn, rule_id)
    updates = []
    for t in conn.execute(
        """SELECT id, label, amount_cents, account_id, category_id FROM transactions
           WHERE transfer_group IS NULL
             AND (category_id IS NULL OR COALESCE(category_source, '') IN ('historique', 'defaut', 'ia'))"""
    ):
        hit = rules.match(t["label"], t["amount_cents"], t["account_id"])
        if hit and (not rule_id or hit["id"] == rule_id) and hit["category_id"] != t["category_id"]:
            updates.append((hit["category_id"], t["id"]))
    with conn:
        conn.executemany(
            "UPDATE transactions SET category_id = ?, category_source = 'regle', ai_suggested = 0, "
            "updated_at = datetime('now') WHERE id = ?",
            updates,
        )
    return {"updated": len(updates)}


def suggest_for_transaction(conn: sqlite3.Connection, transaction_id: int) -> dict:
    """Règle à proposer quand l'utilisateur corrige la catégorie d'une opération."""
    row = conn.execute("SELECT label, amount_cents FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if not row:
        raise NotFoundError("Transaction introuvable.")
    who = identify(row["label"], row["amount_cents"])
    return {"pattern": who["key"], "match_type": "commercant", "merchant": who["name"]} if who["key"] else {}
