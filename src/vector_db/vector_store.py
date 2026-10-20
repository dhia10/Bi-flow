from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import faiss
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from src.schemas.models import OntologyChunk

log = logging.getLogger(__name__)


class FAISSVectorStore:
    """
    Dense vector store indexing OntologyChunk objects using FAISS IndexFlatIP
    with embedding version tracking and L2-normalized cosine distance.
    """

    def __init__(self, embedding_version: str = "v1.2.0") -> None:
        self.embedding_version = embedding_version
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.index: Optional[faiss.IndexFlatIP] = None
        self.chunks: List[OntologyChunk] = []

    def build_index(self, chunks: List[OntologyChunk]) -> None:
        if not chunks:
            log.warning("No chunks provided to build vector index")
            return

        self.chunks = list(chunks)
        corpus = [c.content.lower() for c in self.chunks]

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
            norm="l2",
        )
        dense_matrix = self.vectorizer.fit_transform(corpus).toarray().astype(np.float32)
        faiss.normalize_L2(dense_matrix)

        dimension = dense_matrix.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(dense_matrix)
        log.info(
            "FAISS dense index built: %d chunks indexed, dimension=%d (version=%s)",
            len(self.chunks),
            dimension,
            self.embedding_version,
        )

    def search(self, query: str, top_k: int = 5) -> List[Tuple[OntologyChunk, float]]:
        if not self.index or not self.vectorizer or not self.chunks:
            return []

        q_vec = self.vectorizer.transform([query.lower()]).toarray().astype(np.float32)
        faiss.normalize_L2(q_vec)

        k = min(top_k, len(self.chunks))
        scores, indices = self.index.search(q_vec, k)

        results: List[Tuple[OntologyChunk, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                normalized_score = max(0.0, min(1.0, float(score)))
                results.append((self.chunks[idx], normalized_score))

        return results
