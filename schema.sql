-- Atelier Trésorerie — schéma SQLite (version 1)
-- Tous les montants sont stockés en CENTIMES (INTEGER) pour éviter les erreurs d'arrondi.
-- Convention de signe : montant > 0 = entrée d'argent, montant < 0 = sortie.
-- Le script est idempotent (IF NOT EXISTS) : il peut être rejoué sans risque.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT    NOT NULL,
    type                  TEXT    NOT NULL DEFAULT 'courant'
                          CHECK (type IN ('courant', 'epargne', 'investissement', 'credit', 'especes')),
    institution           TEXT,
    currency              TEXT    NOT NULL DEFAULT 'EUR',
    opening_balance_cents INTEGER NOT NULL DEFAULT 0,
    color                 TEXT,
    archived              INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL CHECK (kind IN ('depense', 'revenu', 'transfert')),
    color      TEXT NOT NULL DEFAULT '#a5b4fc',
    icon       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    date         TEXT    NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    label        TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'valide'
                 CHECK (status IN ('valide', 'en_attente', 'rapproche')),
    notes        TEXT,
    source       TEXT    NOT NULL DEFAULT 'manuel' CHECK (source IN ('manuel', 'import', 'demo')),
    import_hash  TEXT UNIQUE,          -- évite les doublons lors des imports CSV/Excel
    ai_suggested INTEGER NOT NULL DEFAULT 0 CHECK (ai_suggested IN (0, 1)),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transactions_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_account  ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_id);

-- Budget mensuel par catégorie (month = 'YYYY-MM')
CREATE TABLE IF NOT EXISTS budgets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id        INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    month              TEXT    NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    amount_limit_cents INTEGER NOT NULL CHECK (amount_limit_cents >= 0),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (category_id, month)
);

-- Objectifs d'épargne
CREATE TABLE IF NOT EXISTS goals (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL,
    target_amount_cents  INTEGER NOT NULL CHECK (target_amount_cents > 0),
    current_amount_cents INTEGER NOT NULL DEFAULT 0,
    deadline             TEXT,
    account_id           INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Historique des échanges avec l'IA locale (page /ai-insights)
CREATE TABLE IF NOT EXISTS ai_conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    model      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Paramètres clé/valeur (page /settings)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Solde courant de chaque compte = solde d'ouverture + somme des mouvements
CREATE VIEW IF NOT EXISTS v_account_balances AS
SELECT a.id,
       a.name,
       a.type,
       a.institution,
       a.currency,
       a.color,
       a.archived,
       a.opening_balance_cents + COALESCE(SUM(t.amount_cents), 0) AS balance_cents
FROM accounts a
LEFT JOIN transactions t ON t.account_id = a.id
GROUP BY a.id;

PRAGMA user_version = 1;
