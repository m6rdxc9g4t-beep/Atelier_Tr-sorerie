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
    ("Dividendes", "revenu", "#a7f3d0"),
    ("Intérêts", "revenu", "#bae6fd"),
    ("Achat / vente de titres", "transfert", "#ddd6fe"),
]


# Migrations numérotées, appliquées dans l'ordre sur les bases plus anciennes.
# Règle : ne jamais modifier une migration publiée, en ajouter une nouvelle.
MIGRATIONS: dict[int, str] = {
    2: """
        -- Lie les deux jambes d'un virement entre comptes
        ALTER TABLE transactions ADD COLUMN transfer_group TEXT;
        CREATE INDEX IF NOT EXISTS idx_transactions_transfer ON transactions(transfer_group);
    """,
    3: """
        -- Positions détenues dans les comptes d'investissement (titres, crypto, métaux précieux)
        CREATE TABLE holdings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            name             TEXT    NOT NULL,
            asset_type       TEXT    NOT NULL DEFAULT 'action'
                             CHECK (asset_type IN ('action', 'etf', 'fonds', 'obligation', 'crypto', 'metal', 'autre')),
            symbol           TEXT,
            isin             TEXT,
            metal            TEXT CHECK (metal IS NULL OR metal IN ('or', 'argent', 'platine', 'palladium')),
            unit             TEXT    NOT NULL DEFAULT 'titre' CHECK (unit IN ('titre', 'g', 'oz', 'piece')),
            purity           REAL    CHECK (purity IS NULL OR (purity > 0 AND purity <= 1000)),  -- millièmes
            weight_g         REAL    CHECK (weight_g IS NULL OR weight_g > 0),                   -- poids d'une pièce
            quantity         REAL    NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            cost_basis_cents INTEGER NOT NULL DEFAULT 0,  -- prix de revient TOTAL de la quantité détenue
            price_cents      INTEGER,                     -- dernier prix UNITAIRE connu
            price_updated_at TEXT,
            source           TEXT    NOT NULL DEFAULT 'manuel' CHECK (source IN ('manuel', 'trading212', 'demo')),
            notes            TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_holdings_account ON holdings(account_id);

        -- Achats / ventes importés (permettent de recalculer quantité et prix de revient)
        CREATE TABLE trades (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            holding_id     INTEGER NOT NULL REFERENCES holdings(id) ON DELETE CASCADE,
            transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
            date           TEXT    NOT NULL,
            side           TEXT    NOT NULL CHECK (side IN ('achat', 'vente')),
            quantity       REAL    NOT NULL CHECK (quantity > 0),
            amount_cents   INTEGER NOT NULL CHECK (amount_cents >= 0),  -- montant total, frais inclus
            import_hash    TEXT UNIQUE,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_trades_holding ON trades(holding_id, date);

        -- Historique des prix (pour les courbes d'évolution du patrimoine)
        CREATE TABLE holding_prices (
            holding_id  INTEGER NOT NULL REFERENCES holdings(id) ON DELETE CASCADE,
            date        TEXT    NOT NULL,
            price_cents INTEGER NOT NULL,
            PRIMARY KEY (holding_id, date)
        );
    """,
    4: """
        -- Moteur ayant produit chaque message de l'assistant (ollama / claude)
        ALTER TABLE ai_conversations ADD COLUMN provider TEXT;
    """,
}
LATEST_VERSION = max(MIGRATIONS, default=1)


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables (idempotent), applique les migrations et les catégories par défaut."""
    try:
        version = schema_version(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        version = max(version, 1)  # schema.sql = version 1
        for target in sorted(MIGRATIONS):
            if target > version:
                conn.executescript(f"BEGIN;\n{MIGRATIONS[target]}\nPRAGMA user_version = {target};\nCOMMIT;")
                version = target
        conn.execute(f"PRAGMA user_version = {version}")
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
        ("PEA", "investissement", "Courtier", 350_00, "#fcd34d"),
        ("Or physique", "investissement", "Coffre personnel", 0, "#fdba74"),
    ]
    ids = []
    for name, kind, inst, opening, color in accounts:
        cur = conn.execute(
            "INSERT INTO accounts (name, type, institution, opening_balance_cents, color) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, kind, inst, opening, color),
        )
        ids.append(cur.lastrowid)
    courant, livret, pea, gold = ids

    rows: list[tuple] = []

    def add(acc, d, label, cents, category, group=None):
        if d <= today:
            rows.append((acc, cat[category], d.isoformat(), label, cents, "valide", "demo", group))

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
        group = f"demo-{m:%Y-%m}"
        add(courant, m.replace(day=2), "Virement vers Livret A", -200_00, "Virement interne", group)
        add(livret, m.replace(day=2), "Virement depuis compte courant", 200_00, "Virement interne", group)
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

        month_start = (m.replace(day=28) + timedelta(days=4)).replace(day=1)

    conn.executemany(
        "INSERT INTO transactions (account_id, category_id, date, label, amount_cents, status, source, transfer_group) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )

    # Budgets du mois courant et du précédent, et deux objectifs d'épargne
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    limits = {"Courses": 380_00, "Restaurants": 120_00, "Loisirs": 100_00, "Shopping": 120_00, "Abonnements": 30_00}
    conn.executemany(
        "INSERT OR IGNORE INTO budgets (category_id, month, amount_limit_cents) VALUES (?, ?, ?)",
        [(cat[name], m, limit) for name, limit in limits.items() for m in (last_month, this_month)],
    )
    conn.executemany(
        "INSERT INTO goals (name, target_amount_cents, current_amount_cents, deadline, account_id) VALUES (?, ?, ?, ?, ?)",
        [
            ("Fonds d'urgence", 10_000_00, 0, None, livret),
            ("Vacances d'été", 1_500_00, 600_00, f"{today.year + 1}-06-30", None),
        ],
    )
    # Positions : un ETF et une action dans le PEA, des pièces d'or (prix fictifs de démonstration)
    month_ago = (today - timedelta(days=30)).isoformat()
    holdings = [
        # compte, nom, type, symbole, ISIN, métal, unité, pureté, poids, quantité, revient, prix
        (pea, "Amundi MSCI World UCITS ETF", "etf", "CW8", "LU1681043599", None, "titre", None, None, 7, 3_150_00, 512_40),
        (pea, "Air Liquide", "action", "AI", "FR0000120073", None, "titre", None, None, 6, 930_00, 171_80),
        (gold, "Napoléon 20 francs", "metal", None, None, "or", "piece", 900, 6.45, 4, 1_640_00, 545_00),
    ]
    for account, name, kind, symbol, isin, metal, unit, purity, weight, qty, cost, price in holdings:
        hid = conn.execute(
            "INSERT INTO holdings (account_id, name, asset_type, symbol, isin, metal, unit, purity, weight_g, "
            "quantity, cost_basis_cents, price_cents, price_updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo')",
            (account, name, kind, symbol, isin, metal, unit, purity, weight, qty, cost, price, today.isoformat()),
        ).lastrowid
        conn.executemany(
            "INSERT INTO holding_prices (holding_id, date, price_cents) VALUES (?, ?, ?)",
            [(hid, month_ago, int(price * 0.97)), (hid, today.isoformat(), price)],
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
