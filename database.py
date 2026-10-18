"""Accès à la base SQLite : connexion par requête, création du schéma, données de démonstration.

Commandes CLI disponibles (via `flask --app app <commande>`) :
    init-db    crée / met à jour le schéma et les catégories par défaut
    seed-demo  insère 6 mois de données fictives (si la base est vide)
    reset-db   supprime puis recrée la base (demande confirmation)
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import click
from flask import Flask, current_app, g

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class DatabaseError(RuntimeError):
    """Erreur lisible côté utilisateur (fichier inaccessible, base corrompue...)."""


# --------------------------------------------------------------------------- connexion

def connect(path: Path) -> sqlite3.Connection:
    """Ouvre une connexion configurée. Lève DatabaseError avec un message clair."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabaseError(
            f"Impossible de créer le dossier de la base « {path.parent} » : {exc.strerror or exc}"
        ) from exc

    try:
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError as exc:
        raise DatabaseError(f"Impossible d'ouvrir la base « {path} » : {exc}") from exc
    return conn


def get_db() -> sqlite3.Connection:
    """Connexion partagée pendant la durée d'une requête Flask."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------- schéma

DEFAULT_CATEGORIES = [
    # (nom, type, couleur pastel)
    ("Salaire", "revenu", "#6ee7b7"),
    ("Revenus annexes", "revenu", "#99f6e4"),
    ("Logement", "depense", "#a5b4fc"),
    ("Courses", "depense", "#fcd34d"),
    ("Transport", "depense", "#7dd3fc"),
    ("Énergie & Internet", "depense", "#c4b5fd"),
    ("Restaurants", "depense", "#fda4af"),
    ("Loisirs", "depense", "#f9a8d4"),
    ("Abonnements", "depense", "#fdba74"),
    ("Santé", "depense", "#86efac"),
    ("Shopping", "depense", "#f0abfc"),
    ("Impôts & Taxes", "depense", "#cbd5e1"),
    ("Divers", "depense", "#d6d3d1"),
    ("Virement interne", "transfert", "#94a3b8"),
]


def init_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables (idempotent) et les catégories par défaut."""
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executemany(
            "INSERT OR IGNORE INTO categories (name, kind, color) VALUES (?, ?, ?)",
            DEFAULT_CATEGORIES,
        )
        conn.commit()
    except OSError as exc:
        raise DatabaseError(f"Fichier de schéma illisible « {SCHEMA_PATH} » : {exc}") from exc
    except sqlite3.DatabaseError as exc:
        conn.rollback()
        raise DatabaseError(f"Échec de l'initialisation du schéma : {exc}") from exc


def ensure_schema(app: Flask) -> None:
    """Appelé au démarrage : garantit que la base existe et est à jour."""
    conn = connect(app.config["DATABASE_PATH"])
    try:
        init_schema(conn)
    finally:
        conn.close()


def db_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT (SELECT COUNT(*) FROM accounts)     AS accounts,
                  (SELECT COUNT(*) FROM transactions) AS transactions,
                  (SELECT COUNT(*) FROM categories)   AS categories,
                  (SELECT COUNT(*) FROM budgets)      AS budgets"""
    ).fetchone()
    return dict(row)


# --------------------------------------------------------------------------- démo

def seed_demo(conn: sqlite3.Connection, months: int = 6, today: date | None = None) -> int:
    """Insère des données fictives réalistes. Ne fait rien si des transactions existent déjà.

    Retourne le nombre de transactions créées.
    """
    if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]:
        return 0

    rng = random.Random(42)  # déterministe : mêmes données à chaque fois
    today = today or date.today()
    cat = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}

    accounts = [
        ("Compte courant", "courant", "Banque Locale", 1_250_00, "#a5b4fc"),
        ("Livret A", "epargne", "Banque Locale", 6_800_00, "#6ee7b7"),
        ("PEA", "investissement", "Courtier", 4_500_00, "#fcd34d"),
    ]
    ids = []
    for name, kind, inst, opening, color in accounts:
        cur = conn.execute(
            "INSERT INTO accounts (name, type, institution, opening_balance_cents, color) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, kind, inst, opening, color),
        )
        ids.append(cur.lastrowid)
    courant, livret, pea = ids

    rows: list[tuple] = []

    def add(acc, d, label, cents, category):
        if d <= today:
            rows.append((acc, cat[category], d.isoformat(), label, cents, "valide", "demo"))

    # Premier jour du mois, `months` mois en arrière (mois courant inclus)
    start = today.replace(day=1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)

    month_start = start
    while month_start <= today:
        m = month_start
        add(courant, m.replace(day=1), "Salaire", 2_850_00, "Salaire")
        add(courant, m.replace(day=3), "Loyer", -950_00, "Logement")
        add(courant, m.replace(day=5), "Électricité & Internet", -rng.randint(85_00, 120_00), "Énergie & Internet")
        add(courant, m.replace(day=6), "Abonnements streaming", -27_98, "Abonnements")
        add(courant, m.replace(day=8), "Pass transport", -86_40, "Transport")
        add(courant, m.replace(day=2), "Virement vers Livret A", -200_00, "Virement interne")
        add(livret, m.replace(day=2), "Virement depuis compte courant", 200_00, "Virement interne")
        for week_day in (4, 11, 18, 25):
            add(courant, m.replace(day=week_day), "Supermarché", -rng.randint(55_00, 115_00), "Courses")
        for _ in range(rng.randint(2, 5)):
            add(courant, m.replace(day=rng.randint(1, 28)), "Restaurant", -rng.randint(18_00, 65_00), "Restaurants")
        for _ in range(rng.randint(1, 3)):
            add(courant, m.replace(day=rng.randint(1, 28)), "Sortie / loisirs", -rng.randint(15_00, 90_00), "Loisirs")
        if rng.random() < 0.6:
            add(courant, m.replace(day=rng.randint(1, 28)), "Achat en ligne", -rng.randint(25_00, 180_00), "Shopping")
        if rng.random() < 0.4:
            add(courant, m.replace(day=rng.randint(1, 28)), "Pharmacie", -rng.randint(8_00, 40_00), "Santé")
        if rng.random() < 0.35:
            add(courant, m.replace(day=rng.randint(10, 28)), "Mission freelance", rng.randint(150_00, 600_00), "Revenus annexes")
        add(pea, m.replace(day=15), "Variation de valorisation", rng.randint(-120_00, 220_00), "Revenus annexes")

        month_start = (m.replace(day=28) + timedelta(days=4)).replace(day=1)

    conn.executemany(
        "INSERT INTO transactions (account_id, category_id, date, label, amount_cents, status, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------- CLI

@click.command("init-db")
def init_db_command():
    """Crée ou met à jour le schéma de la base."""
    conn = connect(current_app.config["DATABASE_PATH"])
    try:
        init_schema(conn)
    finally:
        conn.close()
    click.secho(f"Base prête : {current_app.config['DATABASE_PATH']}", fg="green")


@click.command("seed-demo")
def seed_demo_command():
    """Insère 6 mois de données de démonstration."""
    conn = connect(current_app.config["DATABASE_PATH"])
    try:
        init_schema(conn)
        n = seed_demo(conn)
    finally:
        conn.close()
    if n:
        click.secho(f"{n} transactions de démonstration ajoutées.", fg="green")
    else:
        click.secho("La base contient déjà des transactions : rien n'a été ajouté.", fg="yellow")


@click.command("reset-db")
@click.confirmation_option(prompt="Supprimer définitivement toutes les données ?")
def reset_db_command():
    """Supprime puis recrée la base (irréversible)."""
    path = Path(current_app.config["DATABASE_PATH"])
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        except OSError as exc:
            raise click.ClickException(f"Suppression impossible de {path}{suffix} : {exc}") from exc
    conn = connect(path)
    try:
        init_schema(conn)
    finally:
        conn.close()
    click.secho("Base réinitialisée.", fg="green")


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(reset_db_command)
