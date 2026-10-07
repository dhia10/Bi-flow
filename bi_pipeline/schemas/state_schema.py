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


class AuditLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_document: str
    tier: Literal["tier_1_verified_rag", "tier_2_zero_shot_induction"]
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    exact_sql_query: str
    execution_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    statistical_thresholds: Optional[Dict[str, Any]] = None
    input_columns_used: List[str] = Field(default_factory=list)


class KPIMetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpi_id: str
    name: str
    category: str
    description: str
    value: Optional[Union[float, int, str]] = None
    unit: Optional[str] = None
    breakdown: Optional[List[Dict[str, Any]]] = None
    lineage: AuditLineage


class SemanticKPIState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    inferred_domain: str
    domain_confidence: float = Field(..., ge=0.0, le=1.0)
    rag_tier: Literal["tier_1_verified_rag", "tier_2_zero_shot_induction"]
    table_schema: Dict[str, str]
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=0)
    kpis: List[KPIMetricResult] = Field(default_factory=list)
    dimensional_aggregations: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    execution_time_ms: float = Field(..., ge=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatisticalAnomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    entity: str
    metric_name: str
    observed_value: float
    expected_value: float
    z_score: Optional[float] = None
    iqr_distance: Optional[float] = None
    pct_deviation: float
    severity: RiskSeverity
    description: str
    lineage: AuditLineage


class TrendInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    dimension: str
    direction: TrendDirection
    growth_rate_pct: float
    volatility_cv: float
    acceleration: Optional[float] = None
    lineage: AuditLineage


class StrategicTakeaway(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    executive_summary: str
    severity: RiskSeverity
    implication: str
    recommended_action: str
    supporting_kpis: List[str] = Field(default_factory=list)
    lineage: AuditLineage


class BIAnalystState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    semantic_state: SemanticKPIState
    statistical_anomalies: List[StatisticalAnomaly] = Field(default_factory=list)
    trend_insights: List[TrendInsight] = Field(default_factory=list)
    strategic_takeaways: List[StrategicTakeaway] = Field(default_factory=list)
    executive_narrative: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PipelineRunOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_state: SemanticKPIState
    analyst_state: BIAnalystState
    total_execution_time_ms: float
    pipeline_version: str = "1.0.0"

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)


class SemanticConceptMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_concept: str
    mapped_column: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class SemanticMappingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_domain: str
    mappings: List[SemanticConceptMapping]


class InterpretedAnomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    severity: RiskSeverity
    business_explanation: str
    financial_impact: str


class StrategicRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: RiskSeverity
    action: str
    justification: str


class StrategicAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    interpreted_anomalies: List[InterpretedAnomaly]
    strategic_recommendations: List[StrategicRecommendation]
