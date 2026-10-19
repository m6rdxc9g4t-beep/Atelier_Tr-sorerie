"""Erreurs métier et validation des données entrantes (communes à tous les services)."""
from __future__ import annotations

import re
from datetime import date

from finance import to_cents


class ServiceError(Exception):
    status = 400

    def __init__(self, message: str, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}

    def to_dict(self) -> dict:
        data = {"error": self.message}
        if self.fields:
            data["fields"] = self.fields
        return data


class ValidationError(ServiceError):
    status = 400


class NotFoundError(ServiceError):
    status = 404


class ConflictError(ServiceError):
    status = 409


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Validator:
    """Collecte toutes les erreurs d'un formulaire avant de les renvoyer d'un coup."""

    def __init__(self, data: dict | None, partial: bool = False):
        if data is not None and not isinstance(data, dict):
            raise ValidationError("Le corps de la requête doit être un objet JSON.")
        self.data = data or {}
        self.partial = partial  # PATCH : seuls les champs fournis sont validés
        self.errors: dict[str, str] = {}
        self.clean: dict = {}

    def _present(self, field: str, required: bool, nullable: bool = False) -> bool:
        """True si une valeur exploitable est fournie. Gère « obligatoire » et l'effacement."""
        provided = field in self.data
        if provided and self.data[field] not in (None, ""):
            return True
        if required and (provided or not self.partial):
            self.errors[field] = "Champ obligatoire."
        elif provided and nullable:
            self.clean[field] = None  # valeur vide envoyée : on efface le champ optionnel
        return False

    def text(self, field: str, required: bool = False, max_len: int = 200) -> None:
        if not self._present(field, required, nullable=not required):
            return
        value = str(self.data[field]).strip()
        if not value and required:
            self.errors[field] = "Champ obligatoire."
        elif len(value) > max_len:
            self.errors[field] = f"{max_len} caractères maximum."
        else:
            self.clean[field] = value or None

    def money(self, field: str, out: str, required: bool = False, positive: bool = False,
              non_zero: bool = False) -> None:
        if not self._present(field, required):
            return
        try:
            cents = to_cents(self.data[field])
        except ValueError:
            self.errors[field] = "Montant invalide."
            return
        if abs(cents) >= 10**13:
            self.errors[field] = "Montant trop élevé."
        elif positive and cents < 0:
            self.errors[field] = "Le montant doit être positif."
        elif non_zero and cents == 0:
            self.errors[field] = "Le montant ne peut pas être nul."
        else:
            self.clean[out] = cents

    def decimal(self, field: str, required: bool = False, minimum: float | None = None,
                maximum: float | None = None, nullable: bool = False, exclusive_min: bool = False) -> None:
        """Nombre décimal libre (quantité, pureté...) : accepte « 1 234,5 » ou 1234.5."""
        if not self._present(field, required, nullable=nullable and not required):
            return
        text = str(self.data[field]).strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "")
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            self.errors[field] = "Nombre invalide."
            return
        if value != value or value in (float("inf"), float("-inf")):
            self.errors[field] = "Nombre invalide."
        elif minimum is not None and (value <= minimum if exclusive_min else value < minimum):
            self.errors[field] = f"Doit être {'supérieur' if exclusive_min else 'supérieur ou égal'} à {minimum:g}."
        elif maximum is not None and value > maximum:
            self.errors[field] = f"Doit être inférieur ou égal à {maximum:g}."
        else:
            self.clean[field] = value

    def date(self, field: str, required: bool = False) -> None:
        if not self._present(field, required, nullable=not required):
            return
        try:
            self.clean[field] = date.fromisoformat(str(self.data[field])[:10]).isoformat()
        except ValueError:
            self.errors[field] = "Date invalide (format AAAA-MM-JJ)."

    def month(self, field: str, required: bool = False) -> None:
        if not self._present(field, required):
            return
        value = str(self.data[field])
        if _MONTH_RE.match(value):
            self.clean[field] = value
        else:
            self.errors[field] = "Mois invalide (format AAAA-MM)."

    def choice(self, field: str, choices, required: bool = False) -> None:
        if not self._present(field, required):
            return
        value = str(self.data[field])
        if value in choices:
            self.clean[field] = value
        else:
            self.errors[field] = "Valeur non autorisée : " + ", ".join(choices) + "."

    def integer_id(self, field: str, required: bool = False) -> None:
        if not self._present(field, required, nullable=not required):
            return
        try:
            value = int(self.data[field])
            if value <= 0:
                raise ValueError
            self.clean[field] = value
        except (TypeError, ValueError):
            self.errors[field] = "Identifiant invalide."

    def color(self, field: str) -> None:
        if not self._present(field, False):
            return
        value = str(self.data[field])
        if _COLOR_RE.match(value):
            self.clean[field] = value.lower()
        else:
            self.errors[field] = "Couleur invalide (format #rrggbb)."

    def boolean(self, field: str) -> None:
        if field in self.data:
            self.clean[field] = 1 if self.data[field] in (True, 1, "1", "true", "on") else 0

    def result(self) -> dict:
        if self.errors:
            raise ValidationError("Certains champs sont invalides.", self.errors)
        if self.partial and not self.clean:
            raise ValidationError("Aucun champ à modifier.")
        return self.clean


def ensure_exists(conn, table: str, row_id: int, label: str) -> None:
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone():  # noqa: S608 (table fixe)
        raise ValidationError(f"{label} introuvable.", {f"{table[:-1]}_id": f"{label} introuvable."})


def update_row(conn, table: str, row_id: int, values: dict, touch: bool = False) -> None:
    """UPDATE paramétré. Les noms de colonnes proviennent toujours d'un Validator (liste blanche)."""
    if not values:
        return
    if touch:
        values = {**values, "updated_at": None}
    assignments = ", ".join(
        "updated_at = datetime('now')" if col == "updated_at" else f"{col} = ?" for col in values
    )
    params = [v for col, v in values.items() if col != "updated_at"]
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*params, row_id))  # noqa: S608
