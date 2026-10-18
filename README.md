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
python app.py                        # → http://127.0.0.1:5000
```

La base `data/finance.db` est créée automatiquement au premier lancement.

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
├── app.py              # Création de l'app Flask, routes des pages et de l'API
├── finance.py          # Logique métier pure (montants, KPI, budgets) — sans Flask
├── database.py         # Connexion SQLite, schéma, données de démo, commandes CLI
├── ollama_client.py    # Client de l'API locale Ollama (bibliothèque standard uniquement)
├── config.py           # Configuration lue depuis l'environnement / .env
├── schema.sql          # Schéma de la base (montants en centimes)
├── templates/
│   ├── base.html       # Layout : sidebar, en-tête, thème clair/sombre
│   ├── _macros.html    # Composants Jinja (icônes, cartes KPI)
│   ├── index.html      # Tableau de bord
│   ├── placeholder.html# Pages à venir
│   └── error.html
├── static/
│   ├── css/app.css     # Jetons de couleur (clair/sombre) et composants
│   └── js/app.js       # Thème, menu mobile, état d'Ollama
├── data/               # finance.db (ignoré par git)
├── docs/specifications.md
└── tests/test_app.py
```

## Conventions

- **Montants en centimes entiers** (`amount_cents`) : jamais de `float` pour l'argent. `finance.to_cents()`
  convertit les saisies, le filtre Jinja `|eur` les affiche (`1 234,56 €`).
- **Signe** : positif = entrée, négatif = sortie. Les virements entre comptes utilisent la catégorie
  « Virement interne » et sont exclus des revenus/dépenses.
- L'application écoute uniquement sur `127.0.0.1`.

## Feuille de route

1. ✅ Structure, base SQLite, layout et thème
2. API REST transactions / comptes / budgets + pages correspondantes, import CSV / Excel
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
