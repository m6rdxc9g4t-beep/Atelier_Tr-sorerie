# Atelier Trésorerie

Application web **locale** de gestion financière : comptes, transactions, budgets, tableaux de bord
et conseils d'une IA qui tourne sur votre machine (Ollama). Aucune donnée financière ne quitte l'ordinateur.

## Démarrage rapide

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # puis adaptez SECRET_KEY et OLLAMA_MODEL

flask --app app seed-demo            # optionnel : 6 mois de données fictives
python app.py                        # → http://127.0.0.1:5050
```

La base `data/finance.db` est créée automatiquement au premier lancement.

> **macOS** : utilisez bien l'adresse `http://127.0.0.1:5050`. Le port 5000 est réservé par le
> récepteur AirPlay, qui renvoie une page blanche. Le port se change avec `PORT=...` dans `.env`.

### IA locale (Ollama)

```bash
ollama serve
ollama pull llama3.1                 # ou le modèle indiqué dans OLLAMA_MODEL
```

La pastille « IA locale » de la barre latérale indique l'état en direct (vert : prêt, jaune : modèle
manquant, corail : Ollama arrêté).

## Commandes utiles

| Commande | Effet |
|---|---|
| `flask --app app init-db` | Crée / met à jour le schéma |
| `flask --app app seed-demo` | Ajoute des données de démonstration (si la base est vide) |
| `flask --app app reset-db` | Efface toutes les données (confirmation demandée) |
| `pytest` | Lance les tests |

## Arborescence

```
atelier_tresorerie/
├── app.py              # Création de l'app Flask et routes des pages
├── api.py              # API REST JSON (/api/...) : routes minces, appelle services/
├── services/           # Règles métier, sans Flask (testables seules)
│   ├── validation.py   #   erreurs métier + validation des données entrantes
│   ├── accounts.py     #   comptes et soldes
│   ├── categories.py   #   catégories
│   ├── transactions.py #   opérations, virements, actions groupées, catégorisation par l'historique
│   ├── budgets.py      #   budgets mensuels et objectifs d'épargne
│   └── importer.py     #   import CSV / Excel (aperçu puis validation, anti-doublons)
├── finance.py          # Calculs financiers purs (montants, taux d'épargne, KPI)
├── database.py         # Connexion SQLite, schéma, migrations, données de démo, commandes CLI
├── ollama_client.py    # Client de l'API locale Ollama
├── config.py           # Configuration lue depuis l'environnement / .env
├── schema.sql          # Schéma de base (version 1) ; évolutions = migrations dans database.py
├── templates/          # Pages Jinja (base, tableau de bord, comptes, transactions, budgets)
├── static/
│   ├── css/app.css     # Jetons de couleur (clair/sombre) et composants
│   └── js/
│       ├── app.js      # Utilitaires partagés (window.AT), thème, menu, état d'Ollama
│       └── pages/      # Un script par page
├── data/               # finance.db (ignoré par git)
├── docs/specifications.md
└── tests/
```

## API REST

Toutes les réponses sont en JSON. Les montants sont envoyés en euros (`"12,50"`, `-12.5`) et
renvoyés en centimes (`amount_cents`). Les requêtes qui modifient des données doivent porter
l'en-tête `X-Requested-With`. Erreurs : `{"error": "...", "fields": {"champ": "message"}}`.

| Ressource | Routes |
|---|---|
| Comptes | `GET/POST /api/accounts` · `GET/PATCH/DELETE /api/accounts/<id>` (`?force=1` si opérations) |
| Catégories | `GET/POST /api/categories` · `PATCH/DELETE /api/categories/<id>` |
| Transactions | `GET /api/transactions?q=&account_id=&category_id=&month=&type=&page=&sort=` · `POST` · `GET/PATCH/DELETE /api/transactions/<id>` · `POST /api/transactions/bulk` |
| Virements | `POST /api/transfers` (crée deux opérations liées) |
| Budgets | `GET /api/budgets?month=AAAA-MM` · `POST` (crée ou met à jour) · `PATCH/DELETE /api/budgets/<id>` · `POST /api/budgets/copy` |
| Objectifs | `GET/POST /api/goals` · `PATCH/DELETE /api/goals/<id>` |
| Import | `POST /api/import/preview` (multipart : `file`, `account_id`, `mapping`) · `POST /api/import/commit` |
| Santé | `GET /api/health` |

### Import de relevés

Formats acceptés : `.csv` (séparateur et encodage détectés automatiquement) et `.xlsx`.
Les colonnes Date / Libellé / Montant (ou Débit + Crédit) sont reconnues dans les exports des
banques françaises ; sinon on les choisit à la main dans l'aperçu. Chaque ligne reçoit une
empreinte : réimporter un relevé, ou un relevé qui chevauche le précédent, ne crée pas de doublons.
Les catégories sont reprises du fichier ou devinées à partir des opérations déjà catégorisées.

## Conventions

- **Montants en centimes entiers** (`amount_cents`) : jamais de `float` pour l'argent. `finance.to_cents()`
  convertit les saisies, le filtre Jinja `|eur` les affiche (`1 234,56 €`).
- **Signe** : positif = entrée, négatif = sortie. Les virements entre comptes utilisent la catégorie
  « Virement interne » et sont exclus des revenus/dépenses.
- L'application écoute uniquement sur `127.0.0.1`.

## Feuille de route

1. ✅ Structure, base SQLite, layout et thème
2. ✅ API REST comptes / transactions / budgets / objectifs, pages correspondantes, import CSV / Excel
3. Tableau de bord dynamique : KPI, courbe 6 mois, donut par catégorie, dernières transactions
4. Assistant IA (Ollama) : chat sur les finances, catégorisation automatique ; page Paramètres

## Workflow Git

Une branche par fonctionnalité, fusionnée dans `main` via une pull request :

```bash
git checkout main && git pull
git checkout -b feature/nom-de-la-tache
# ... développement + pytest ...
git add .
git commit -m "feat(api): routes CRUD des transactions"
git push -u origin feature/nom-de-la-tache
```
