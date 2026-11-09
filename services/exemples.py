"""Exemples de la suite (`exemples-suite/`, format `atelier-exemples/1`).

Le dossier est généré par Atelier_Deploy (`exemples/generer.py`) et copié tel quel dans chaque app : une histoire
fictive par fichier `<histoire>.json`. Pour Trésorerie, chaque histoire apporte un compte, ses opérations d'août à
octobre 2026 (les mêmes que les relevés convertis par Convert et rangés dans Tab), leurs catégories et les budgets
d'octobre, dont un est dépassé.

Rien d'existant n'est modifié : une catégorie du même nom est réutilisée, un budget déjà posé sur une catégorie et
un mois est laissé tel quel. Ce qui est créé est noté dans `settings` (clé `exemples_suite`) ; retirer supprime
exactement cela : le compte (et ses opérations), les budgets créés, les catégories créées que plus rien n'utilise.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from finance import to_cents

from . import accounts, budgets, categories
from .validation import NotFoundError

FORMAT = "atelier-exemples/1"
STATE_KEY = "exemples_suite"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
COULEURS = ["#a5b4fc", "#fcd34d", "#7dd3fc", "#c4b5fd", "#fda4af", "#f9a8d4", "#fdba74", "#86efac", "#f0abfc", "#cbd5e1"]


def _json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("format") == FORMAT else None


def _part(directory: Path, histoire: str) -> dict:
    part = _json(directory / f"{histoire}.json") if ID_RE.match(histoire or "") else None
    if part is None or "compte" not in part:
        raise NotFoundError("Exemple introuvable.")
    return part


def _state(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (STATE_KEY,)).fetchone()
    try:
        data = json.loads(row["value"]) if row and row["value"] else {}
    except (TypeError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(conn: sqlite3.Connection, state: dict) -> None:
    if state:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (STATE_KEY, json.dumps(state, ensure_ascii=False)),
        )
    else:
        conn.execute("DELETE FROM settings WHERE key = ?", (STATE_KEY,))
    conn.commit()


def list_histoires(conn: sqlite3.Connection, directory: Path) -> list[dict]:
    """Histoires livrées avec l'app, avec ce que chacune crée ici et si elle est chargée."""
    index = _json(directory / "index.json")
    if index is None:
        return []
    state = _state(conn)
    out = []
    for h in index.get("histoires", []):
        try:
            part = _part(directory, str(h.get("id", "")))
        except NotFoundError:
            continue
        b = part["budgets"]
        loaded = state.get(h["id"])
        out.append({
            **{k: h.get(k, "") for k in ("id", "titre", "sous_titre", "secteur", "resume")},
            "parcours": h.get("parcours", []),
            "compte": part["compte"]["nom"],
            "operations": len(part["operations"]),
            "budgets_mois": b["mois"],
            "budgets": len(b["montants"]),
            "charge": bool(loaded),
            "account_id": loaded.get("account_id") if loaded else None,
        })
    return out


def load(conn: sqlite3.Connection, directory: Path, histoire: str) -> dict:
    """Charge l'histoire (une seule fois : un second appel renvoie l'état déjà chargé)."""
    part = _part(directory, histoire)
    state = _state(conn)
    if histoire in state:
        return {"histoire": histoire, **state[histoire], "deja_charge": True}

    try:
        return _load(conn, part, state, histoire)
    except Exception:
        # Chargement interrompu : on retire ce qui a déjà été créé, rien ne reste à moitié.
        if histoire in _state(conn):
            remove(conn, directory, histoire)
        raise


def _load(conn: sqlite3.Connection, part: dict, state: dict, histoire: str) -> dict:
    c = part["compte"]
    account = accounts.create_account(conn, {
        "name": c["nom"], "type": c.get("type", "courant"), "institution": c.get("institution", ""),
        "opening_balance": f"{c['solde_initial']:.2f}",
    })
    rec: dict = {"account_id": account["id"], "categories_creees": [], "budgets_crees": [], "budgets_gardes": []}
    state[histoire] = rec
    _save_state(conn, state)

    by_name = {row["name"].casefold(): row["id"] for row in conn.execute("SELECT id, name FROM categories")}
    for i, cat in enumerate(part["categories"]):
        if cat["nom"].casefold() in by_name:
            continue
        created = categories.create_category(conn, {
            "name": cat["nom"], "kind": cat["type"], "color": COULEURS[i % len(COULEURS)],
        })
        by_name[cat["nom"].casefold()] = created["id"]
        rec["categories_creees"].append(created["id"])

    conn.executemany(
        "INSERT INTO transactions (account_id, category_id, date, label, amount_cents, source) "
        "VALUES (?, ?, ?, ?, ?, 'demo')",
        [(account["id"], by_name.get(o["categorie"].casefold()), o["date"], o["libelle"], to_cents(o["montant"]))
         for o in part["operations"]],
    )
    conn.commit()

    month = part["budgets"]["mois"]
    existing = {row["category_id"] for row in conn.execute("SELECT category_id FROM budgets WHERE month = ?", (month,))}
    for name, amount in part["budgets"]["montants"].items():
        cid = by_name.get(name.casefold())
        if cid is None:
            continue
        if cid in existing:
            rec["budgets_gardes"].append(name)
            continue
        b = budgets.upsert_budget(conn, {"category_id": cid, "month": month, "amount_limit": f"{amount:.2f}"})
        rec["budgets_crees"].append(b["id"])
    _save_state(conn, state)
    return {"histoire": histoire, **rec, "deja_charge": False}


def remove(conn: sqlite3.Connection, directory: Path, histoire: str) -> dict:
    """Retire ce que l'histoire a créé ; garde une catégorie créée si d'autres opérations l'utilisent."""
    _part(directory, histoire)  # histoire connue
    state = _state(conn)
    rec = state.get(histoire)
    if not rec:
        raise NotFoundError("Cet exemple n'est pas chargé.")
    for bid in rec.get("budgets_crees", []):
        conn.execute("DELETE FROM budgets WHERE id = ?", (bid,))
    conn.commit()
    if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (rec["account_id"],)).fetchone():
        accounts.delete_account(conn, rec["account_id"], force=True)
    kept = []
    for cid in rec.get("categories_creees", []):
        row = conn.execute(
            "SELECT c.name, (SELECT COUNT(*) FROM transactions t WHERE t.category_id = c.id) AS n "
            "FROM categories c WHERE c.id = ?", (cid,)
        ).fetchone()
        if row is None:
            continue
        if row["n"]:
            kept.append(row["name"])
        else:
            categories.delete_category(conn, cid)
    del state[histoire]
    _save_state(conn, state)
    return {"histoire": histoire, "categories_gardees": kept}
