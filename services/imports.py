"""Lots d'import : historique, rapport détaillé d'un import, annulation.

Chaque validation d'un relevé crée un lot (table import_batches) ; les opérations insérées
portent son identifiant. Le rapport aide à comprendre ce qui vient d'arriver sur le compte :
entrées / sorties, répartition par catégorie, origine des catégories, virements internes,
nouveaux commerçants, montants inhabituels et échéances récurrentes.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

from finance import format_eur

from .classifier import SOURCE_LABELS
from .insights import detect_recurring, unusual
from .merchants import identify
from .validation import NotFoundError

_IS_TRANSFER = "(t.transfer_group IS NOT NULL OR COALESCE(c.kind, '') = 'transfert')"


def list_batches(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        f"""SELECT b.id, b.account_id, a.name AS account_name, a.color AS account_color, b.filename,
                   b.skipped, b.created_at,
                   COUNT(t.id) AS count,
                   MIN(t.date) AS start, MAX(t.date) AS end,
                   COALESCE(SUM(CASE WHEN t.amount_cents > 0 AND NOT {_IS_TRANSFER} THEN t.amount_cents END), 0)
                       AS income_cents,
                   COALESCE(SUM(CASE WHEN t.amount_cents < 0 AND NOT {_IS_TRANSFER} THEN t.amount_cents END), 0)
                       AS expense_cents,
                   SUM(CASE WHEN t.category_id IS NULL THEN 1 ELSE 0 END) AS uncategorized
            FROM import_batches b
            JOIN accounts a ON a.id = b.account_id
            LEFT JOIN transactions t ON t.import_batch_id = b.id
            LEFT JOIN categories c ON c.id = t.category_id
            GROUP BY b.id ORDER BY b.id DESC LIMIT ?""",  # noqa: S608 (constante interne)
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _batch(conn, batch_id: int) -> dict:
    row = conn.execute(
        """SELECT b.id, b.account_id, a.name AS account_name, b.filename, b.inserted, b.skipped, b.created_at
           FROM import_batches b JOIN accounts a ON a.id = b.account_id WHERE b.id = ?""",
        (batch_id,),
    ).fetchone()
    if not row:
        raise NotFoundError("Import introuvable.")
    return dict(row)


def report(conn: sqlite3.Connection, batch_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    batch = _batch(conn, batch_id)
    rows = [dict(r) for r in conn.execute(
        """SELECT t.id, t.date, t.label, t.amount_cents, t.category_id, t.category_source, t.transfer_group,
                  c.name AS category_name, c.color AS category_color, c.kind AS category_kind,
                  (SELECT a2.name FROM transactions t2 JOIN accounts a2 ON a2.id = t2.account_id
                    WHERE t2.transfer_group = t.transfer_group AND t2.id != t.id) AS transfer_account
           FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.import_batch_id = ? ORDER BY t.date, t.id""",
        (batch_id,),
    )]
    for r in rows:
        r["is_transfer"] = bool(r["transfer_group"]) or r["category_kind"] == "transfert"
    flows = [r for r in rows if not r["is_transfer"]]
    income = sum(r["amount_cents"] for r in flows if r["amount_cents"] > 0)
    expense = sum(r["amount_cents"] for r in flows if r["amount_cents"] < 0)

    # Répartition par catégorie (le signe compte : un remboursement réduit la dépense de sa catégorie)
    cats: dict[tuple, dict] = {}
    for r in flows:
        kind = "revenu" if (r["category_kind"] == "revenu" or (r["category_kind"] is None and r["amount_cents"] > 0)) \
            else "depense"
        key = (kind, r["category_id"])
        entry = cats.setdefault(key, {"category_id": r["category_id"], "name": r["category_name"] or "À classer",
                                      "color": r["category_color"], "amount_cents": 0, "count": 0})
        entry["amount_cents"] += r["amount_cents"]
        entry["count"] += 1
    expenses_by_category = sorted((v for (k, _), v in cats.items() if k == "depense" and v["amount_cents"] < 0),
                                  key=lambda v: v["amount_cents"])
    income_by_category = sorted((v for (k, _), v in cats.items() if k == "revenu" and v["amount_cents"] > 0),
                                key=lambda v: -v["amount_cents"])

    sources: dict[str, int] = defaultdict(int)
    for r in rows:
        sources[r["category_source"] if r["category_id"] else "aucune"] += 1

    # Nouveaux commerçants : jamais vus avant cet import, sur aucun compte
    seen = set()
    for old in conn.execute(
        "SELECT label, amount_cents FROM transactions WHERE import_batch_id IS NOT ? ORDER BY date DESC LIMIT 5000",
        (batch_id,),
    ):
        seen.add(identify(old["label"], old["amount_cents"])["key"])
    new: dict[str, dict] = {}
    for r in flows:
        who = identify(r["label"], r["amount_cents"])
        if who["key"] and who["key"] not in seen:
            entry = new.setdefault(who["key"], {"merchant": who["name"], "count": 0, "amount_cents": 0,
                                                "category_name": r["category_name"]})
            entry["count"] += 1
            entry["amount_cents"] += r["amount_cents"]

    # Échéances récurrentes concernées par cet import (calculées sur tout l'historique du compte)
    keys = {identify(r["label"], r["amount_cents"])["key"] for r in flows}
    history = [dict(r) for r in conn.execute(
        """SELECT t.date, t.label, t.amount_cents, c.name AS category_name, c.color AS category_color
           FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.account_id = ? AND t.transfer_group IS NULL AND COALESCE(c.kind, '') != 'transfert'
             AND t.date >= date(?, '-460 days')""",
        (batch["account_id"], today.isoformat()),
    )]
    recurring = [i for i in detect_recurring(history, today) if i["merchant_key"] in keys]

    balance = conn.execute("SELECT balance_cents FROM v_account_balances WHERE id = ?",
                           (batch["account_id"],)).fetchone()
    report_data = {
        "batch": batch,
        "count": len(rows),
        "period": {"start": rows[0]["date"] if rows else None, "end": rows[-1]["date"] if rows else None},
        "income_cents": income,
        "expense_cents": expense,
        "net_cents": income + expense,
        "balance_cents": balance["balance_cents"] if balance else None,
        "expenses_by_category": expenses_by_category,
        "income_by_category": income_by_category,
        "sources": [{"source": k, "label": SOURCE_LABELS.get(k, "À classer"), "count": n}
                    for k, n in sorted(sources.items(), key=lambda kv: -kv[1])],
        "uncategorized": sources.get("aucune", 0),
        "transfers": [{k: r[k] for k in ("id", "date", "label", "amount_cents", "transfer_account")}
                      for r in rows if r["transfer_group"]],
        "new_merchants": sorted(new.values(), key=lambda m: m["amount_cents"])[:10],
        "new_merchants_count": len(new),
        "unusual": unusual(conn, flows, exclude_batch=batch_id, today=today),
        "recurring": recurring,
        "top_expenses": sorted((r for r in flows if r["amount_cents"] < 0), key=lambda r: r["amount_cents"])[:5],
    }
    report_data["highlights"] = _highlights(report_data)
    return report_data


def _eur(cents: int) -> str:
    return format_eur(cents).replace(" ", " ")


def _highlights(r: dict) -> list[str]:
    """Quelques phrases simples qui résument l'import."""
    out = []
    if r["period"]["start"]:
        start, end = (date.fromisoformat(r["period"][k]).strftime("%d/%m/%Y") for k in ("start", "end"))
        out.append(f"{r['count']} opération(s) du {start} au {end} : {_eur(r['income_cents'])} d'entrées "
                   f"et {_eur(-r['expense_cents'])} de sorties (hors virements internes).")
    if r["expenses_by_category"]:
        top = r["expenses_by_category"][0]
        share = round(top["amount_cents"] / r["expense_cents"] * 100) if r["expense_cents"] else 0
        out.append(f"Premier poste de dépense : {top['name']} ({_eur(-top['amount_cents'])}, {share} % des sorties).")
    classified = r["count"] - r["uncategorized"]
    if r["count"]:
        out.append(f"{classified} opération(s) sur {r['count']} classée(s) automatiquement"
                   + (f" ; {r['uncategorized']} reste(nt) à classer." if r["uncategorized"] else "."))
    if r["transfers"]:
        out.append(f"{len(r['transfers'])} virement(s) entre vos comptes reconnu(s) et exclu(s) des dépenses.")
    debits = [i for i in r["recurring"] if i["direction"] == "debit"]
    if debits:
        out.append(f"{len(debits)} prélèvement(s) récurrent(s) dans ce relevé, soit {_eur(-sum(i['monthly_cents'] for i in debits))} "
                   "par mois.")
    if r["unusual"]:
        out.append(f"{len(r['unusual'])} montant(s) inhabituel(s) à vérifier.")
    if r["new_merchants_count"]:
        out.append(f"{r['new_merchants_count']} nouveau(x) commerçant(s) ou émetteur(s).")
    return out


def undo(conn: sqlite3.Connection, batch_id: int) -> dict:
    """Supprime toutes les opérations d'un import. Les virements liés à d'autres comptes sont déliés."""
    _batch(conn, batch_id)
    with conn:
        groups = [r[0] for r in conn.execute(
            "SELECT DISTINCT transfer_group FROM transactions WHERE import_batch_id = ? AND transfer_group IS NOT NULL",
            (batch_id,),
        )]
        for group in groups:
            conn.execute(
                """UPDATE transactions SET transfer_group = NULL,
                          category_id = CASE WHEN category_source = 'virement' THEN NULL ELSE category_id END,
                          category_source = CASE WHEN category_source = 'virement' THEN NULL ELSE category_source END,
                          updated_at = datetime('now')
                   WHERE transfer_group = ? AND COALESCE(import_batch_id, -1) != ?""",
                (group, batch_id),
            )
        deleted = conn.execute("DELETE FROM transactions WHERE import_batch_id = ?", (batch_id,)).rowcount
        conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
    return {"deleted": deleted}


def explain_prompt(r: dict, detailed: bool) -> str:
    """Texte transmis à l'IA pour commenter un import.

    detailed=False (Claude, hors de la machine) : uniquement des montants agrégés par catégorie,
    jamais de libellé, de commerçant ni de nom de compte.
    """
    lines = [
        "Voici le résumé d'un relevé bancaire que l'utilisateur vient d'importer.",
        f"Période : du {r['period']['start']} au {r['period']['end']}, {r['count']} opérations.",
        f"Entrées : {_eur(r['income_cents'])} ; sorties : {_eur(-r['expense_cents'])} (hors virements internes).",
        "", "Sorties par catégorie :",
    ]
    lines += [f"- {c['name']} : {_eur(-c['amount_cents'])} ({c['count']} op.)" for c in r["expenses_by_category"]]
    if r["income_by_category"]:
        lines += ["", "Entrées par catégorie :"]
        lines += [f"- {c['name']} : {_eur(c['amount_cents'])}" for c in r["income_by_category"]]
    debits = [i for i in r["recurring"] if i["direction"] == "debit"]
    if debits:
        total = _eur(-sum(i["monthly_cents"] for i in debits))
        lines += ["", f"Prélèvements récurrents : {len(debits)}, soit {total} par mois."]
        if detailed:
            lines += [f"- {i['merchant']} : {_eur(-i['amount_cents'])} ({i['frequency']})" for i in debits]
    if r["unusual"]:
        lines += ["", f"Montants inhabituels : {len(r['unusual'])}."]
        if detailed:
            lines += [f"- {u['date']} {u['merchant']} {_eur(-u['amount_cents'])} : {u['reason']}" for u in r["unusual"]]
    if detailed and r["top_expenses"]:
        lines += ["", "Plus grosses sorties :"]
        lines += [f"- {t['date']} · {t['label']} · {_eur(-t['amount_cents'])}" for t in r["top_expenses"]]
    lines += ["", "En 5 points maximum, explique simplement ce que montre ce relevé : où part l'argent, ce qui "
                  "est inhabituel ou à surveiller, et une idée concrète d'économie si les chiffres la justifient. "
                  "N'invente aucune donnée."]
    return "\n".join(lines)
