"""Comprendre ses comptes : opérations récurrentes, montants inhabituels, virements internes.

Tout est calculé localement, à partir des opérations déjà enregistrées.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from .merchants import identify, normalize_text
from .validation import Validator

# --------------------------------------------------------------------------- récurrences

# (nom, intervalle typique en jours, intervalle min, intervalle max, occurrences minimales)
FREQUENCIES = (
    ("hebdomadaire", 7, 5, 9, 4),
    ("mensuel", 30.44, 25, 36, 3),
    ("trimestriel", 91.3, 80, 100, 3),
    ("annuel", 365.25, 345, 385, 2),
)
# Écart toléré entre les montants (relatif à la médiane) : une facture d'énergie varie, un abonnement non
MAX_AMOUNT_SPREAD = 0.35
WEEKLY_AMOUNT_SPREAD = 0.15


def _iso(d: date) -> str:
    return d.isoformat()


def detect_recurring(rows: list[dict], today: date) -> list[dict]:
    """Regroupe des opérations par commerçant et sens, et garde celles qui reviennent à intervalle régulier.

    `rows` : dicts avec date (ISO), label, amount_cents, category_name/color (facultatifs).
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    names: dict[tuple, str] = {}
    for r in rows:
        who = identify(r["label"], r["amount_cents"])
        if not who["key"]:
            continue
        # Par compte : un salaire versé sur deux comptes le même jour reste deux échéances distinctes
        key = (who["key"], 1 if r["amount_cents"] > 0 else -1, r.get("account_id"))
        groups[key].append(r)
        names.setdefault(key, who["name"])

    found = []
    for key, items in groups.items():
        # Plusieurs opérations le même jour (ex. deux paiements) comptent pour une échéance
        by_day: dict[str, int] = defaultdict(int)
        for r in items:
            by_day[r["date"]] += r["amount_cents"]
        days = sorted(by_day)
        if len(days) < 2:
            continue
        dates = [date.fromisoformat(d) for d in days]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        typical = median(gaps)
        freq = next((f for f in FREQUENCIES if f[2] <= typical <= f[3] and len(days) >= f[4]), None)
        if not freq:
            continue
        regular = sum(1 for g in gaps if freq[2] <= g <= freq[3]) / len(gaps)
        if regular < 0.7:
            continue
        amounts = [abs(by_day[d]) for d in days]
        mid = median(amounts)
        spread = max(abs(a - mid) for a in amounts[-6:]) / mid if mid else 1
        # Les courses de la semaine reviennent aussi chaque semaine : seul un montant quasi fixe compte
        if spread > (WEEKLY_AMOUNT_SPREAD if freq[0] == "hebdomadaire" else MAX_AMOUNT_SPREAD):
            continue
        last = dates[-1]
        # Toujours actif ? Pas plus d'une fois et demie l'intervalle depuis la dernière échéance
        if (today - last).days > freq[3] * 1.5:
            continue
        sign = key[1]
        recent = sorted(items, key=lambda r: r["date"])[-1]
        found.append({
            "merchant": names[key],
            "merchant_key": key[0],
            "direction": "credit" if sign > 0 else "debit",
            "frequency": freq[0],
            "count": len(days),
            "amount_cents": sign * round(mid),
            "fixed": spread <= 0.05,
            "monthly_cents": sign * round(mid * 30.44 / freq[1]),
            "first_date": days[0],
            "last_date": days[-1],
            "next_date": _iso(last + timedelta(days=round(freq[1]))),
            "category_name": recent.get("category_name"),
            "category_color": recent.get("category_color"),
            "account_name": recent.get("account_name"),
        })
    found.sort(key=lambda r: r["monthly_cents"])  # plus grosses sorties d'abord
    return found


def _transactions_since(conn: sqlite3.Connection, start: str, account_id: int | None = None,
                        exclude_batch: int | None = None) -> list[dict]:
    sql = """SELECT t.id, t.date, t.label, t.amount_cents, t.account_id, a.name AS account_name,
                    t.category_id, c.name AS category_name, c.color AS category_color, t.import_batch_id
             FROM transactions t
             JOIN accounts a ON a.id = t.account_id
             LEFT JOIN categories c ON c.id = t.category_id
             WHERE t.date >= ? AND t.transfer_group IS NULL AND COALESCE(c.kind, '') != 'transfert'"""
    params: list = [start]
    if account_id:
        sql += " AND t.account_id = ?"
        params.append(account_id)
    if exclude_batch:
        sql += " AND t.import_batch_id IS NOT ?"
        params.append(exclude_batch)
    return [dict(r) for r in conn.execute(sql + " ORDER BY t.date", params)]


def recurring(conn: sqlite3.Connection, args: dict | None = None, today: date | None = None) -> dict:
    """Abonnements, factures et revenus réguliers des 15 derniers mois."""
    today = today or date.today()
    v = Validator(dict(args or {}))
    v.integer_id("account_id")
    account_id = v.result().get("account_id")
    rows = _transactions_since(conn, _iso(today - timedelta(days=460)), account_id)
    items = detect_recurring(rows, today)
    debits = [i for i in items if i["direction"] == "debit"]
    credits = [i for i in items if i["direction"] == "credit"]
    return {
        "items": items,
        "monthly_debit_cents": sum(i["monthly_cents"] for i in debits),
        "monthly_credit_cents": sum(i["monthly_cents"] for i in credits),
        "upcoming": sorted((i for i in items if i["next_date"] <= _iso(today + timedelta(days=31))),
                           key=lambda i: i["next_date"]),
    }


# --------------------------------------------------------------------------- montants inhabituels

def unusual(conn: sqlite3.Connection, rows: list[dict], exclude_batch: int | None = None,
            today: date | None = None) -> list[dict]:
    """Sorties d'argent nettement au-dessus de l'habitude, chez ce commerçant ou dans cette catégorie."""
    today = today or date.today()
    history = _transactions_since(conn, _iso(today - timedelta(days=460)), exclude_batch=exclude_batch)
    ids = {r.get("id") for r in rows}
    by_merchant: dict[str, list[int]] = defaultdict(list)
    by_category: dict[int, list[int]] = defaultdict(list)
    for h in history:
        if h["amount_cents"] >= 0 or h["id"] in ids:
            continue
        key = identify(h["label"], h["amount_cents"])["key"]
        if key:
            by_merchant[key].append(-h["amount_cents"])
        if h["category_id"]:
            by_category[h["category_id"]].append(-h["amount_cents"])

    flagged = []
    for r in rows:
        cents = -r["amount_cents"]
        if cents <= 0:
            continue
        who = identify(r["label"], r["amount_cents"])
        reason = None
        past = by_merchant.get(who["key"], [])
        if len(past) >= 3:
            mid = median(past)
            if cents >= 2 * mid and cents - mid >= 20_00:
                reason = f"{cents / mid:.1f}".replace(".", ",") + f" × le montant habituel chez {who['name']}"
        elif r.get("category_id") and len(by_category.get(r["category_id"], [])) >= 6:
            mid = median(by_category[r["category_id"]])
            if cents >= 3 * mid and cents - mid >= 80_00:
                reason = (f"{cents / mid:.1f}".replace(".", ",")
                          + f" × la dépense habituelle en {r.get('category_name') or 'cette catégorie'}")
        elif not past and cents >= 500_00:
            reason = "Montant important chez un nouveau commerçant"
        if reason:
            flagged.append({**{k: r.get(k) for k in ("id", "date", "label", "amount_cents", "category_name")},
                            "merchant": who["name"], "reason": reason})
    flagged.sort(key=lambda f: f["amount_cents"])
    return flagged[:20]


# --------------------------------------------------------------------------- virements internes

TRANSFER_WINDOW_DAYS = 3
_TRANSFER_HINTS = ("vir", "virement", "transfert", "livret", "epargne", "ldd", "ldds", "pel", "cel", "lep")


def _looks_like_transfer(label: str) -> bool:
    words = set(normalize_text(label).split())
    return any(h in words for h in _TRANSFER_HINTS)


class TransferMatcher:
    """Retrouve, dans les AUTRES comptes, l'opération opposée d'un virement (même montant, ±3 jours)."""

    def __init__(self, conn: sqlite3.Connection, account_id: int, start: str, end: str):
        lo = _iso(date.fromisoformat(start) - timedelta(days=TRANSFER_WINDOW_DAYS))
        hi = _iso(date.fromisoformat(end) + timedelta(days=TRANSFER_WINDOW_DAYS))
        self.candidates: dict[int, list[dict]] = defaultdict(list)
        for r in conn.execute(
            """SELECT t.id, t.date, t.label, t.amount_cents, a.name AS account_name
               FROM transactions t JOIN accounts a ON a.id = t.account_id
               WHERE t.account_id != ? AND t.transfer_group IS NULL AND t.date BETWEEN ? AND ?""",
            (account_id, lo, hi),
        ):
            self.candidates[r["amount_cents"]].append(dict(r))
        self.used: set[int] = set()

    def find(self, day: str, amount_cents: int, label: str) -> dict | None:
        d = date.fromisoformat(day)
        best, best_gap = None, None
        for c in self.candidates.get(-amount_cents, []):
            if c["id"] in self.used:
                continue
            gap = abs((date.fromisoformat(c["date"]) - d).days)
            if gap > TRANSFER_WINDOW_DAYS:
                continue
            # Même montant opposé : on exige un indice (libellé de virement) ou le même jour
            if gap and not (_looks_like_transfer(label) or _looks_like_transfer(c["label"])):
                continue
            if best is None or gap < best_gap:
                best, best_gap = c, gap
        if best:
            self.used.add(best["id"])
            return {"transaction_id": best["id"], "date": best["date"], "label": best["label"],
                    "account_name": best["account_name"]}
        return None

