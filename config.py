"""Configuration centralisée d'Atelier Trésorerie.

Toutes les valeurs peuvent être surchargées par des variables d'environnement
(ou un fichier .env à la racine, chargé automatiquement si python-dotenv est installé).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:  # .env optionnel
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-a-changer")

    # Base SQLite locale (créée automatiquement au premier lancement)
    DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data" / "finance.db"))

    # IA locale — aucune donnée ne quitte la machine
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
    OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "90"))

    CURRENCY = os.environ.get("CURRENCY", "EUR")
    PORT = int(os.environ.get("PORT", "5050"))  # 5000 est occupé par AirPlay sur macOS
    # Lancé par l'application Mac (double-clic) : active le bouton « Quitter »
    APP_MODE = os.environ.get("ATELIER_APP_MODE") == "1"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # imports CSV/Excel : 10 Mo max
