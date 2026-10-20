from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

import numpy as np

from src.schemas.models import OntologyChunk

log = logging.getLogger(__name__)


def _tokenize(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return [t for t in cleaned.split() if len(t) > 1]


class BM25LexicalIndex:
    """
    Lexical keyword search over column names, synonyms, and SQL formulas
    using Okapi BM25.
    """

    def __init__(self) -> None:
        self.chunks: List[OntologyChunk] = []
        self.bm25: Optional[Any] = None

    def build_index(self, chunks: List[OntologyChunk]) -> None:
        if not chunks:
            return

        self.chunks = list(chunks)
        tokenized_corpus = [_tokenize(c.content) for c in self.chunks]

        try:
            from rank_bm25 import BM25Okapi
            self.bm25 = BM25Okapi(tokenized_corpus)
            log.info("BM25 lexical index built with %d chunks", len(self.chunks))
        except ImportError:
            log.warning("rank_bm25 not available, falling back to TF overlap")
            self.bm25 = None

    def search(self, query: str, top_k: int = 5) -> List[Tuple[OntologyChunk, float]]:
        if not self.chunks:
            return []

        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        if self.bm25 is not None:
            raw_scores = self.bm25.get_scores(q_tokens)
            max_s = float(np.max(raw_scores)) if len(raw_scores) > 0 and np.max(raw_scores) > 0 else 1.0
            norm_scores = [max(0.0, float(s) / max_s) for s in raw_scores]
            
            ranked_indices = np.argsort(raw_scores)[::-1][:top_k]
            return [(self.chunks[idx], float(norm_scores[idx])) for idx in ranked_indices if raw_scores[idx] > 0]
        else:
            # Fallback simple Jaccard / token overlap
            q_set = set(q_tokens)
            scored = []
            for c in self.chunks:
                c_set = set(_tokenize(c.content))
                overlap = len(q_set & c_set) / max(1, len(q_set | c_set))
                scored.append((c, overlap))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
