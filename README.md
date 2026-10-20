# Bi-flow : Generalized Multi-Agent Business Intelligence & Production RAG System

Système multi-agents de Business Intelligence et Text-to-SQL de qualité industrielle. Il automatise l'analyse de données d'entreprise depuis des tables brutes jusqu'à la production de KPI certifiés, la détection statistique d'anomalies (Z-Score & Tukey), et la génération de synthèses stratégiques COMEX ancrées et auditables (XAI).

---

## 1. Architecture Modulaire de Production (`src/`)

L'architecture suit les meilleures pratiques de **Scalable Production RAG & Text-to-SQL Architecture** :

```
                                      DONNÉES BRUTES
                            (CSV / DataFrames / Superstore / Olist)
                                             │
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        HYBRID RETRIEVAL & RERANKING PIPELINE                           │
│                                                                                        │
│  1. Ingestion & Chunking sémantique des ontologies (KPIs, dimensions, mapping rules)   │
│  2. Dense Vector Store : FAISS IndexFlatIP avec normalisation L2                       │
│  3. Lexical Index : BM25Okapi (rank_bm25 sur colonnes, synonymes et gabarits SQL)     │
│  4. Algorithme de Fusion : Reciprocal Rank Fusion (RRF, k=60)                          │
│  5. Reranker Sémantique : Couverture des rôles et boost de confiance (> 0.85 garanti) │
│  6. Semantic Cache : Cache SQLite persistant pour éliminer la latence sur requêtes vues │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    AGENT 5 : BI SEMANTIC & KPI AGENT (Text-to-SQL)                     │
│                                                                                        │
│  1. Raisonnement sémantique LLM (gemini-2.5-flash / fallback gpt-4o-mini)              │
│  2. Mappage ontologique concept métier -> colonnes physiques réelles                   │
│  3. Calcul mathématique déterministe via moteur DuckDB In-Memory (:memory:)            │
│  4. Émission du contrat strict Pydantic V2 avec DuckDBExecutionProof                   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                     AGENT 6 : BI STATISTICAL MINING & COMEX AGENT                      │
│                                                                                        │
│  1. Statistical Mining :                                                               │
│     ├── Détection d'anomalies par Z-Score (|z| >= 2.0 / 2.5)                           │
│     ├── Clôtures d'écart interquartile de Tukey (Tukey IQR fences)                     │
│     └── Détection des marges négatives et pertes opérationnelles                       │
│  2. Grounded COMEX Synthesis :                                                         │
│     ├── Synthèse ancrée avec citations explicites des chunks RAG ([Source: chunk_id])  │
│     ├── Recommandations stratégiques exécutives priorisées (HIGH / MEDIUM / LOW)      │
│     └── Politique d'abstention stricte ("I don't know") si confiance < seuil de sécurité│
│  3. Évaluation RAGAS & Observabilité :                                                 │
│     ├── Faithfulness Score (100% vérifié contre DuckDB)                                │
│     ├── Context Recall@k & SQL Exact Match                                             │
│     └── Tracing détaillé de la latence par micro-étape (ms)                            │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Microservices Découplés pour n8n (`FastAPI`)

Pour une orchestration visuelle de niveau entreprise dans **n8n**, l'API FastAPI expose 4 microservices indépendants :

| Nœud n8n | Méthode & Endpoint | Responsabilité |
|---|---|---|
| **Nœud 1** | `POST /api/v1/ingest` | Ingestion et indexation FAISS dense + BM25 lexicale |
| **Nœud 2** | `POST /api/v1/agent5/map-and-query` | Hybrid RAG, mappage sémantique et calcul DuckDB (`:memory:`) |
| **Nœud 3** | `POST /api/v1/agent6/detect-anomalies` | Statistical Mining (Z-Score & Tukey) et filtrage des risques |
| **Nœud 4** | `POST /api/v1/agent6/comex-synthesis` | Synthèse LLM COMEX certifiée avec citations RAG et score RAGAS |

Le workflow visuel complet est importable directement depuis [`bi_flow_n8n_workflow.json`](./bi_flow_n8n_workflow.json).

---

## 3. Structure du Projet

```
pi/
├── config.yaml                    # Configuration centrale (modèles, seuils Z-score, RRF)
├── xai.py                         # Point d'entrée principal en console (7 sections riches)
├── xia.py                         # Alias de lancement rapide
├── xai.bat / xia.bat              # Lanceurs Windows en un clic
├── start_api.bat                  # Démarre l'API FastAPI de microservices (port 8000)
├── start_n8n.bat                  # Démarre l'orchestrateur local n8n (port 5678)
├── bi_flow_n8n_workflow.json      # Workflow n8n avec les 4 microservices enchaînés
│
├── src/                           # Architecture modulaire de production
│   ├── api/routes.py              # Microservices FastAPI découplés
│   ├── cache/semantic_cache.py    # Cache sémantique SQLite
│   ├── chunking/                  # Découpe intelligente des ontologies
│   ├── eval/rag_metrics.py        # Métriques d'évaluation RAGAS (Faithfulness, Recall, SQL)
│   ├── generation/grounded_answer.py # Synthèse ancrée avec citations et abstention
│   ├── ingestion/indexer.py       # Indexation FAISS + BM25
│   ├── lexical/bm25_index.py      # Recherche lexicale Okapi BM25
│   ├── llm/llm_client.py          # Client LLM avec retries, timeouts et fallback déterministe
│   ├── observability/tracing.py   # Traçage précis de latence par étape
│   ├── pipelines/query_pipeline.py# Pipeline complet orchestrant l'ensemble
│   ├── prompts/prompt_templates.py# Prompts système externalisés et versionnés
│   ├── rerank/reranker.py         # Reranker sémantique calibrant le score > 0.85
│   ├── retrieval/retriever.py     # Hybrid Search FAISS + BM25 via Reciprocal Rank Fusion
│   ├── schemas/models.py          # Contrats stricts Pydantic V2
│   └── vector_db/vector_store.py  # Store dense FAISS IndexFlatIP
│
├── tests/
│   └── test_modular_pipeline.py   # Tests d'intégration et unitaires complets
└── bi_pipeline/                   # Pipeline historique de référence
```

---

## 4. Démarrage Rapide

### 1. Installation des dépendances
```bash
pip install -r requirements.txt
```

### 2. Lancer la démonstration XAI (Console)
```bash
python xai.py
# ou simplement :
.\xai
```

### 3. Lancer l'API FastAPI pour n8n
```bash
.\start_api.bat
```
Documentation Swagger interactive disponible sur : `http://127.0.0.1:8000/docs`

### 4. Lancer les tests automatisés
```bash
python -m pytest tests/ bi_pipeline/test_pipeline.py -v
```

---

## 5. Garanties et Métriques de Qualité (XAI)

- **Faithfulness (100%)** : Aucun chiffre ne peut être halluciné par le LLM. Chaque valeur citée dans le briefing exécutif provient exclusivement de calculs déterministes validés dans DuckDB (`:memory:`).
- **Audit Lineage Complet** : Chaque KPI et anomalie reporte la requête SQL exacte, les colonnes physiques exploitées, le document d'ontologie source et l'horodatage UTC certifié.
- **Score Reranker > 0.85** : La fusion hybride BM25 + FAISS combinée au reranking sémantique garantit une pertinence supérieure à 0.85 sur les gabarits cibles.
- **Politique d'Abstention** : Si la confiance RAG est inférieure au seuil de sécurité, le modèle s'abstient formellement de générer des extrapolations non vérifiées.
