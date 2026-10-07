from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import faiss
import numpy as np
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger(__name__)


class RAGMatchResult(BaseModel):
    tier: Literal["tier_1_verified_rag", "tier_2_zero_shot_induction"]
    matched_domain: str
    domain_name: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    source_document: str
    description: str
    kpi_templates: List[Dict[str, Any]]
    dimensional_templates: List[Dict[str, Any]]
    column_mapping_rules: Dict[str, Any]


class DomainRAGEngine:
    def __init__(
        self,
        knowledge_base_dir: Optional[Path] = None,
        similarity_threshold: float = 0.30,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.kb_dir = Path(knowledge_base_dir) if knowledge_base_dir else Path(__file__).resolve().parents[1] / "knowledge_base"

        self.vectorizer: Optional[TfidfVectorizer] = None
        self.index: Optional[faiss.IndexFlatIP] = None
        self.domains: List[Dict[str, Any]] = []
        self.fallback_rules: Dict[str, Any] = {}

        self._load_and_index()

    def _load_and_index(self) -> None:
        if not self.kb_dir.is_dir():
            raise FileNotFoundError(f"Knowledge base directory does not exist: {self.kb_dir}")

        fallback_path = self.kb_dir / "universal_heuristics.json"
        if fallback_path.is_file():
            with open(fallback_path, "r", encoding="utf-8") as f:
                self.fallback_rules = json.load(f)

        corpus = []
        for p in sorted(self.kb_dir.glob("*.json")):
            if p.name == "universal_heuristics.json":
                continue
            with open(p, "r", encoding="utf-8") as f:
                entry = json.load(f)
            entry["_source_file"] = p.name
            self.domains.append(entry)

            text_chunks = [
                entry.get("domain_name", ""),
                entry.get("description", ""),
                " ".join(entry.get("keywords", [])),
                " ".join(f"{k} {' '.join(v)}" for k, v in entry.get("column_mapping_rules", {}).items()),
                " ".join(f"{t.get('name', '')} {t.get('description', '')}" for t in entry.get("kpi_templates", [])),
            ]
            corpus.append(" ".join(text_chunks).lower())

        if not self.domains:
            log.warning("No domain files loaded from %s", self.kb_dir)
            return

        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        vectors = self.vectorizer.fit_transform(corpus).toarray().astype(np.float32)
        faiss.normalize_L2(vectors)

        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def retrieve(
        self,
        column_names: List[str],
        sample_values: Optional[List[str]] = None,
        domain_hint: Optional[str] = None,
    ) -> RAGMatchResult:
        query_tokens = [c.replace("_", " ").lower() for c in column_names]
        if sample_values:
            query_tokens.extend(str(v).lower() for v in sample_values[:15])
        if domain_hint:
            query_tokens.append(domain_hint.lower())
        query = " ".join(query_tokens)

        score = 0.0
        doc_idx = -1

        if self.index and self.vectorizer and self.domains:
            q_vec = self.vectorizer.transform([query]).toarray().astype(np.float32)
            faiss.normalize_L2(q_vec)
            scores, indices = self.index.search(q_vec, 1)
            score = max(0.0, min(1.0, float(scores[0][0])))
            doc_idx = int(indices[0][0])

        log.debug("RAG match index=%d score=%.4f (threshold=%.2f)", doc_idx, score, self.similarity_threshold)

        if score >= self.similarity_threshold and doc_idx >= 0:
            doc = self.domains[doc_idx]
            return RAGMatchResult(
                tier="tier_1_verified_rag",
                matched_domain=doc.get("domain_id", "verified_domain"),
                domain_name=doc.get("domain_name", "Verified Domain"),
                similarity_score=round(score, 4),
                source_document=f"knowledge_base/{doc.get('_source_file', 'domain.json')}",
                description=doc.get("description", ""),
                kpi_templates=doc.get("kpi_templates", []),
                dimensional_templates=doc.get("dimensional_templates", []),
                column_mapping_rules=doc.get("column_mapping_rules", {}),
            )

        return RAGMatchResult(
            tier="tier_2_zero_shot_induction",
            matched_domain="unseen_domain_universal",
            domain_name="Unseen Domain (Universal Induction)",
            similarity_score=round(score, 4),
            source_document="knowledge_base/universal_heuristics.json",
            description="Zero-shot statistical induction fallback for unseen schema.",
            kpi_templates=self.fallback_rules.get("universal_kpi_templates", []),
            dimensional_templates=self.fallback_rules.get("universal_dimensional_templates", []),
            column_mapping_rules=self.fallback_rules.get("role_detection_rules", {}),
        )
