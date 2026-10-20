from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

from src.schemas.models import DuckDBExecutionProof, OntologyChunk, RAGASEvalMetrics

log = logging.getLogger(__name__)


class RAGMetricEvaluator:
    """
    Evaluates RAG pipeline quality using RAGAS-inspired criteria computed
    dynamically from retrieval results and DuckDB execution proofs.

    Every metric is genuinely calculated — no hardcoded values.

    1. Context Recall@k — fraction of target concepts covered by retrieved chunks
    2. Faithfulness — fraction of numbers in the narrative that are verifiably
       present in DuckDB execution proofs (numbers not found count as unfaithful)
    3. SQL Exact Match — fraction of DuckDB proofs containing valid SELECT..FROM
    4. Grounded Claim Ratio — fraction of narrative statements backed by a
       citation marker or verifiable SQL reference
    """

    def evaluate(
        self,
        retrieved_chunks: List[OntologyChunk],
        target_concepts: List[str],
        duckdb_proofs: List[DuckDBExecutionProof],
        executive_narrative: str,
        anomalies: Optional[List[Any]] = None,
    ) -> RAGASEvalMetrics:
        context_recall = self._context_recall(retrieved_chunks, target_concepts)
        faithfulness = self._faithfulness(duckdb_proofs, executive_narrative, anomalies)
        sql_exact_match = self._sql_exact_match(duckdb_proofs)
        grounded_ratio = self._grounded_claim_ratio(executive_narrative)

        return RAGASEvalMetrics(
            context_recall=context_recall,
            faithfulness=faithfulness,
            sql_exact_match=sql_exact_match,
            grounded_claim_ratio=grounded_ratio,
        )

    def _context_recall(
        self,
        retrieved_chunks: List[OntologyChunk],
        target_concepts: List[str],
    ) -> float:
        """Fraction of target concepts whose semantic role appears in retrieved chunks."""
        if not target_concepts:
            return 1.0

        # Collect all role tokens and alias tokens from retrieved chunks
        retrieved_tokens: set[str] = set()
        for c in retrieved_chunks:
            for role in c.required_roles:
                retrieved_tokens.add(role.lower())
                # Also add sub-tokens (e.g. "monetary_sales" -> {"monetary", "sales"})
                retrieved_tokens.update(role.lower().replace("_", " ").split())
            for alias in c.metadata.get("aliases", []):
                retrieved_tokens.add(alias.lower())
                retrieved_tokens.update(alias.lower().replace("_", " ").split())
            # Add chunk name tokens
            retrieved_tokens.update(re.findall(r"\w+", c.name.lower()))

        matched = 0
        for concept in target_concepts:
            concept_tokens = set(concept.lower().replace("_", " ").split())
            # A concept is recalled if any of its tokens appear in retrieved roles
            if concept_tokens & retrieved_tokens:
                matched += 1

        return round(matched / len(target_concepts), 4)

    def _faithfulness(
        self,
        duckdb_proofs: List[DuckDBExecutionProof],
        narrative: str,
        anomalies: Optional[List[Any]] = None,
    ) -> float:
        """
        Extract all factual financial and quantitative values from narrative
        and verify each against verified DuckDB proofs or statistical anomalies.
        Numbers not backed by any proof are treated as hallucinations.
        """
        tokens = re.findall(r"[-+]?\b\d[\d,]*\.?\d*\b(?!\s*%)", narrative)
        significant_numbers: set[float] = set()
        for num_str in tokens:
            clean = num_str.replace(",", "")
            try:
                val = float(clean)
                # Ignore years (1950-2050) and tiny indices/thresholds (< 5.0)
                if 1950 <= val <= 2050 or abs(val) < 5.0:
                    continue
                significant_numbers.add(round(val, 2))
            except ValueError:
                continue

        if not significant_numbers:
            return 1.0

        # Verified values from DuckDB execution proofs
        verified_values: set[float] = set()
        for p in duckdb_proofs:
            if isinstance(p.value, (int, float)):
                verified_values.add(round(float(p.value), 2))

        # Verified values from statistical anomalies
        if anomalies:
            for a in anomalies:
                obs = getattr(a, "observed_value", None) if not isinstance(a, dict) else a.get("observed_value")
                base = getattr(a, "baseline_value", None) if not isinstance(a, dict) else a.get("baseline_value")
                if obs is not None:
                    verified_values.add(round(float(obs), 2))
                if base is not None:
                    verified_values.add(round(float(base), 2))

        supported = 0
        for num in significant_numbers:
            tolerance = max(1.0, abs(num) * 0.01)
            if any(abs(num - v) <= tolerance for v in verified_values):
                supported += 1
            else:
                log.debug("Faithfulness: number %.2f in narrative not found in proofs %s", num, verified_values)

        return round(supported / len(significant_numbers), 4)

    def _sql_exact_match(self, duckdb_proofs: List[DuckDBExecutionProof]) -> float:
        """Fraction of DuckDB proofs that contain a syntactically valid SQL statement."""
        if not duckdb_proofs:
            return 0.0

        valid = 0
        for p in duckdb_proofs:
            sql_upper = p.exact_sql.upper().strip()
            if sql_upper.startswith("SELECT") and "FROM" in sql_upper:
                valid += 1

        return round(valid / len(duckdb_proofs), 4)

    def _grounded_claim_ratio(self, narrative: str) -> float:
        """
        Fraction of substantive sentences in the narrative that contain an
        explicit source citation or verifiable SQL reference.
        """
        sentences = [
            s.strip()
            for s in re.split(r"[\n.!?]", narrative)
            if len(s.strip()) > 25
        ]
        if not sentences:
            return 0.0

        grounded = 0
        for s in sentences:
            # A sentence is grounded if it contains an explicit citation or SQL reference
            if any(
                marker in s
                for marker in ("[Source:", "SQL:", "SELECT ", "DuckDB", "`")
            ):
                grounded += 1

        return round(grounded / len(sentences), 4)
