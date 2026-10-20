from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from src.schemas.models import DuckDBExecutionProof, OntologyChunk

log = logging.getLogger(__name__)


class GroundedAnswerGenerator:
    """
    Grounded COMEX summary generator with strict RAG chunk citations ([Source: chunk_id])
    and explicit abstention ('I don't know') policy when retrieval confidence is insufficient.
    """

    def __init__(self, min_confidence_threshold: float = 0.40) -> None:
        self.min_confidence = min_confidence_threshold

    def generate(
        self,
        dataset_name: str,
        detected_domain: str,
        retrieval_confidence: float,
        retrieved_chunks: List[Tuple[OntologyChunk, float]],
        duckdb_proofs: List[DuckDBExecutionProof],
        raw_summary: str,
    ) -> Tuple[str, List[str], bool]:
        """
        Returns:
            Tuple of (grounded_narrative, citations_list, was_abstained)
        """
        # Strict Abstention Policy
        if retrieval_confidence < self.min_confidence:
            abstention_text = (
                f"ABSTENTION STRICTE (Politique 'I don't know') : "
                f"Le score de confiance RAG ({retrieval_confidence:.2f}) est inférieur au seuil de sécurité ({self.min_confidence:.2f}). "
                f"Aucune synthèse financière extrapolée n'est générée pour éviter tout risque d'hallucination."
            )
            return abstention_text, [], True

        citations = []
        for chunk, score in retrieved_chunks[:3]:
            citations.append(f"[Source: {chunk.chunk_id} (Relevance: {score:.2f})]")

        citations_str = " ".join(citations)

        # Grounded COMEX synthesis injecting exact verified proofs
        lines = [
            f"### Synthèse Exécutive COMEX Certifiée",
            f"{raw_summary} {citations_str}",
            f"",
            f"#### Preuves Mathématiques & Citations d'Origine :",
        ]

        for proof in duckdb_proofs[:4]:
            val_str = f"{proof.value:,.2f}" if isinstance(proof.value, float) else f"{proof.value}"
            lines.append(
                f"- **{proof.kpi_name}** : `{val_str} {proof.unit or ''}` "
                f"[Source: `{proof.source_chunk_id}`] | *SQL: `{proof.exact_sql}`*"
            )

        grounded_text = "\n".join(lines)
        return grounded_text, citations, False
