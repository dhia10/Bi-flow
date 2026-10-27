from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class JoinStep(BaseModel):
    right_table: str
    source_table: str = ""
    left_on: str
    right_on: str
    how: Literal["left", "inner"] = "left"
    reason: str = ""

class DerivedColumn(BaseModel):
    name: str
    operation: Literal["multiply", "add", "subtract", "divide"]
    inputs: list[str] = Field(min_length=2, max_length=2)
    reason: str = ""

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise ValueError("Derived column names must be alphanumeric/underscore only.")
        return value

class DateFeature(BaseModel):
    source_column: str
    features: list[Literal["year", "month", "day", "quarter", "month_name"]] = Field(default_factory=list)
    reason: str = ""

class DimensionPlan(BaseModel):
    source_table: str
    dimension_name: str
    key: str

class ETLPlan(BaseModel):
    domain: str = "unknown"
    schema_type: Literal["star_schema", "snowflake_schema"] = "star_schema"
    schema_reason: str = ""
    base_table: str
    fact_table: str = "fact_data"
    joins: list[JoinStep] = Field(default_factory=list)
    derived_columns: list[DerivedColumn] = Field(default_factory=list)
    date_features: list[DateFeature] = Field(default_factory=list)
    dimensions: list[DimensionPlan] = Field(default_factory=list)
    planner_summary: str = ""
    domain_source: str = "unknown"
    domain_subdomain: str = ""
    domain_confidence: str = "low"
    domain_evidence: list[str] = Field(default_factory=list)
    business_processes: list[str] = Field(default_factory=list)
    measure_sources: dict[str, str] = Field(default_factory=dict)
    semantic_notes: list[str] = Field(default_factory=list)
