from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrendDirection(str, Enum):
    SURGING = "surging"
    UPWARD = "upward"
    STABLE = "stable"
    DOWNWARD = "downward"
    CRASHING = "crashing"
    VOLATILE = "volatile"


class OntologyChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    domain: str
    entity_type: Literal["kpi", "dimension", "mapping_rule", "heuristic"]
    name: str
    content: str
    sql_template: Optional[str] = None
    required_roles: List[str] = Field(default_factory=list)
    unit: Optional[str] = None
    category: str = "general"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SemanticMappingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    physical_column: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    data_type: str = "unknown"


class DuckDBExecutionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpi_id: str
    kpi_name: str
    value: Optional[Union[float, int, str]] = None
    unit: Optional[str] = None
    exact_sql: str
    latency_ms: float = Field(..., ge=0.0)
    source_chunk_id: str
    columns_used: List[str] = Field(default_factory=list)
    execution_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnomalyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    entity: str
    metric: str
    observed_value: float
    baseline_value: float
    z_score: Optional[float] = None
    iqr_distance: Optional[float] = None
    deviation_pct: float
    severity: RiskSeverity
    proof_rule: str
    description: str


class RAGASEvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_recall: float = Field(..., ge=0.0, le=1.0)
    faithfulness: float = Field(..., ge=0.0, le=1.0)
    sql_exact_match: float = Field(..., ge=0.0, le=1.0)
    grounded_claim_ratio: float = Field(..., ge=0.0, le=1.0)
    eval_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StrategicRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: RiskSeverity
    action: str
    justification: str


class XAIResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    detected_domain: str
    retrieval_relevance_score: float
    retrieval_tier: str
    cache_hit: bool
    semantic_mappings: List[SemanticMappingResult] = Field(default_factory=list)
    duckdb_proofs: List[DuckDBExecutionProof] = Field(default_factory=list)
    anomalies: List[AnomalyReport] = Field(default_factory=list)
    executive_narrative: str
    grounded_citations: List[str] = Field(default_factory=list)
    strategic_recommendations: List[StrategicRecommendation] = Field(default_factory=list)
    trend_metrics: Dict[str, Any] = Field(default_factory=dict)
    breakdown_charts_data: Dict[str, Any] = Field(default_factory=dict)
    eval_metrics: RAGASEvalMetrics
    step_latencies_ms: Dict[str, float] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)
