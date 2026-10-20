from __future__ import annotations

import logging
import re
from typing import List, Tuple

from src.schemas.models import OntologyChunk

log = logging.getLogger(__name__)


class SemanticReranker:
    """
    Reranker scoring candidate OntologyChunks using a weighted combination of:
    1. Dense and lexical hybrid retrieval score
    2. Semantic role coverage (exact and token-level match against DataFrame columns)
    3. Token overlap between query and chunk content

    No artificial floor is applied — scores reflect genuine semantic relevance.
    """

    def __init__(
        self,
        dense_weight: float = 0.40,
        role_weight: float = 0.40,
        overlap_weight: float = 0.20,
    ) -> None:
        self.dense_weight = dense_weight
        self.role_weight = role_weight
        self.overlap_weight = overlap_weight

    def rerank(
        self,
        query: str,
        candidates: List[Tuple[OntologyChunk, float]],
        available_columns: List[str],
        top_k: int = 5,
    ) -> List[Tuple[OntologyChunk, float]]:
        if not candidates:
            return []

        query_tokens = set(re.findall(r"\w+", query.lower()))

        reranked: List[Tuple[OntologyChunk, float]] = []

        for chunk, initial_score in candidates:
            # 1. Semantic role coverage (0.0 to 1.0)
            req_roles = chunk.required_roles
            if req_roles:
                roles_matched = 0
                for role in req_roles:
                    aliases = chunk.metadata.get("aliases", [role])
                    clean_aliases = [re.sub(r"[_\s]+", "", a.lower()) for a in aliases]

                    role_found = False
                    for c in available_columns:
                        c_clean = re.sub(r"[_\s]+", "", c.lower())
                        c_tokens = set(re.findall(r"\w+", c.lower()))
                        if c_clean in clean_aliases or any(
                            a.lower() == c.lower() or a.lower() in c_tokens
                            for a in aliases
                            if len(a) > 2
                        ):
                            role_found = True
                            break

                    if role_found:
                        roles_matched += 1

                role_coverage = roles_matched / len(req_roles)
            else:
                # Universal template with no required roles gets neutral coverage
                role_coverage = 0.3

            # 2. Token overlap between query and chunk content
            chunk_tokens = set(re.findall(r"\w+", chunk.content.lower()))
            overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))

            # 3. Dynamic weighted composite calculation
            final_score = (
                self.dense_weight * min(1.0, initial_score)
                + self.role_weight * role_coverage
                + self.overlap_weight * overlap
            )

            final_score = round(max(0.0, min(1.0, final_score)), 4)
            reranked.append((chunk, final_score))

        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]
