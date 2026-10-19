"""Résumé des finances transmis à l'IA, en texte lisible.

Deux niveaux, selon où part le texte :
  - détaillé (Ollama, local) : comptes nommés, positions, plus grosses opérations du mois ;
  - agrégé (Claude, hors de la machine) : uniquement des montants regroupés par mois, par
    catégorie, par type de compte et par type d'actif. Aucun libellé d'opération, nom de
    compte, établissement, nom de position ou d'objectif.

L'utilisateur peut afficher exactement ce texte depuis la page Assistant IA.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from finance import format_eur, savings_rate

from . import accounts as accounts_service
from . import budgets as budgets_service
from . import dashboard
from . import holdings as holdings_service

MONTHS = dashboard.MONTHS_FR_LONG


def _eur(cents: int) -> str:
    return format_eur(cents).replace(" ", " ")


def _pct(value) -> str:
    return f"{value:g}".replace(".", ",") + " %"


def _de(label: str) -> str:
    """« de octobre » -> « d'octobre »."""
    return ("d'" if label[:1].lower() in "aeiouyhéèê" else "de ") + label


def _month_label(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{MONTHS[m - 1]} {y}"


def build_context(conn: sqlite3.Connection, detailed: bool, today: date | None = None) -> str:
    today = today or date.today()
    lines: list[str] = [f"Date du jour : {today.day} {MONTHS[today.month - 1]} {today.year} (mois en cours partiel)."]
    if detailed:
        lines.append("Niveau de détail : complet (l'IA tourne sur l'ordinateur de l'utilisateur).")
    else:
        lines.append("Niveau de détail : agrégé (aucun libellé d'opération ni nom de compte).")

    # ------------------------------------------------------------------ patrimoine
    accounts = accounts_service.list_accounts(conn)
    total = sum(a["total_value_cents"] for a in accounts)
    invest = sum(a["holdings_value_cents"] for a in accounts)
    lines += ["", "## Patrimoine", f"- Total : {_eur(total)} (dont placements valorisés : {_eur(invest)})"]
    if detailed:
        for a in accounts:
            extra = f", dont positions {_eur(a['holdings_value_cents'])}" if a["holdings_value_cents"] else ""
            lines.append(f"- {a['name']} ({a['type_label']}) : {_eur(a['total_value_cents'])}{extra}")
    else:
        by_type: dict[str, int] = {}
        for a in accounts:
            by_type[a["type_label"]] = by_type.get(a["type_label"], 0) + a["total_value_cents"]
        for label, cents in sorted(by_type.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {label} : {_eur(cents)}")

    # ------------------------------------------------------------------ flux mensuels
    hist = dashboard.history(conn, 6, today)
    lines += ["", "## Revenus et dépenses des 6 derniers mois (hors virements internes et achats de titres)"]
    for m in hist:
        rate = savings_rate(m["income_cents"], m["expense_cents"])
        partial = " (en cours)" if m["partial"] else ""
        lines.append(
            f"- {_month_label(m['month'])}{partial} : revenus {_eur(m['income_cents'])}, "
            f"dépenses {_eur(-m['expense_cents'])}, solde {_eur(m['income_cents'] + m['expense_cents'])}"
            + (f", taux d'épargne {_pct(rate)}" if rate is not None else "")
            + f", patrimoine fin de période {_eur(m['total_cents'])}"
        )

    # ------------------------------------------------------------------ dépenses par catégorie
    current = hist[-1]["month"]
    previous = [m["month"] for m in hist[-4:-1]]
    now = {i["name"]: i["amount_cents"] for i in dashboard.expenses_by_category(conn, current, limit=99)["items"]}
    past: dict[str, int] = {}
    for month in previous:
        for i in dashboard.expenses_by_category(conn, month, limit=99)["items"]:
            past[i["name"]] = past.get(i["name"], 0) + i["amount_cents"]
    lines += ["", f"## Dépenses par catégorie : {_month_label(current)} (en cours) vs moyenne des 3 mois précédents"]
    for name in sorted(set(now) | set(past), key=lambda n: -(now.get(n, 0) or past.get(n, 0) / 3)):
        avg = round(past.get(name, 0) / max(1, len(previous)))
        lines.append(f"- {name} : {_eur(now.get(name, 0))} ce mois-ci (moyenne {_eur(avg)})")

    # ------------------------------------------------------------------ budgets
    b = budgets_service.list_budgets(conn, current)
    if b["items"]:
        lines += ["", f"## Budgets {_de(_month_label(current))}"]
        status = {"ok": "dans le budget", "attention": "plus de 80 % consommés", "depasse": "DÉPASSÉ"}
        for i in b["items"]:
            lines.append(f"- {i['category_name']} : {_eur(i['spent_cents'])} / {_eur(i['amount_limit_cents'])} "
                         f"({status[i['status']]})")

    # ------------------------------------------------------------------ objectifs
    goals = budgets_service.list_goals(conn)
    if goals:
        lines += ["", "## Objectifs d'épargne"]
        for n, g in enumerate(goals, 1):
            name = g["name"] if detailed else f"Objectif {n}"
            deadline = f", échéance {g['deadline']}" if g["deadline"] else ""
            monthly = f", il faut {_eur(g['monthly_needed_cents'])} par mois" if g["monthly_needed_cents"] else ""
            lines.append(f"- {name} : {_eur(g['progress_cents'])} / {_eur(g['target_amount_cents'])} "
                         f"({_pct(g['percent'])}){deadline}{monthly}")

    # ------------------------------------------------------------------ placements
    positions = holdings_service.list_holdings(conn)
    if positions["items"]:
        t = positions["totals"]
        gain = f", plus-value latente {_eur(t['gain_cents'])} ({_pct(t['gain_percent'])})" if t["gain_percent"] is not None else ""
        lines += ["", "## Placements", f"- Valeur {_eur(t['value_cents'])}, investi {_eur(t['cost_cents'])}{gain}"]
        for row in positions["by_type"]:
            share = round(row["value_cents"] / t["value_cents"] * 100) if t["value_cents"] else 0
            lines.append(f"- {row['label']} : {_eur(row['value_cents'])} ({share} %)")
        if detailed:
            lines.append("Positions :")
            for h in positions["items"]:
                pct = f" ({'+' if h['gain_percent'] > 0 else ''}{_pct(h['gain_percent'])})" if h["gain_percent"] is not None else ""
                lines.append(f"  - {h['name']} [{h['asset_label']}] : valeur {_eur(h['value_cents'])}, "
                             f"prix de revient {_eur(h['cost_basis_cents'])}{pct}")

    # ------------------------------------------------------------------ détail local uniquement
    if detailed:
        rows = conn.execute(
            """SELECT t.date, t.label, t.amount_cents, COALESCE(c.name, 'Non catégorisée') AS category
               FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
               WHERE substr(t.date, 1, 7) = ? AND t.amount_cents < 0 AND t.transfer_group IS NULL
                 AND COALESCE(c.kind, '') != 'transfert'
               ORDER BY t.amount_cents LIMIT 12""",
            (current,),
        ).fetchall()
        if rows:
            lines += ["", f"## Plus grosses dépenses {_de(_month_label(current))}"]
            lines += [f"- {r['date']} · {r['label']} · {_eur(-r['amount_cents'])} · {r['category']}" for r in rows]
        uncategorized = conn.execute("SELECT COUNT(*) FROM transactions WHERE category_id IS NULL").fetchone()[0]
        if uncategorized:
            lines.append(f"\n{uncategorized} opération(s) ne sont pas catégorisées.")
    return "\n".join(lines)


SYSTEM_PROMPT = """Tu es l'assistant financier d'Atelier Trésorerie, une application personnelle de gestion de budget.
Tu réponds en français, de façon claire et concise, en t'appuyant uniquement sur les données ci-dessous.

Règles :
- Cite les chiffres utiles (montants en euros, pourcentages) et compare aux mois précédents quand c'est pertinent.
- N'invente jamais de données : si une information manque, dis-le simplement.
- Le mois en cours est incomplet : tiens-en compte avant de conclure à une baisse ou une hausse.
- Pour les placements, présente les options et leurs risques plutôt qu'une recommandation ferme :
  tu n'es pas un conseiller financier agréé.
- Mets en forme avec des listes courtes et du **gras** pour les points clés. Pas de tableau.

Données financières de l'utilisateur :
"""


def system_prompt(conn: sqlite3.Connection, detailed: bool, today: date | None = None) -> str:
    return SYSTEM_PROMPT + build_context(conn, detailed, today)
