"""Classement en cascade d'une opération bancaire.

Pour chaque opération, la première source qui répond l'emporte :

  1. regle      : une règle de l'utilisateur (services/rules.py) ;
  2. fichier    : la catégorie fournie par la banque dans le relevé, si elle existe dans l'application ;
  3. historique : la catégorie la plus utilisée pour le même libellé, puis pour le même commerçant ;
  4. defaut     : le dictionnaire des commerçants français courants (services/merchants.py) ;
  5. sinon rien : l'opération reste « à classer » — l'IA peut alors proposer (services/assistant.py).

Chaque résultat indique sa source, pour que l'utilisateur sache d'où vient la catégorie.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from .merchants import identify
from .rules import RuleSet
from .transactions import normalize_label

SOURCES = ("regle", "fichier", "historique", "defaut", "ia", "virement", "manuel")
SOURCE_LABELS = {
    "regle": "Règle", "fichier": "Relevé", "historique": "Historique", "defaut": "Commerçant connu",
    "ia": "IA", "virement": "Virement", "manuel": "Manuel",
}
HISTORY = 5000


class Classifier:
    def __init__(self, conn: sqlite3.Connection):
        self.rules = RuleSet(conn)
        self.categories = {r["id"]: dict(r) for r in conn.execute("SELECT id, name, kind FROM categories")}
        self.by_name = {c["name"].lower(): c for c in self.categories.values()}
        by_label: dict[str, Counter] = defaultdict(Counter)
        by_merchant: dict[str, Counter] = defaultdict(Counter)
        for row in conn.execute(
            "SELECT label, amount_cents, category_id FROM transactions "
            "WHERE category_id IS NOT NULL AND transfer_group IS NULL ORDER BY date DESC LIMIT ?",
            (HISTORY,),
        ):
            key = normalize_label(row["label"])
            if key:
                by_label[key][row["category_id"]] += 1
            merchant = identify(row["label"], row["amount_cents"])["key"]
            if merchant:
                by_merchant[merchant][row["category_id"]] += 1
        self._by_label = {k: c.most_common(1)[0][0] for k, c in by_label.items()}
        self._by_merchant = {k: c.most_common(1)[0][0] for k, c in by_merchant.items()}

    def _coherent(self, category_id: int | None, amount_cents: int) -> bool:
        """Une catégorie de revenu n'est jamais proposée pour une sortie d'argent."""
        cat = self.categories.get(category_id)
        return bool(cat) and not (amount_cents < 0 and cat["kind"] == "revenu")

    def classify(self, label: str, amount_cents: int, account_id: int | None = None,
                 file_category: str | None = None) -> dict:
        who = identify(label, amount_cents)
        result = {"merchant": who["name"], "merchant_key": who["key"],
                  "category_id": None, "category_source": None, "rule_id": None}

        rule = self.rules.match(label, amount_cents, account_id, merchant_key=who["key"])
        if rule:
            return {**result, "category_id": rule["category_id"], "category_source": "regle", "rule_id": rule["id"]}

        if file_category:
            cat = self.by_name.get(file_category.strip().lower())
            if cat:
                return {**result, "category_id": cat["id"], "category_source": "fichier"}

        for guess in (self._by_label.get(normalize_label(label)), self._by_merchant.get(who["key"])):
            if guess and self._coherent(guess, amount_cents):
                return {**result, "category_id": guess, "category_source": "historique"}

        if who["category"]:
            cat = self.by_name.get(who["category"].lower())
            if cat and self._coherent(cat["id"], amount_cents):
                return {**result, "category_id": cat["id"], "category_source": "defaut"}
        return result
