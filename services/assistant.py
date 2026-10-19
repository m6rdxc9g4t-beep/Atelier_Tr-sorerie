"""Assistant IA : conversation sur les finances et catégorisation des opérations.

Le moteur (Ollama ou Claude) est fourni par l'appelant : ce module ne fait aucun appel
réseau lui-même. Les erreurs du moteur remontent telles quelles (OllamaError / ClaudeError).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from .ai_context import system_prompt
from .validation import ValidationError, Validator

HISTORY_TURNS = 8          # nombre d'échanges précédents renvoyés au moteur
MAX_QUESTION = 2000
CATEGORIZE_LIMIT = 40

SUGGESTIONS = [
    "Où est-ce que je dépense trop ce mois-ci ?",
    "Comment évolue mon taux d'épargne depuis 6 mois ?",
    "Quels budgets risquent d'être dépassés d'ici la fin du mois ?",
    "Combien puis-je mettre de côté chaque mois sans me priver ?",
    "Résume la situation de mes placements.",
    "Quelles dépenses pourrais-je réduire facilement ?",
]


def _provider_name(provider) -> str:
    return "ollama" if getattr(provider, "local", False) else "claude"


# --------------------------------------------------------------------------- conversation

def messages(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, role, content, model, provider, created_at FROM ai_conversations ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM ai_conversations")
    conn.commit()
    return cur.rowcount


def ask(conn: sqlite3.Connection, provider, data: dict | None, today: date | None = None) -> dict:
    v = Validator(data)
    v.text("question", required=True, max_len=MAX_QUESTION)
    question = v.result()["question"]

    # Chaque moteur ne reçoit que ses propres échanges : les réponses d'Ollama, construites avec
    # le contexte détaillé, ne doivent jamais partir chez Claude si l'utilisateur change de moteur.
    name = _provider_name(provider)
    rows = conn.execute(
        "SELECT role, content FROM ai_conversations WHERE provider = ? ORDER BY id DESC LIMIT ?",
        (name, HISTORY_TURNS * 2),
    ).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    system = system_prompt(conn, detailed=provider.local, today=today)
    answer = provider.chat([*history, {"role": "user", "content": question}], system=system)

    # Enregistrés seulement si le moteur a répondu : pas de question orpheline en cas d'erreur
    with conn:
        conn.execute("INSERT INTO ai_conversations (role, content, model, provider) VALUES ('user', ?, ?, ?)",
                     (question, provider.model, name))
        cur = conn.execute("INSERT INTO ai_conversations (role, content, model, provider) VALUES ('assistant', ?, ?, ?)",
                           (answer, provider.model, name))
    row = conn.execute("SELECT id, role, content, model, provider, created_at FROM ai_conversations WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
    return {"question": question, "answer": dict(row)}


# --------------------------------------------------------------------------- catégorisation

CATEGORIZE_PROMPT = """Tu classes des opérations bancaires françaises dans des catégories.
Réponds UNIQUEMENT avec un tableau JSON, sans texte autour, de la forme :
[{"id": 12, "categorie": "Courses"}, ...]
Règles :
- "categorie" doit être EXACTEMENT un nom de la liste fournie, ou null si tu n'es pas sûr.
- Un montant négatif est une dépense : choisis une catégorie de type « dépense ».
- Un montant positif est une entrée : choisis une catégorie de type « revenu » (ou « dépense » s'il s'agit d'un remboursement).
"""

KIND_FR = {"depense": "dépense", "revenu": "revenu", "transfert": "virement"}


def uncategorized_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id IS NULL AND transfer_group IS NULL"
    ).fetchone()[0]


def _extract_json_array(text: str):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValidationError("L'IA n'a pas renvoyé de suggestions exploitables. Réessayez.")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValidationError("L'IA n'a pas renvoyé de suggestions exploitables. Réessayez.") from exc


def suggest_categories(conn: sqlite3.Connection, provider, limit: int = CATEGORIZE_LIMIT) -> dict:
    rows = conn.execute(
        """SELECT t.id, t.date, t.label, t.amount_cents, a.name AS account_name
           FROM transactions t JOIN accounts a ON a.id = t.account_id
           WHERE t.category_id IS NULL AND t.transfer_group IS NULL
           ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (max(1, min(int(limit), CATEGORIZE_LIMIT)),),
    ).fetchall()
    if not rows:
        return {"items": [], "remaining": 0, "unmatched": 0}
    categories = conn.execute("SELECT id, name, kind FROM categories WHERE kind != 'transfert' ORDER BY name").fetchall()
    by_name = {c["name"].lower(): c for c in categories}

    listing = "\n".join(f"- {c['name']} (type {KIND_FR[c['kind']]})" for c in categories)
    ops = "\n".join(f"{r['id']} | {r['label']} | {r['amount_cents'] / 100:.2f} €" for r in rows)
    prompt = f"Catégories disponibles :\n{listing}\n\nOpérations (id | libellé | montant) :\n{ops}"
    raw = provider.chat([{"role": "user", "content": prompt}], system=CATEGORIZE_PROMPT, max_tokens=3000)

    proposals = {}
    for item in _extract_json_array(raw):
        if not isinstance(item, dict):
            continue
        try:
            tx_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("categorie") or item.get("category") or "").strip().lower()
        if name in by_name:
            proposals[tx_id] = by_name[name]

    items, unmatched = [], 0
    for r in rows:
        cat = proposals.get(r["id"])
        # Cohérence du sens : une catégorie de revenu pour une dépense est rejetée
        if cat is not None and r["amount_cents"] < 0 and cat["kind"] == "revenu":
            cat = None
        if cat is None:
            unmatched += 1
            continue
        items.append({**dict(r), "category_id": cat["id"], "category_name": cat["name"]})
    return {"items": items, "remaining": uncategorized_count(conn), "unmatched": unmatched}


def apply_categories(conn: sqlite3.Connection, data: dict | None) -> dict:
    items = (data or {}).get("items")
    if not isinstance(items, list) or not items or len(items) > 500:
        raise ValidationError("Aucune suggestion à appliquer.")
    valid = {r[0] for r in conn.execute("SELECT id FROM categories")}
    updates = []
    for item in items:
        v = Validator(item if isinstance(item, dict) else None)
        v.integer_id("id", required=True)
        v.integer_id("category_id", required=True)
        clean = v.result()
        if clean["category_id"] not in valid:
            raise ValidationError("Catégorie introuvable.")
        updates.append((clean["category_id"], clean["id"]))
    with conn:
        before = conn.total_changes
        conn.executemany(
            "UPDATE transactions SET category_id = ?, ai_suggested = 1, updated_at = datetime('now') WHERE id = ?",
            updates,
        )
        applied = conn.total_changes - before
    return {"applied": applied, "remaining": uncategorized_count(conn)}
