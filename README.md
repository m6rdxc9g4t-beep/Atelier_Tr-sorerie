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

## Application de bureau (macOS)

Comme Atelier Projets, Atelier Trésorerie s'installe comme une vraie application : sa propre fenêtre,
son icône dans le Dock et son menu, sans navigateur (Electron).

```bash
cd ~/atelier_tresorerie          # dossier du projet
bash scripts/macos/install-desktop.sh
```

Prérequis : Python avec les dépendances du projet (installées par le script si besoin) et Node.js
(déjà présent pour Atelier Projets). L'application est créée dans `~/Applications` ; elle apparaît dans
Launchpad et Spotlight, à glisser dans le Dock.

- **Double-clic** : écran de démarrage, vérification de Python, lancement du serveur local, puis l'interface.
  Si l'application tourne déjà dans un terminal (`python app.py`), la fenêtre l'utilise telle quelle.
- **Cmd+Q** (ou fermer la fenêtre) arrête le serveur. **Cmd+,** ouvre les Paramètres, **Cmd+1…6** les pages.
- **Mises à jour** : l'application lit le code du dossier du projet ; un `git pull` suffit. Une nouvelle
  dépendance Python est installée automatiquement au lancement suivant.
- **Journal** : menu Aide → Journal de l'application (`~/Library/Logs/Atelier_Tresorerie/app.log`).
- Relancer le script après un déplacement du dossier, un changement de Python ou de Node.

Variante qui ouvre l'interface dans le navigateur : `bash scripts/macos/install-launcher.sh`.

## Commandes utiles

| Commande | Effet |
|---|---|
| `flask --app app init-db` | Crée / met à jour le schéma |
| `flask --app app seed-demo` | Ajoute des données de démonstration (si la base est vide) |
| `flask --app app reset-db` | Efface toutes les données (confirmation demandée) |
| `pytest` | Lance les tests |
| `npm test --prefix desktop` | Tests de l'application de bureau (Node) |
| `bash scripts/macos/install-desktop.sh` | Crée l'application de bureau macOS |

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
│   ├── holdings.py     #   positions (titres, crypto, or, argent) et valorisation
│   ├── trading212.py   #   import de l'historique CSV Trading 212
│   ├── dashboard.py    #   agrégations du tableau de bord
│   ├── ai_context.py   #   résumé des finances transmis à l'IA (détaillé ou agrégé)
│   ├── assistant.py    #   conversation et catégorisation par l'IA
│   ├── settings.py     #   paramètres (moteur d'IA, clé API)
│   └── importer.py     #   import CSV / Excel (aperçu puis validation, anti-doublons)
├── finance.py          # Calculs financiers purs (montants, taux d'épargne, KPI)
├── database.py         # Connexion SQLite, schéma, migrations, données de démo, commandes CLI
├── ollama_client.py    # Client de l'API locale Ollama
├── claude_client.py    # Client Claude (Claude Code en mode non interactif, ou API) — seul appel sortant
├── ai_providers.py     # Choix du moteur d'IA selon les paramètres
├── config.py           # Configuration lue depuis l'environnement / .env
├── schema.sql          # Schéma de base (version 1) ; évolutions = migrations dans database.py
├── templates/          # Pages Jinja (base, tableau de bord, comptes, transactions, budgets)
├── static/
│   ├── css/app.css     # Jetons de couleur (clair/sombre) et composants
│   └── js/
│       ├── app.js      # Utilitaires partagés (window.AT), thème, menu, état d'Ollama
│       └── pages/      # Un script par page
├── desktop/            # Application de bureau Electron (main.cjs, lib/server.cjs, splash.html, tests)
├── scripts/macos/      # install-desktop.sh (application de bureau), install-launcher.sh (variante navigateur)
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
| Positions | `GET/POST /api/holdings` · `GET/PATCH/DELETE /api/holdings/<id>` · `POST /api/holdings/prices` |
| Trading 212 | `POST /api/import/trading212` (multipart : `file`, `account_id`, `dry_run=1` pour l'aperçu) |
| Import | `POST /api/import/preview` (multipart : `file`, `account_id`, `mapping`) · `POST /api/import/commit` |
| Tableau de bord | `GET /api/dashboard?months=6` (indicateurs, historique, dépenses par catégorie, opérations, budgets) |
| Assistant IA | `GET/DELETE /api/ai/messages` · `POST /api/ai/ask` · `GET /api/ai/context` · `GET /api/ai/status?deep=1` · `POST /api/ai/categorize` · `POST /api/ai/categorize/apply` |
| Paramètres | `GET/PATCH /api/settings` · `GET /api/system/backup` (téléchargement de la base) |
| Santé | `GET /api/health` |

### Import de relevés

Formats acceptés : `.csv` (séparateur et encodage détectés automatiquement) et `.xlsx`.
Les colonnes Date / Libellé / Montant (ou Débit + Crédit) sont reconnues dans les exports des
banques françaises ; sinon on les choisit à la main dans l'aperçu. Chaque ligne reçoit une
empreinte : réimporter un relevé, ou un relevé qui chevauche le précédent, ne crée pas de doublons.
Les catégories sont reprises du fichier ou devinées à partir des opérations déjà catégorisées.

### Placements (actions, ETF, crypto, or, argent)

Les positions sont rattachées à un compte de type **Investissement**. La valeur d'un compte
d'investissement = liquidités (solde des opérations) + positions (quantité × dernier cours).
Les métaux précieux se comptent en grammes, onces troy ou pièces, avec leur pureté : l'application
calcule le poids de métal fin. Les cours se mettent à jour à la main (bouton « Mettre à jour les
cours »), et chaque mise à jour est historisée.

**Trading 212** : exportez l'historique en CSV depuis l'application, puis « Importer Trading 212 ».
Dépôts, achats, ventes, dividendes et intérêts deviennent des opérations du compte ; achats et ventes
alimentent les positions, recalculées au coût moyen pondéré. Les colonnes sont reconnues par leur nom,
car Trading 212 fait évoluer son format ; un export qui chevauche le précédent ne crée pas de doublons.

### Tableau de bord

- **Patrimoine net** : liquidités de tous les comptes + valeur des positions, comparé à la fin du mois précédent.
- **Revenus / dépenses du mois** : classés selon la catégorie (un remboursement dans « Courses » réduit
  les dépenses) ; virements internes et achats de titres exclus. La comparaison se fait « à date » :
  du 1er au même jour du mois précédent.
- **Taux d'épargne** = (revenus − dépenses) ÷ revenus.
- **Historique** : solde des comptes en fin de mois + positions valorisées au dernier cours connu à cette date.
- Les graphiques utilisent Chart.js (chargé depuis jsDelivr) et suivent le thème clair / sombre.

### Assistant IA

Deux moteurs au choix, dans **Paramètres** :

- **Ollama (par défaut)** : l'IA tourne sur le Mac, rien ne sort. Installer [Ollama](https://ollama.com/download)
  puis un modèle (`ollama pull llama3.1`, ou `llama3.2` sur un Mac avec 8 Go de mémoire).
- **Claude** : analyses plus fines, mais les questions et un **résumé agrégé** sont envoyés à Anthropic
  (totaux par mois, catégorie, type de compte et type d'actif ; jamais de libellé, nom de compte,
  de banque, de position ou d'objectif). Deux connexions possibles :
  - *Mon abonnement* : utilise Claude Code déjà connecté sur le Mac (`claude -p`, sans aucun outil,
    lancé dans un dossier vide, sans historique conservé) ;
  - *Clé API* : clé créée dans la Claude Console, facturée à l'usage.

Le bouton « Données transmises » de la page Assistant IA affiche le texte exact envoyé au moteur.
Chaque moteur ne reçoit que ses propres échanges : changer de moteur ne transmet pas l'historique.

La **catégorisation automatique** propose une catégorie pour les opérations qui n'en ont pas ;
rien n'est appliqué sans validation. Avec Claude, les libellés concernés sont envoyés après confirmation.

## Conventions

- **Montants en centimes entiers** (`amount_cents`) : jamais de `float` pour l'argent. `finance.to_cents()`
  convertit les saisies, le filtre Jinja `|eur` les affiche (`1 234,56 €`).
- **Signe** : positif = entrée, négatif = sortie. Les virements entre comptes utilisent la catégorie
  « Virement interne » et sont exclus des revenus/dépenses.
- L'application écoute uniquement sur `127.0.0.1`.

## Feuille de route

1. ✅ Structure, base SQLite, layout et thème
2. ✅ API REST comptes / transactions / budgets / objectifs, pages correspondantes, import CSV / Excel
3. ✅ Placements (actions, ETF, crypto, or, argent) et import Trading 212
4. ✅ Tableau de bord : indicateurs, patrimoine sur 6 / 12 mois, revenus & dépenses, dépenses par catégorie
5. ✅ Application Mac double-cliquable
6. ✅ Assistant IA (Ollama ou Claude), catégorisation automatique, page Paramètres et sauvegarde
7. ✅ Application de bureau Electron (fenêtre native, comme Atelier Projets)

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
