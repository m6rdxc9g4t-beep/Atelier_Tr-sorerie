# CLAUDE.md — Atelier Trésorerie

Contexte lu automatiquement par Claude CLI à chaque session dans ce dépôt.

## Projet
Application Flask locale de gestion financière (comptes, transactions, budgets, objectifs) avec IA
locale Ollama. Confidentialité absolue : aucune donnée financière ne doit quitter la machine.

## Architecture (à respecter)
- `app.py` : création de l'app et routes des **pages** uniquement.
- `api.py` : blueprint `/api`. Routes minces : lire la requête, appeler un service, renvoyer du JSON.
- `services/` : toutes les règles métier et le SQL. Chaque fonction reçoit une connexion SQLite,
  ne dépend pas de Flask, valide ses entrées avec `Validator` et lève `ValidationError` (400),
  `NotFoundError` (404) ou `ConflictError` (409) — `api.py` les convertit en JSON.
- `finance.py` : calculs financiers purs (montants, taux, KPI).
- `database.py` : connexion (`get_db()`), schéma, migrations, CLI. Erreurs fichier/SQLite → `DatabaseError`.
- `ollama_client.py` : seul point de contact avec Ollama ; erreurs → `OllamaError`.
- `schema.sql` = schéma de base (v1), jamais modifié. Toute évolution = nouvelle entrée dans
  `database.MIGRATIONS` (numéro suivant) + test de migration.
- Frontend : `static/js/app.js` expose `window.AT` (api, eur, date, toast, confirm, showErrors...) ;
  un script par page dans `static/js/pages/`. Fenêtres modales = `<dialog>` natif.

## Règles
- Montants **toujours en centimes entiers** (`*_cents`). Positif = entrée, négatif = sortie.
- Requêtes SQL **paramétrées** uniquement (`?`), jamais de f-string avec des données utilisateur.
- Routes API sous `/api/...`, réponses JSON ; erreurs `{"error": "...", "fields": {...}}`.
  Les requêtes qui modifient des données exigent l'en-tête `X-Requested-With` (anti-CSRF).
- Virements : deux opérations liées par `transfer_group`, exclues des revenus et dépenses.
- Placements : valeur d'un compte = liquidités (`balance_cents`) + positions (`services/holdings.VALUE_SQL`).
  Positions issues d'un import : quantité et prix de revient recalculés depuis `trades`, jamais saisis.
  Achats / ventes de titres = catégorie de type `transfert` (ni revenu ni dépense).
- Toute chaîne utilisateur insérée dans du HTML passe par `AT.esc()`.
- UI : Tailwind avec les jetons de `static/css/app.css` (`bg-surface`, `text-ink`, `text-muted`,
  `text-gain`, `text-loss`, `bg-brand`...) — pas de couleurs codées en dur. Chiffres avec la classe `num`.
- Textes de l'interface en français. Formatage monétaire via le filtre Jinja `|eur`.
- Jamais d'appel réseau sortant hors `localhost` pour les données (Ollama : proxys désactivés).
- Ne jamais versionner `data/*.db`, `.env`, ni des relevés CSV/Excel réels.

## Vérifier avant de committer
```bash
pytest
python app.py   # puis ouvrir http://127.0.0.1:5050 (5000 = AirPlay sur macOS)
```

## Git
Une branche par fonctionnalité (`feature/...`), commits au format Conventional Commits en français
(`feat(ui): ...`, `fix(api): ...`, `refactor: ...`).
