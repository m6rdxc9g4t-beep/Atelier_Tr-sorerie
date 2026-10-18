# CLAUDE.md — Atelier Trésorerie

Contexte lu automatiquement par Claude CLI à chaque session dans ce dépôt.

## Projet
Application Flask locale de gestion financière (comptes, transactions, budgets, objectifs) avec IA
locale Ollama. Confidentialité absolue : aucune donnée financière ne doit quitter la machine.

## Architecture (à respecter)
- `app.py` : création de l'app, routes pages + API. Pas de logique métier ni de SQL complexe ici.
- `finance.py` : logique métier pure, testable sans Flask.
- `database.py` : connexion (`get_db()`), schéma, CLI. Toute erreur fichier/SQLite → `DatabaseError`.
- `ollama_client.py` : seul point de contact avec Ollama ; erreurs → `OllamaError`.
- `schema.sql` : idempotent (`IF NOT EXISTS`). Toute évolution incrémente `PRAGMA user_version`.

## Règles
- Montants **toujours en centimes entiers** (`*_cents`). Positif = entrée, négatif = sortie.
- Requêtes SQL **paramétrées** uniquement (`?`), jamais de f-string avec des données utilisateur.
- Routes API sous `/api/...`, réponses JSON ; erreurs JSON `{"error": "..."}` avec code HTTP adapté.
- UI : Tailwind avec les jetons de `static/css/app.css` (`bg-surface`, `text-ink`, `text-muted`,
  `text-gain`, `text-loss`, `bg-brand`...) — pas de couleurs codées en dur. Chiffres avec la classe `num`.
- Textes de l'interface en français. Formatage monétaire via le filtre Jinja `|eur`.
- Jamais d'appel réseau sortant hors `localhost` pour les données (Ollama : proxys désactivés).
- Ne jamais versionner `data/*.db`, `.env`, ni des relevés CSV/Excel réels.

## Vérifier avant de committer
```bash
pytest
python app.py   # puis ouvrir http://127.0.0.1:5000
```

## Git
Une branche par fonctionnalité (`feature/...`), commits au format Conventional Commits en français
(`feat(ui): ...`, `fix(api): ...`, `refactor: ...`).
