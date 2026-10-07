# Bi-flow: Generalized Multi-Agent Business Intelligence System

Système multi-agents de Business Intelligence de qualité industrielle, conçu pour automatiser l'analyse de données d'entreprise depuis des tables brutes jusqu'à la production de KPI vérifiés, la détection statistique d'anomalies et la rédaction de briefings exécutifs auditables.

---

## 1. Vue d'ensemble de l'Architecture

Le système repose sur une séparation stricte des responsabilités entre deux agents interdépendants et un moteur RAG vectoriel à deux niveaux :

```
                                  DONNÉES BRUTES
                      (DataFrames Pandas / CSV / Olist)
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AGENT 5: BI SEMANTIC & KPI AGENT                      │
│                                                                             │
│  1. Profilage dynamique du schéma (types, cardinalité, complétude)          │
│  2. Moteur RAG Vectoriel 2-Tier (FAISS IndexFlatIP + TF-IDF normalisé)      │
│     ├── Score >= 0.30 ──> Tier 1: RAG Vérifié (Retail/E-Commerce, Telecom)  │
│     └── Score <  0.30 ──> Tier 2: Induction Zero-Shot Heuristique           │
│  3. Mappage des rôles sémantiques (sales, profit, dates, entités)           │
│  4. Exécution SQL sécurisée et ultra-rapide sur DuckDB in-memory (:memory:) │
│  5. Émission de l'état avec Audit Lineage complet                           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                         Émet: SemanticKPIState (Pydantic V2)
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENT 6: BI ANALYST AGENT                           │
│                                                                             │
│  1. Statistical Mining :                                                    │
│     ├── Détection d'anomalies par Z-Score (|z| >= 2.0 / 2.5)                │
│     ├── Clôtures d'écart interquartile de Tukey (IQR fences)                │
│     └── Détection des marges négatives et pertes opérationnelles            │
│  2. Analyse de vélocité temporelle :                                        │
│     ├── Croissance période sur période (MoM)                                │
│     ├── Volatilité via Coefficient de Variation (CV = σ / μ)                │
│     └── Classification de trajectoire (SURGING, STABLE, CRASHING, VOLATILE) │
│  3. Analyse des risques de concentration (Loi de Pareto >= 45%)             │
│  4. Synthèse narrative exécutive et recommandations stratégiques priorisées │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                          Émet: BIAnalystState (Pydantic V2)
                                       │
                                       ▼
                     Downstream BI Auditor / XAI Agent
```

---

## 2. Piliers Techniques & Contrats

- **Pydantic V2** : Tous les échanges entre agents respectent des contrats d'interface stricts (`extra="forbid"`, typage strict, immutabilité).
- **Moteur DuckDB In-Memory (`:memory:`)** : Exécution SQL analytique ultra-rapide (< 100 ms) directement sur les DataFrames sans latence réseau ni écriture disque.
- **RAG Vectoriel 2-Tier (FAISS)** :
  - **Tier 1 (Verified RAG)** : Récupération de gabarits SQL éprouvés si la similarité cosinus $\ge 0.30$.
  - **Tier 2 (Zero-Shot Induction)** : Déduction automatique des métriques universelles (volume, montants, ratios, cardinalités) pour les domaines non vus sans planter.
- **Audit Lineage (XAI)** : Chaque KPI, anomalie statistique, tendance et recommandation est obligatoirement lié à son `AuditLineage` (requête SQL exacte, document source, horodatage, seuils statistiques $z$ et $IQR$).

---

## 3. Structure du Projet

```
Bi-flow/
├── bi_pipeline/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── rag_engine.py             # Moteur vectoriel FAISS & routage 2-Tier
│   │   ├── semantic_kpi_agent.py     # Agent 5 : Mappage sémantique & moteur DuckDB
│   │   └── bi_analyst_agent.py       # Agent 6 : Mining statistique & reporting exécutif
│   ├── knowledge_base/
│   │   ├── retail_ecommerce.json     # Règles métier et gabarits Retail / E-commerce
│   │   ├── telecom_saas.json         # Règles métier et gabarits Télécom & SaaS
│   │   └── universal_heuristics.json # Heuristiques universelles de repli (Tier 2)
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── state_schema.py           # Contrats Pydantic V2 (Lineage, États, IPC)
│   ├── data/
│   │   └── mock_clean_data.csv       # Jeu de données de test validé (Superstore Sales)
│   ├── test_pipeline.py              # Suite de tests d'intégration automatisés
│   └── run_olist_analysis.py         # Script d'analyse sur le jeu de données Olist
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 4. Installation & Démarrage Rapide

### Prérequis
- Python 3.10+

### Installation des dépendances
```bash
pip install -r requirements.txt
```

### Exécution des tests d'intégration
```bash
python -m pytest bi_pipeline/test_pipeline.py -v
```

Tous les tests valident :
1. L'inférence Tier 1 sur données Retail.
2. Le repli gracieux Tier 2 sur données IoT / Télémétrie industrielle.
3. La sérialisation / désérialisation JSON stricte via Pydantic V2.
4. L'exécution DuckDB en sous-seconde.
5. Les tests sur les tables réelles E-commerce Olist.

### Lancer une analyse complète sur les données Olist
```bash
python bi_pipeline/run_olist_analysis.py
```

Exemple de sortie produite :
- **Chiffre d'affaires total** : 3 466 786,88 $
- **Panier moyen (AOV)** : 138,67 $
- **Unités vendues** : 33 964 unités
- **Anomalie critique détectée** : Hyper-concentration régionale sur São Paulo (+4.25 écarts-types, 7 fois la moyenne nationale).
- **Trajectoire temporelle** : En forte accélération (+2 118,8 % de croissance de CA, $CV = 0.46$).

---

## 5. Licence
Projet développé sous licence MIT.
