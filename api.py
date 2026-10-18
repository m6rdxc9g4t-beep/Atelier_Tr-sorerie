"""API REST JSON d'Atelier Trésorerie (préfixe /api).

Les routes restent minces : validation et règles métier vivent dans `services/`.
Toute requête qui modifie des données doit porter l'en-tête `X-Requested-With`
(protection simple contre les requêtes envoyées par un autre site vers localhost).
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import threading

from flask import Blueprint, current_app, jsonify, request

import database
from services import ServiceError, ValidationError
from services import accounts, budgets, categories, dashboard, holdings, importer, trading212, transactions

bp = Blueprint("api", __name__, url_prefix="/api")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@bp.before_request
def _csrf_guard():
    if request.method in MUTATING and not request.headers.get("X-Requested-With"):
        return jsonify(error="En-tête X-Requested-With manquant."), 403
    return None


def _db() -> sqlite3.Connection:
    return database.get_db()


def _json() -> dict | None:
    data = request.get_json(silent=True)
    if request.data and data is None:
        raise ValidationError("Corps JSON invalide.")
    return data


def _flag(name: str) -> bool:
    return request.args.get(name, "").lower() in ("1", "true", "oui", "yes")


@bp.errorhandler(ServiceError)
def _service_error(err: ServiceError):
    return jsonify(err.to_dict()), err.status


@bp.errorhandler(sqlite3.IntegrityError)
def _integrity_error(err):
    current_app.logger.warning("Contrainte SQLite violée : %s", err)
    return jsonify(error="Opération refusée : elle violerait l'intégrité des données."), 409


# --------------------------------------------------------------------------- santé

@bp.get("/health")
def health():
    try:
        db_state = {"ok": True, **database.db_stats(_db()), "schema_version": database.schema_version(_db())}
    except (database.DatabaseError, sqlite3.DatabaseError) as exc:
        db_state = {"ok": False, "error": str(exc)}
    return jsonify(database=db_state, ollama=current_app.extensions["ollama"].status())


@bp.get("/ping")
def ping():
    """Réponse légère : permet au lanceur Mac de savoir si l'application tourne déjà."""
    return jsonify(app="atelier-tresorerie", app_mode=current_app.config["APP_MODE"])


@bp.post("/system/shutdown")
def shutdown():
    """Arrête le serveur (uniquement quand il a été lancé par l'application Mac)."""
    if not current_app.config["APP_MODE"]:
        return jsonify(error="Disponible uniquement depuis l'application Mac."), 404
    # Laisse le temps à la réponse de partir avant d'arrêter le processus
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return jsonify(ok=True)


# --------------------------------------------------------------------------- tableau de bord

@bp.get("/dashboard")
def dashboard_data():
    months = request.args.get("months", default=6, type=int)
    return jsonify(dashboard.dashboard(_db(), months))


# --------------------------------------------------------------------------- comptes

@bp.get("/accounts")
def accounts_list():
    items = accounts.list_accounts(_db(), include_archived=_flag("archived"))
    return jsonify(items=items, total_balance_cents=sum(a["total_value_cents"] for a in items if not a["archived"]))


@bp.post("/accounts")
def accounts_create():
    return jsonify(accounts.create_account(_db(), _json())), 201


@bp.get("/accounts/<int:account_id>")
def accounts_get(account_id):
    return jsonify(accounts.get_account(_db(), account_id))


@bp.patch("/accounts/<int:account_id>")
def accounts_update(account_id):
    return jsonify(accounts.update_account(_db(), account_id, _json()))


@bp.delete("/accounts/<int:account_id>")
def accounts_delete(account_id):
    accounts.delete_account(_db(), account_id, force=_flag("force"))
    return "", 204


# --------------------------------------------------------------------------- catégories

@bp.get("/categories")
def categories_list():
    return jsonify(items=categories.list_categories(_db()))


@bp.post("/categories")
def categories_create():
    return jsonify(categories.create_category(_db(), _json())), 201


@bp.patch("/categories/<int:category_id>")
def categories_update(category_id):
    return jsonify(categories.update_category(_db(), category_id, _json()))


@bp.delete("/categories/<int:category_id>")
def categories_delete(category_id):
    categories.delete_category(_db(), category_id)
    return "", 204


# --------------------------------------------------------------------------- transactions

@bp.get("/transactions")
def transactions_list():
    return jsonify(transactions.list_transactions(_db(), request.args.to_dict()))


@bp.post("/transactions")
def transactions_create():
    return jsonify(transactions.create_transaction(_db(), _json())), 201


@bp.post("/transactions/bulk")
def transactions_bulk():
    return jsonify(transactions.bulk_action(_db(), _json()))


@bp.get("/transactions/<int:transaction_id>")
def transactions_get(transaction_id):
    return jsonify(transactions.get_transaction(_db(), transaction_id))


@bp.patch("/transactions/<int:transaction_id>")
def transactions_update(transaction_id):
    return jsonify(transactions.update_transaction(_db(), transaction_id, _json()))


@bp.delete("/transactions/<int:transaction_id>")
def transactions_delete(transaction_id):
    return jsonify(deleted=transactions.delete_transaction(_db(), transaction_id))


@bp.post("/transfers")
def transfers_create():
    return jsonify(items=transactions.create_transfer(_db(), _json())), 201


# --------------------------------------------------------------------------- budgets

@bp.get("/budgets")
def budgets_list():
    return jsonify(budgets.list_budgets(_db(), request.args.get("month")))


@bp.post("/budgets")
def budgets_upsert():
    return jsonify(budgets.upsert_budget(_db(), _json())), 201


@bp.post("/budgets/copy")
def budgets_copy():
    return jsonify(budgets.copy_budgets(_db(), _json()))


@bp.patch("/budgets/<int:budget_id>")
def budgets_update(budget_id):
    return jsonify(budgets.update_budget(_db(), budget_id, _json()))


@bp.delete("/budgets/<int:budget_id>")
def budgets_delete(budget_id):
    budgets.delete_budget(_db(), budget_id)
    return "", 204


# --------------------------------------------------------------------------- objectifs

@bp.get("/goals")
def goals_list():
    return jsonify(items=budgets.list_goals(_db()))


@bp.post("/goals")
def goals_create():
    return jsonify(budgets.create_goal(_db(), _json())), 201


@bp.patch("/goals/<int:goal_id>")
def goals_update(goal_id):
    return jsonify(budgets.update_goal(_db(), goal_id, _json()))


@bp.delete("/goals/<int:goal_id>")
def goals_delete(goal_id):
    budgets.delete_goal(_db(), goal_id)
    return "", 204


# --------------------------------------------------------------------------- positions (placements)

@bp.get("/holdings")
def holdings_list():
    account_id = request.args.get("account_id", type=int)
    return jsonify(holdings.list_holdings(_db(), account_id, include_closed=_flag("closed")))


@bp.post("/holdings")
def holdings_create():
    return jsonify(holdings.create_holding(_db(), _json())), 201


@bp.post("/holdings/prices")
def holdings_prices():
    return jsonify(holdings.update_prices(_db(), _json()))


@bp.get("/holdings/<int:holding_id>")
def holdings_get(holding_id):
    return jsonify(holdings.get_holding(_db(), holding_id))


@bp.patch("/holdings/<int:holding_id>")
def holdings_update(holding_id):
    return jsonify(holdings.update_holding(_db(), holding_id, _json()))


@bp.delete("/holdings/<int:holding_id>")
def holdings_delete(holding_id):
    holdings.delete_holding(_db(), holding_id)
    return "", 204


# --------------------------------------------------------------------------- import

@bp.post("/import/preview")
def import_preview():
    """multipart/form-data : file, account_id, mapping (JSON optionnel {champ: index de colonne})."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValidationError("Aucun fichier reçu.", {"file": "Choisissez un fichier .csv ou .xlsx."})
    mapping = None
    if request.form.get("mapping"):
        try:
            mapping = json.loads(request.form["mapping"])
        except json.JSONDecodeError as exc:
            raise ValidationError("Correspondance des colonnes illisible.") from exc
    raw = upload.read()
    return jsonify(importer.preview(_db(), upload.filename, raw, request.form.get("account_id"), mapping))


@bp.post("/import/commit")
def import_commit():
    return jsonify(importer.commit(_db(), _json())), 201


@bp.post("/import/trading212")
def import_trading212():
    """multipart/form-data : file, account_id, dry_run (1 = aperçu, 0 = import)."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValidationError("Aucun fichier reçu.", {"file": "Choisissez l'export CSV de Trading 212."})
    raw = upload.read()
    account_id = request.form.get("account_id")
    if request.form.get("dry_run", "1") != "0":
        return jsonify(trading212.preview(_db(), upload.filename, raw, account_id))
    return jsonify(trading212.commit(_db(), upload.filename, raw, account_id)), 201


@bp.errorhandler(413)
def _too_large(_err):
    return jsonify(error="Fichier trop volumineux (10 Mo maximum)."), 413
