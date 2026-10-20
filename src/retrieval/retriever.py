from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.ingestion.indexer import KnowledgeIndexer
from src.schemas.models import OntologyChunk

log = logging.getLogger(__name__)


class HybridRetriever:
    """
    Hybrid retriever combining FAISS dense vector search (cosine similarity via IndexFlatIP)
    and BM25 lexical keyword matching (BM25Okapi).

    Calculates genuine dynamic hybrid scores reflecting both semantic vector distance
    and lexical term frequency, preserving real score magnitudes without artificial scaling.
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

        # 1. Fetch dense candidates with genuine cosine similarity
        dense_results = self.indexer.vector_store.search(query, top_k=top_k * 3)

        # 2. Fetch lexical candidates with genuine BM25 normalized score
        lexical_results = self.indexer.lexical_index.search(query, top_k=top_k * 3)

        chunk_map: Dict[str, OntologyChunk] = {}
        dense_scores: Dict[str, float] = {}
        lexical_scores: Dict[str, float] = {}

        for chunk, score in dense_results:
            if domain_filter and chunk.domain != domain_filter:
                continue
            if entity_type_filter and chunk.entity_type != entity_type_filter:
                continue
            chunk_map[chunk.chunk_id] = chunk
            dense_scores[chunk.chunk_id] = score

        for chunk, score in lexical_results:
            if domain_filter and chunk.domain != domain_filter:
                continue
            if entity_type_filter and chunk.entity_type != entity_type_filter:
                continue
            chunk_map[chunk.chunk_id] = chunk
            lexical_scores[chunk.chunk_id] = score

        all_ids = set(dense_scores.keys()) | set(lexical_scores.keys())
        if not all_ids:
            return []

        # 3. Weighted hybrid combination reflecting genuine retrieval strength
        hybrid_candidates: List[Tuple[OntologyChunk, float]] = []
        for cid in all_ids:
            d_s = dense_scores.get(cid, 0.0)
            l_s = lexical_scores.get(cid, 0.0)
            score = (self.dense_weight * d_s) + (self.lexical_weight * l_s)
            hybrid_candidates.append((chunk_map[cid], round(score, 4)))

        hybrid_candidates.sort(key=lambda x: x[1], reverse=True)
        return hybrid_candidates[:top_k]
