from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.ingestion.indexer import KnowledgeIndexer
from src.schemas.models import OntologyChunk

log = logging.getLogger(__name__)


class HybridRetriever:
    """
    Hybrid retriever combining FAISS dense vector search and BM25 lexical keyword matching
    using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        indexer: KnowledgeIndexer,
        dense_weight: float = 0.6,
        lexical_weight: float = 0.4,
        rrf_k: int = 60,
    ) -> None:
        self.indexer = indexer
        self.dense_weight = dense_weight
        self.lexical_weight = lexical_weight
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        domain_filter: Optional[str] = None,
        entity_type_filter: Optional[str] = None,
    ) -> List[Tuple[OntologyChunk, float]]:
        if not self.indexer.chunks:
            self.indexer.run_indexing()

        # 1. Fetch dense candidates
        dense_results = self.indexer.vector_store.search(query, top_k=top_k * 3)
        # 2. Fetch lexical candidates
        lexical_results = self.indexer.lexical_index.search(query, top_k=top_k * 3)

        # 3. Apply Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = {}
        chunk_map: Dict[str, OntologyChunk] = {}

        for rank, (chunk, _) in enumerate(dense_results, start=1):
            if domain_filter and chunk.domain != domain_filter:
                continue
            if entity_type_filter and chunk.entity_type != entity_type_filter:
                continue
            chunk_map[chunk.chunk_id] = chunk
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + (
                self.dense_weight / (self.rrf_k + rank)
            )

        for rank, (chunk, _) in enumerate(lexical_results, start=1):
            if domain_filter and chunk.domain != domain_filter:
                continue
            if entity_type_filter and chunk.entity_type != entity_type_filter:
                continue
            chunk_map[chunk.chunk_id] = chunk
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + (
                self.lexical_weight / (self.rrf_k + rank)
            )

        if not rrf_scores:
            return []

        # Normalize RRF scores
        max_rrf = max(rrf_scores.values())
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        return [(chunk_map[cid], round(score / max_rrf, 4)) for cid, score in ranked]
