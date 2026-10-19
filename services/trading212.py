"""Import de l'historique Trading 212 (export CSV « History » de l'application).

Le format de Trading 212 évolue avec le temps : les colonnes sont donc repérées par leur
nom (Action, Time, ISIN, Ticker, Name, No. of shares, Total, ID...) et non par leur position.
Le signe des montants est déduit du type d'opération, jamais du fichier.

Chaque ligne produit :
  - une opération de trésorerie sur le compte (dépôt, achat, dividende...) ;
  - pour les achats / ventes, un « trade » qui alimente la position correspondante.
Les positions sont ensuite recalculées au coût moyen pondéré.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter

from .holdings import recompute_from_trades
from .importer import _norm, parse_amount, parse_date, read_table
from .validation import ValidationError, Validator

# Type d'opération -> (catégorie, sens du flux de trésorerie)
KINDS = {
    "achat": ("Achat / vente de titres", -1),
    "vente": ("Achat / vente de titres", +1),
    "depot": ("Virement interne", +1),
    "retrait": ("Virement interne", -1),
    "dividende": ("Dividendes", +1),
    "interets": ("Intérêts", +1),
    "carte": (None, -1),             # dépense avec la carte Trading 212 : catégorie à choisir
    "cashback": ("Revenus annexes", +1),
}
KIND_LABELS = {
    "achat": "Achats", "vente": "Ventes", "depot": "Dépôts", "retrait": "Retraits",
    "dividende": "Dividendes", "interets": "Intérêts", "carte": "Paiements carte", "cashback": "Cashback",
}


def classify(action: str) -> str | None:
    a = _norm(action)
    if not a:
        return None
    if "conversion" in a:
        return None  # conversion de devises interne : aucun effet sur la valeur du compte
    if "buy" in a or "achat" in a:
        return "achat"
    if "sell" in a or "vente" in a:
        return "vente"
    if "dividend" in a:
        return "dividende"
    if "interest" in a or "interet" in a:
        return "interets"
    if "deposit" in a or "depot" in a:
        return "depot"
    if "withdraw" in a or "retrait" in a:
        return "retrait"
    if "cashback" in a:
        return "cashback"
    if "card" in a or "carte" in a:
        return "carte"
    return None


def _columns(headers: list[str]) -> dict[str, int | None]:
    names = [_norm(h) for h in headers]

    def find(pred):
        return next((i for i, n in enumerate(names) if pred(n)), None)

    return {
        "action": find(lambda n: n == "action"),
        "time": find(lambda n: n == "time" or n.startswith("time ") or n == "date"),
        "isin": find(lambda n: n == "isin"),
        "ticker": find(lambda n: n == "ticker"),
        "name": find(lambda n: n == "name"),
        "shares": find(lambda n: "no of shares" in n or n == "shares" or n == "quantity"),
        # « Total » ou, dans les anciens exports, « Total (EUR) »
        "total": find(lambda n: n == "total" or (n.startswith("total ") and "currency" not in n)),
        "total_currency": find(lambda n: n == "currency total"),
        "id": find(lambda n: n == "id"),
        "notes": find(lambda n: n == "notes"),
        "merchant": find(lambda n: n == "merchant name"),
    }


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return None
    value = row[idx]
    return value.strip() if isinstance(value, str) else value


def _hash(account_id: int, row_id: str, kind: str, fallback: str) -> str:
    key = f"t212|{account_id}|{row_id}|{kind}" if row_id else f"t212|{account_id}|{fallback}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _guess_asset_type(name: str) -> str:
    n = (name or "").lower()
    return "etf" if any(k in n for k in ("etf", "ucits", "ishares", "vanguard", "amundi", "lyxor", "xtrackers")) else "action"


def parse(conn: sqlite3.Connection, account_id: int, filename: str, raw: bytes) -> dict:
    table = read_table(filename, raw)
    header_pos = next((i for i, (_, cells) in enumerate(table[:10])
                       if any(_norm(c) == "action" for c in cells)), None)
    if header_pos is None:
        raise ValidationError("Ce fichier ne ressemble pas à un export Trading 212 (colonne « Action » absente).")
    headers = [str(h or "").strip() for h in table[header_pos][1]]
    cols = _columns(headers)
    missing = [k for k in ("action", "time", "total") if cols[k] is None]
    if missing:
        raise ValidationError("Colonnes Trading 212 introuvables : " + ", ".join(missing) + ".")
    currency = conn.execute("SELECT currency FROM accounts WHERE id = ?", (account_id,)).fetchone()[0]

    rows, ignored = [], []
    for line, cells in table[header_pos + 1:]:
        action = str(_cell(cells, cols["action"]) or "")
        kind = classify(action)
        if kind is None:
            ignored.append({"line": line, "action": action or "(vide)", "reason": "Opération sans effet ou non reconnue"})
            continue
        try:
            day = parse_date(_cell(cells, cols["time"]))
            total = parse_amount(_cell(cells, cols["total"]))
            if not total:
                raise ValueError("montant total vide")
            cur = str(_cell(cells, cols["total_currency"]) or "").upper()
            if cur and cur != currency:
                raise ValueError(f"montant en {cur}, le compte est en {currency}")
            shares = None
            if kind in ("achat", "vente"):
                shares = float(str(_cell(cells, cols["shares"]) or "").replace(",", "."))
                if shares <= 0:
                    raise ValueError("nombre de titres invalide")
        except (ValueError, TypeError) as exc:
            reason = str(exc)
            ignored.append({"line": line, "action": action, "reason": reason[:1].upper() + reason[1:]})
            continue

        category, sign = KINDS[kind]
        ticker = str(_cell(cells, cols["ticker"]) or "").upper()
        isin = str(_cell(cells, cols["isin"]) or "").upper()
        name = str(_cell(cells, cols["name"]) or "") or ticker or isin
        row_id = str(_cell(cells, cols["id"]) or "")
        time_raw = str(_cell(cells, cols["time"]) or "")
        amount = sign * abs(total)

        if kind in ("achat", "vente"):
            verb = "Achat" if kind == "achat" else "Vente"
            label = f"{verb} {shares:g} × {ticker or name}"
        elif kind == "dividende":
            label = f"Dividende {ticker or name}".strip()
        elif kind == "carte":
            label = str(_cell(cells, cols["merchant"]) or "") or "Paiement carte Trading 212"
        else:
            label = {"depot": "Dépôt Trading 212", "retrait": "Retrait Trading 212",
                     "interets": "Intérêts Trading 212", "cashback": "Cashback Trading 212"}[kind]

        rows.append({
            "line": line, "kind": kind, "date": day, "label": label[:200], "amount_cents": amount,
            "category": category, "ticker": ticker or None, "isin": isin or None, "name": name or None,
            "shares": shares,
            "import_hash": _hash(account_id, row_id, kind, f"{time_raw}|{action}|{isin or ticker}|{shares}|{total}"),
        })

    # Doublons : lignes déjà importées (même empreinte), y compris au sein du fichier
    seen: set[str] = set()
    for r in rows:
        exists = conn.execute("SELECT 1 FROM transactions WHERE import_hash = ?", (r["import_hash"],)).fetchone()
        r["duplicate"] = bool(exists) or r["import_hash"] in seen
        seen.add(r["import_hash"])
    return {"rows": rows, "ignored": ignored, "currency": currency}


def _key(r: dict) -> str:
    return r["isin"] or r["ticker"] or r["name"]


def _positions_preview(conn, account_id: int, rows: list[dict]) -> list[dict]:
    """Positions obtenues après import (historique déjà en base + nouvelles lignes)."""
    trades: dict[str, list] = {}
    names: dict[str, str] = {}
    for h in conn.execute(
        "SELECT h.id, h.name, h.symbol, h.isin, t.date, t.side, t.quantity, t.amount_cents "
        "FROM trades t JOIN holdings h ON h.id = t.holding_id WHERE h.account_id = ?", (account_id,)
    ):
        key = h["isin"] or h["symbol"] or h["name"]
        trades.setdefault(key, []).append((h["date"], 0, "achat" if h["side"] == "achat" else "vente",
                                           h["quantity"], h["amount_cents"]))
        names[key] = h["name"]
    for i, r in enumerate(rows):
        if r["kind"] in ("achat", "vente") and not r["duplicate"]:
            trades.setdefault(_key(r), []).append((r["date"], i + 1, r["kind"], r["shares"], abs(r["amount_cents"])))
            names.setdefault(_key(r), r["name"])
    out = []
    for key, items in trades.items():
        qty, cost = 0.0, 0.0
        for _, _, side, q, amount in sorted(items):
            if side == "achat":
                qty += q
                cost += amount
            elif qty > 0:
                sold = min(q, qty)
                cost -= cost * sold / qty
                qty -= sold
            if qty < 1e-9:
                qty, cost = 0.0, 0.0
        out.append({"key": key, "name": names.get(key) or key, "quantity": round(qty, 8),
                    "cost_basis_cents": int(round(cost)),
                    "average_price_cents": int(round(cost / qty)) if qty else None})
    out.sort(key=lambda p: (-p["cost_basis_cents"], p["name"]))
    return out


def _account(conn, account_id) -> int:
    v = Validator({"account_id": account_id})
    v.integer_id("account_id", required=True)
    account_id = v.result()["account_id"]
    row = conn.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not row:
        raise ValidationError("Compte introuvable.", {"account_id": "Compte introuvable."})
    if row["type"] != "investissement":
        raise ValidationError("Choisissez un compte de type Investissement.", {"account_id": "Type de compte incorrect."})
    return account_id


def preview(conn: sqlite3.Connection, filename: str, raw: bytes, account_id) -> dict:
    account_id = _account(conn, account_id)
    parsed = parse(conn, account_id, filename, raw)
    rows = parsed["rows"]
    fresh = [r for r in rows if not r["duplicate"]]
    by_kind = Counter(r["kind"] for r in fresh)
    amounts = Counter()
    for r in fresh:
        amounts[r["kind"]] += r["amount_cents"]
    return {
        "account_id": account_id,
        "currency": parsed["currency"],
        "summary": {
            "total": len(rows), "new": len(fresh), "duplicates": len(rows) - len(fresh),
            "ignored": len(parsed["ignored"]),
            "cash_change_cents": sum(r["amount_cents"] for r in fresh),
        },
        "by_kind": [{"kind": k, "label": KIND_LABELS[k], "count": by_kind[k], "amount_cents": amounts[k]}
                    for k in KIND_LABELS if by_kind[k]],
        "positions": _positions_preview(conn, account_id, rows),
        "ignored": parsed["ignored"][:200],
        "rows": rows[:300],
    }


def commit(conn: sqlite3.Connection, filename: str, raw: bytes, account_id) -> dict:
    account_id = _account(conn, account_id)
    rows = [r for r in parse(conn, account_id, filename, raw)["rows"] if not r["duplicate"]]
    categories = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    holding_ids: dict[str, int] = {}
    touched: set[int] = set()
    inserted = trades = 0
    try:
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO transactions (account_id, category_id, date, label, amount_cents, source, import_hash) "
                "VALUES (?, ?, ?, ?, ?, 'import', ?)",
                (account_id, categories.get(r["category"]), r["date"], r["label"], r["amount_cents"], r["import_hash"]),
            )
            if not cur.rowcount:
                continue
            inserted += 1
            if r["kind"] not in ("achat", "vente"):
                continue
            key = _key(r)
            if key not in holding_ids:
                found = conn.execute(
                    "SELECT id FROM holdings WHERE account_id = ? AND ((isin IS NOT NULL AND isin = ?) "
                    "OR (symbol IS NOT NULL AND symbol = ?) OR name = ?) ORDER BY isin IS NULL LIMIT 1",
                    (account_id, r["isin"], r["ticker"], r["name"]),
                ).fetchone()
                if found:
                    holding_ids[key] = found["id"]
                else:
                    holding_ids[key] = conn.execute(
                        "INSERT INTO holdings (account_id, name, asset_type, symbol, isin, source) "
                        "VALUES (?, ?, ?, ?, ?, 'trading212')",
                        (account_id, r["name"] or key, _guess_asset_type(r["name"]), r["ticker"], r["isin"]),
                    ).lastrowid
            conn.execute(
                "INSERT INTO trades (holding_id, transaction_id, date, side, quantity, amount_cents, import_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (holding_ids[key], cur.lastrowid, r["date"], r["kind"], r["shares"], abs(r["amount_cents"]),
                 r["import_hash"]),
            )
            trades += 1
            touched.add(holding_ids[key])
        for holding_id in touched:
            recompute_from_trades(conn, holding_id)
        conn.commit()
    except sqlite3.DatabaseError:
        conn.rollback()
        raise
    return {"inserted": inserted, "trades": trades, "positions_updated": len(touched)}
