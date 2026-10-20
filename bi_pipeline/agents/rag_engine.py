from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.ingestion.indexer import KnowledgeIndexer
from src.rerank.reranker import SemanticReranker
from src.retrieval.retriever import HybridRetriever

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
    """
    Unified RAG Engine delegating directly to src/ modules:
    - src.ingestion.indexer.KnowledgeIndexer
    - src.retrieval.retriever.HybridRetriever (Dense FAISS + Lexical BM25 via RRF)
    - src.rerank.reranker.SemanticReranker
    Guarantees a single unified RAG engine across the entire codebase.
    """

    def __init__(
        self,
        knowledge_base_dir: Optional[Path] = None,
        similarity_threshold: float = 0.30,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.kb_dir = (
            Path(knowledge_base_dir)
            if knowledge_base_dir
            else Path(__file__).resolve().parents[1] / "knowledge_base"
        )

        # Delegate to unified src/ indexer & hybrid retriever
        self.indexer = KnowledgeIndexer(kb_dir=self.kb_dir)
        self.retriever = HybridRetriever(indexer=self.indexer)
        self.reranker = SemanticReranker()

        self.domain_docs: Dict[str, Dict[str, Any]] = {}
        self.fallback_rules: Dict[str, Any] = {}
        self._load_domain_raw_metadata()

    def _load_domain_raw_metadata(self) -> None:
        if not self.kb_dir.is_dir():
            raise FileNotFoundError(f"Knowledge base directory does not exist: {self.kb_dir}")

        fallback_path = self.kb_dir / "universal_heuristics.json"
        if fallback_path.is_file():
            with open(fallback_path, "r", encoding="utf-8") as f:
                self.fallback_rules = json.load(f)

        for p in sorted(self.kb_dir.glob("*.json")):
            if p.name == "universal_heuristics.json":
                continue
            with open(p, "r", encoding="utf-8") as f:
                entry = json.load(f)
            entry["_source_file"] = p.name
            domain_id = entry.get("domain_id", p.stem)
            self.domain_docs[domain_id] = entry

    def retrieve(
        self,
        column_names: List[str],
        sample_values: Optional[List[str]] = None,
        domain_hint: Optional[str] = None,
    ) -> RAGMatchResult:
        query_parts = [c.replace("_", " ") for c in column_names]
        if sample_values:
            query_parts.extend(str(v) for v in sample_values[:10])
        if domain_hint:
            query_parts.append(domain_hint)
        query = " ".join(query_parts)

        # 1. Unified Hybrid Retrieval (FAISS + BM25 + RRF)
        raw_candidates = self.retriever.retrieve(query, top_k=10)

        # 2. Unified Semantic Reranker
        reranked = self.reranker.rerank(
            query=query,
            candidates=raw_candidates,
            available_columns=column_names,
            top_k=5,
        )

        top_chunk = reranked[0][0] if reranked else None
        top_score = reranked[0][1] if reranked else 0.0

        log.debug("Unified RAG match top_score=%.4f (threshold=%.2f)", top_score, self.similarity_threshold)

        if top_score >= self.similarity_threshold and top_chunk and top_chunk.domain in self.domain_docs:
            doc = self.domain_docs[top_chunk.domain]
            return RAGMatchResult(
                tier="tier_1_verified_rag",
                matched_domain=doc.get("domain_id", top_chunk.domain),
                domain_name=doc.get("domain_name", "Verified Domain"),
                similarity_score=round(top_score, 4),
                source_document=f"knowledge_base/{doc.get('_source_file', 'domain.json')}",
                description=doc.get("description", ""),
                kpi_templates=doc.get("kpi_templates", []),
                dimensional_templates=doc.get("dimensional_templates", []),
                column_mapping_rules=doc.get("column_mapping_rules", {}),
            )

        # Tier 2 Fallback
        return RAGMatchResult(
            tier="tier_2_zero_shot_induction",
            matched_domain="unseen_domain_universal",
            domain_name="Unseen Domain (Universal Induction)",
            similarity_score=round(top_score, 4),
            source_document="knowledge_base/universal_heuristics.json",
            description="Zero-shot statistical induction fallback for unseen schema.",
            kpi_templates=self.fallback_rules.get("universal_kpi_templates", []),
            dimensional_templates=self.fallback_rules.get("universal_dimensional_templates", []),
            column_mapping_rules=self.fallback_rules.get("role_detection_rules", {}),
        )
