"""Logique métier financière (indépendante de Flask).

Étape 1 : utilitaires de conversion et de formatage des montants.
Étapes suivantes : KPI du tableau de bord, agrégations mensuelles, suivi des budgets.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

NBSP = " "  # espace fine insécable, séparateur de milliers en français


def to_cents(value) -> int:
    """Convertit une saisie utilisateur ('1 234,56', '-12.5', 42) en centimes entiers."""
    if isinstance(value, int):
        return value * 100
    text = str(value).strip().replace(NBSP, "").replace("\xa0", "").replace(" ", "").replace("€", "")
    if "," in text and "." in text:  # ex : 1.234,56
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Montant invalide : {value!r}") from exc
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(cents: int | None) -> float:
    return round((cents or 0) / 100, 2)


def format_eur(cents: int | None, signed: bool = False) -> str:
    """Format français : 1 234,56 € (avec signe + optionnel pour les entrées)."""
    cents = cents or 0
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", NBSP) + f",{rest:02d}{NBSP}€"


def savings_rate(income_cents: int, expense_cents: int) -> float | None:
    """Taux d'épargne = (revenus - dépenses) / revenus × 100. None si aucun revenu."""
    if income_cents <= 0:
        return None
    return round((income_cents - abs(expense_cents)) / income_cents * 100, 1)
