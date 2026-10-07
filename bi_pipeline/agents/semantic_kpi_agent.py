from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

from bi_pipeline.agents.rag_engine import DomainRAGEngine, RAGMatchResult
from bi_pipeline.schemas.state_schema import AuditLineage, KPIMetricResult, SemanticKPIState

log = logging.getLogger(__name__)


class BISemanticKPIAgent:
    def __init__(self, rag_engine: Optional[DomainRAGEngine] = None) -> None:
        self.rag = rag_engine or DomainRAGEngine()

    def _profile(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        n_rows = len(df)
        stats = {}
        for c in df.columns:
            s = df[c]
            n_uniq = s.nunique(dropna=True)
            is_num = pd.api.types.is_numeric_dtype(s)
            is_dt = pd.api.types.is_datetime64_any_dtype(s)

            date_hint = False
            if not is_num and not is_dt and s.dtype == "object":
                c_low = c.lower()
                date_hint = any(k in c_low for k in ("date", "time", "timestamp", "year", "month", "day"))

            stats[c] = {
                "dtype": str(s.dtype),
                "is_numeric": is_num,
                "is_datetime": is_dt or date_hint,
                "num_unique": n_uniq,
                "cardinality_ratio": n_uniq / max(1, n_rows),
                "samples": [str(x) for x in s.dropna().head(3).tolist()],
            }
        return stats

    def _map_roles(
        self,
        df: pd.DataFrame,
        profiles: Dict[str, Dict[str, Any]],
        rag_res: RAGMatchResult,
    ) -> Dict[str, str]:
        cols = list(df.columns)
        used = set()
        mapping = {}

        if rag_res.tier == "tier_1_verified_rag":
            for role, aliases in rag_res.column_mapping_rules.items():
                target = None
                for c in cols:
                    if c in used:
                        continue
                    if c.lower() in [a.lower() for a in aliases]:
                        target = c
                        break

                if not target:
                    for c in cols:
                        if c in used:
                            continue
                        clean_c = re.sub(r"[_\s]+", "", c.lower())
                        for a in aliases:
                            clean_a = re.sub(r"[_\s]+", "", a.lower())
                            if clean_a in clean_c or clean_c in clean_a:
                                target = c
                                break
                        if target:
                            break

                if target:
                    mapping[role] = target
                    used.add(target)
        else:
            num_cols = [c for c in cols if profiles[c]["is_numeric"]]
            if num_cols:
                priority_names = ("sales", "revenue", "amount", "price", "value", "cost", "reading", "metric")
                ranked = sorted(
                    num_cols,
                    key=lambda x: (any(p in x.lower() for p in priority_names), profiles[x]["num_unique"]),
                    reverse=True,
                )
                mapping["primary_measure"] = ranked[0]
                used.add(ranked[0])
                if len(ranked) > 1:
                    mapping["secondary_measure"] = ranked[1]
                    used.add(ranked[1])

            id_candidates = [
                c for c in cols
                if c not in used and (
                    any(p in c.lower() for p in ("id", "code", "key", "num", "uuid", "user", "cust"))
                    or profiles[c]["cardinality_ratio"] > 0.3
                )
            ]
            if id_candidates:
                mapping["entity_id"] = id_candidates[0]
                used.add(id_candidates[0])

            cat_candidates = [
                c for c in cols
                if c not in used and not profiles[c]["is_datetime"] and 1 < profiles[c]["num_unique"] <= 50
            ]
            if cat_candidates:
                mapping["primary_dimension"] = cat_candidates[0]
                used.add(cat_candidates[0])

            dt_candidates = [
                c for c in cols
                if profiles[c]["is_datetime"] or any(k in c.lower() for k in ("date", "time", "year", "month"))
            ]
            if dt_candidates:
                mapping["temporal_dimension"] = dt_candidates[0]
                used.add(dt_candidates[0])

        return mapping

    def _render_sql(self, template: str, roles: Dict[str, str]) -> Optional[str]:
        placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", template)
        replacements = {}
        for ph in placeholders:
            if ph not in roles:
                return None
            replacements[ph] = f'"{roles[ph]}"'

        query = template
        for ph, quoted in replacements.items():
            query = query.replace(f"{{{ph}}}", quoted)
        return query

    def analyze(
        self,
        df: pd.DataFrame,
        dataset_name: str = "dataset",
        domain_hint: Optional[str] = None,
    ) -> SemanticKPIState:
        t0 = time.perf_counter()
        if df is None or df.empty:
            raise ValueError("Input DataFrame is empty")

        profiles = self._profile(df)
        table_schema = {c: profiles[c]["dtype"] for c in df.columns}

        sample_pool = []
        for c in df.columns:
            sample_pool.extend(profiles[c]["samples"])

        rag_res = self.rag.retrieve(list(df.columns), sample_pool, domain_hint)
        roles = self._map_roles(df, profiles, rag_res)

        kpis = []
        dim_aggs = {}

        con = duckdb.connect(database=":memory:")
        try:
            con.register("df", df)

            for tpl in rag_res.kpi_templates:
                sql = self._render_sql(tpl["sql_template"], roles)
                if not sql:
                    continue

                try:
                    q_start = time.perf_counter()
                    row = con.execute(sql).fetchone()
                    lat_ms = (time.perf_counter() - q_start) * 1000.0

                    val = None
                    if row and len(row) > 0 and row[0] is not None:
                        raw = row[0]
                        if isinstance(raw, (np.integer, int)):
                            val = int(raw)
                        elif isinstance(raw, (np.floating, float)):
                            val = round(float(raw), 2)
                        else:
                            val = str(raw)

                    cols_used = [roles[r] for r in tpl.get("required_roles", []) if r in roles]
                    lineage = AuditLineage(
                        source_document=f"{rag_res.source_document}#{tpl['id']}",
                        tier=rag_res.tier,
                        similarity_score=rag_res.similarity_score,
                        exact_sql_query=sql,
                        execution_timestamp=datetime.now(timezone.utc),
                        statistical_thresholds={"latency_ms": round(lat_ms, 2)},
                        input_columns_used=cols_used,
                    )

                    kpis.append(
                        KPIMetricResult(
                            kpi_id=tpl["id"],
                            name=tpl["name"],
                            category=tpl.get("category", "general"),
                            description=tpl.get("description", ""),
                            value=val,
                            unit=tpl.get("unit"),
                            lineage=lineage,
                        )
                    )
                except Exception as err:
                    log.debug("Failed executing KPI query for %s: %s", tpl["id"], err)

            for dim_tpl in rag_res.dimensional_templates:
                sql = self._render_sql(dim_tpl["sql_template"], roles)
                if not sql:
                    continue

                try:
                    records = con.execute(sql).fetchdf().to_dict(orient="records")
                    key = dim_tpl.get("dimension_name", dim_tpl["id"])
                    dim_aggs[key] = records

                    for k in kpis:
                        if k.category == "financial" and "revenue" in k.kpi_id and key in ("category", "primary_dimension"):
                            k.breakdown = records[:10]
                except Exception as err:
                    log.debug("Failed executing dimensional query for %s: %s", dim_tpl["id"], err)

        finally:
            con.close()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return SemanticKPIState(
            dataset_name=dataset_name,
            inferred_domain=rag_res.matched_domain,
            domain_confidence=rag_res.similarity_score,
            rag_tier=rag_res.tier,
            table_schema=table_schema,
            row_count=len(df),
            column_count=len(df.columns),
            kpis=kpis,
            dimensional_aggregations=dim_aggs,
            execution_time_ms=round(elapsed_ms, 2),
            created_at=datetime.now(timezone.utc),
        )
