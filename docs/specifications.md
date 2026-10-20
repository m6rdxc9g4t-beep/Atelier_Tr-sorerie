# Spécifications Techniques - Atelier_Trésorerie

## 1. Vue d'ensemble du projet
**Atelier_Trésorerie** est une application web locale de gestion financière personnelle et professionnelle. Elle permet de suivre les comptes, d'analyser les flux de trésorerie, de catégoriser les transactions et d'obtenir des conseils budgétaires intelligents grâce à une **IA locale (Ollama)**. Le projet est versionné sur GitHub et structuré pour être piloté et étendu via **Claude CLI**.

---

## 2. Architecture Technique
- **Backend :** Python (Flask / FastAPI)
  - Gestion de la base de données relationnelle (SQLite / `finance.db`).
  - API REST pour les transactions, les comptes, les budgets et les analyses.
  - Intégration Ollama (API locale `http://localhost:11434`) pour l'analyse prédictive et la catégorisation intelligente des dépenses.
- **Frontend :** HTML5, Tailwind CSS, JavaScript moderne (Vanilla JS ou Vue.js/React léger)
  - Graphiques interactifs (Chart.js) pour la visualisation de la trésorerie.
  - Interface utilisateur épurée, responsive et moderne (Mode sombre/clair).
- **Dépôt GitHub :** Versioning complet, gestion des branches par fonctionnalités et automatisation des commits via Claude CLI.

---

## 3. Design UI / UX (Nouvelle Interface Visuelle)
- **Palette de couleurs :** Charte « néon monochrome » de la suite Atelier : toute l'interface est déclinée dans la couleur signature de l'application, le bleu roi #3B5BDB (banque, confiance) — fonds, surfaces, bordures et halos teintés, en clair comme en sombre. Les couleurs qui portent un sens restent distinctes : émeraude pour les gains, corail doux pour les dépenses, couleurs propres à chaque catégorie.
- **Navigation principale (Sidebar) :**
  - Tableau de bord (`/`)
  - Comptes & Soldes (`/accounts`)
  - Transactions (`/transactions`)
  - Budgets & Objectifs (`/budgets`)
  - Assistant IA (Ollama) (`/ai-insights`)
  - Paramètres (`/settings`)
- **Écran du Tableau de bord :**
  - **KPIs en-tête :** Solde total, Revenus du mois, Dépenses du mois, Taux d'épargne (avec formules $ \text{Taux} = \frac{\text{Épargne}}{\text{Revenus}} \times 100 $).
  - **Graphiques principaux :** Évolution de la trésorerie sur 6 mois (courbe) et répartition des dépenses par catégorie (camembert / donut).
  - **Dernières transactions :** Tableau fluide avec badges de catégories et statuts.

---

## 4. Fonctionnalités Clés
1. **Gestion des flux :** Saisie manuelle ou import de fichiers (CSV / Excel).
2. **Analyse par IA Locale (Ollama) :** Recommandations personnalisées pour réduire les postes de dépenses superflues.
3. **Sécurité et Confidentialité :** 100% local, aucune donnée financière ne quitte la machine.
4. **Intégration Claude CLI :** Commandes en langage naturel pour générer de nouveaux graphiques, optimiser les requêtes SQL ou corriger des bugs.
