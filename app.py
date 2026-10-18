"""Point d'entrée Flask d'Atelier Trésorerie : routes des pages et de l'API.

Lancement :
    python app.py                      (http://127.0.0.1:5050)
    flask --app app run --debug --port 5050
"""
from __future__ import annotations

import os
from datetime import date

from flask import Flask, jsonify, render_template, request

import database
from api import bp as api_bp
from config import Config
from finance import format_eur
from ollama_client import OllamaClient

# Navigation principale (sidebar) — `icon` = tracé SVG 24×24 au trait
NAV_ITEMS = [
    {"endpoint": "dashboard", "label": "Tableau de bord",
     "icon": "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"},
    {"endpoint": "accounts", "label": "Comptes & Soldes",
     "icon": "M3 10l9-6 9 6M5 10v8M10 10v8M14 10v8M19 10v8M3 21h18"},
    {"endpoint": "investments", "label": "Placements",
     "icon": "M3 17l5-5 4 4 8-8M14 8h6v6M3 21h18"},
    {"endpoint": "transactions", "label": "Transactions",
     "icon": "M4 7h14m0 0-4-4m4 4-4 4M20 17H6m0 0 4-4m-4 4 4 4"},
    {"endpoint": "budgets", "label": "Budgets & Objectifs",
     "icon": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01"},
    {"endpoint": "ai_insights", "label": "Assistant IA",
     "icon": "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z"},
    {"endpoint": "settings", "label": "Paramètres",
     "icon": "M4 6h9m4 0h3M15 4v4M4 12h3m4 0h9M9 10v4M4 18h11m4 0h1M17 16v4"},
]

# Pages pas encore construites : description affichée en attendant
UPCOMING = {
    "ai_insights": (4, "Dialogue avec vos finances via l'IA locale Ollama : analyses et conseils personnalisés."),
    "settings": (4, "Modèle Ollama, devise, thème, catégories, export et sauvegarde de la base."),
}

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    database.init_app(app)
    database.ensure_schema(app)

    app.extensions["ollama"] = OllamaClient(
        app.config["OLLAMA_URL"], app.config["OLLAMA_MODEL"], app.config["OLLAMA_TIMEOUT"]
    )

    app.jinja_env.filters["eur"] = format_eur

    @app.context_processor
    def inject_globals():
        today = date.today()
        return {
            "nav_items": NAV_ITEMS,
            "current_month_label": f"{MONTHS_FR[today.month - 1]} {today.year}",
        }

    # ------------------------------------------------------------------ pages

    @app.get("/")
    def dashboard():
        stats = database.db_stats(database.get_db())
        return render_template("index.html", stats=stats)

    @app.get("/accounts")
    def accounts():
        return render_template("accounts.html")

    @app.get("/investments")
    def investments():
        return render_template("investments.html")

    @app.get("/transactions")
    def transactions():
        return render_template("transactions.html")

    @app.get("/budgets")
    def budgets():
        return render_template("budgets.html")

    def _upcoming_page(endpoint: str):
        step, description = UPCOMING[endpoint]
        item = next(i for i in NAV_ITEMS if i["endpoint"] == endpoint)
        return render_template("placeholder.html", item=item, step=step, description=description)

    app.add_url_rule("/ai-insights", "ai_insights", lambda: _upcoming_page("ai_insights"))
    app.add_url_rule("/settings", "settings", lambda: _upcoming_page("settings"))

    app.register_blueprint(api_bp)

    # ------------------------------------------------------------------ erreurs

    def _wants_json() -> bool:
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(_err):
        if _wants_json():
            return jsonify(error="Ressource introuvable"), 404
        return render_template("error.html", code=404, message="Cette page n'existe pas."), 404

    @app.errorhandler(database.DatabaseError)
    def database_error(err):
        app.logger.error("Erreur base de données : %s", err)
        if _wants_json():
            return jsonify(error=str(err)), 500
        return render_template("error.html", code=500, message=str(err)), 500

    return app


if __name__ == "__main__":
    # 127.0.0.1 : l'application n'est accessible que depuis cette machine.
    # Port 5050 par défaut : sur macOS, le port 5000 est pris par le récepteur AirPlay,
    # ce qui donne une page blanche sur http://localhost:5000.
    application = create_app()
    port = application.config["PORT"]
    if not os.environ.get("WERKZEUG_RUN_MAIN"):  # une seule fois, pas à chaque rechargement automatique
        print(f"\n  Atelier Trésorerie → http://127.0.0.1:{port}\n")
    application.run(host="127.0.0.1", port=port, debug=True)
