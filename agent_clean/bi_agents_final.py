# -*- coding: utf-8 -*-
"""
BI Data Profiler & Cleaner Agents (agent_clean)
Production implementation for data identification, profiling, and autonomous cleaning.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

log = logging.getLogger(__name__)

# Key discovery: environment or local key.txt
KEY_PATH = Path(__file__).resolve().parent / "key.txt"
if not os.getenv("GEMINI_API_KEY") and KEY_PATH.is_file():
    raw_key = KEY_PATH.read_text(encoding="utf-8").strip()
    if raw_key:
        os.environ["GEMINI_API_KEY"] = raw_key

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

_genai_client = None


def get_genai_client():
    global _genai_client
    if _genai_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                from google import genai
                _genai_client = genai.Client(api_key=api_key)
            except Exception as e:
                log.warning("Could not initialize google.genai Client: %s", e)
    return _genai_client


ARTIFACT_DIR = "artifacts"


@dataclass
class AgentMessage:
    """Envelope passed between agents. The dataframe itself never goes in the JSON."""
    agent: str
    status: str
    data_ref: str
    payload: dict
    log: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    run_id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str):
        return cls(**json.loads(s))


def save_df(df: pd.DataFrame, run_id: str, name: str) -> str:
    out_dir = Path(ARTIFACT_DIR) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = str(out_dir / f"{name}.parquet")
    try:
        df.to_parquet(path, index=False)
    except Exception:
        df_copy = df.copy()
        for c in df_copy.select_dtypes(include="object"):
            df_copy[c] = df_copy[c].where(df_copy[c].isna(), df_copy[c].astype(str))
        df_copy.to_parquet(path, index=False)
    return path


def fallback_domain_identification(prof: dict) -> dict:
    """Rule-based domain and column roles fallback when LLM is unreachable."""
    cols = list(prof.get("columns", {}).keys())
    cols_lower = [c.lower() for c in cols]

    domain = "generic"
    confidence = 0.80

    if any(k in cols_lower for k in ["sales", "order_id", "product_id", "freight_value", "price"]):
        domain = "retail_ecommerce"
        confidence = 0.95
    elif any(k in cols_lower for k in ["balance", "transaction_id", "account", "loan", "credit"]):
        domain = "banking_finance"
        confidence = 0.90
    elif any(k in cols_lower for k in ["temperature", "pressure", "vibration", "sensor", "telemetry"]):
        domain = "industrial_iot"
        confidence = 0.90

    column_roles = {}
    likely_targets = []
    for c in cols:
        cl = c.lower()
        if "id" in cl or cl.endswith("_id") or cl == "id":
            column_roles[c] = "id"
        elif any(k in cl for k in ["sales", "price", "amount", "revenue", "profit", "cost", "freight"]):
            column_roles[c] = "price"
            likely_targets.append(c)
        elif any(k in cl for k in ["date", "time", "timestamp"]):
            column_roles[c] = "datetime"
        elif any(k in cl for k in ["quantity", "qty", "count", "num"]):
            column_roles[c] = "numeric"
        elif any(k in cl for k in ["city", "state", "country", "region", "geo"]):
            column_roles[c] = "geo"
        elif any(k in cl for k in ["category", "segment", "status", "type"]):
            column_roles[c] = "categorical"
        elif any(k in cl for k in ["is_", "has_", "flag"]):
            column_roles[c] = "boolean"
        else:
            dtype_str = prof.get("columns", {}).get(c, {}).get("dtype", "")
            if "int" in dtype_str or "float" in dtype_str:
                column_roles[c] = "numeric"
            else:
                column_roles[c] = "categorical"

    return {
        "domain": domain,
        "confidence": confidence,
        "description": f"Dataset identified in domain '{domain}' with {len(cols)} columns.",
        "column_roles": column_roles,
        "likely_target_columns": likely_targets,
    }


def fallback_cleaning_plan(payload: dict) -> list:
    """Deterministic rule-based cleaning plan fallback."""
    steps = []
    issues = payload.get("issues", [])
    profile_data = payload.get("profile", {})
    cols_info = profile_data.get("columns", {})

    for issue in issues:
        typ = issue.get("type")
        col = issue.get("column")

        if typ == "duplicates":
            steps.append({
                "op": "drop_duplicates",
                "params": {},
                "reason": "Eliminate identical rows.",
            })
        elif typ == "constant" and col:
            steps.append({
                "op": "drop_columns",
                "params": {"columns": [col]},
                "reason": f"Column '{col}' provides zero variance.",
            })
        elif typ == "wrong_dtype" and col:
            detail = issue.get("detail", "")
            if "dates" in detail:
                steps.append({
                    "op": "cast_type",
                    "params": {"column": col, "to": "datetime"},
                    "reason": f"Cast '{col}' from text to datetime.",
                })
            elif "numeric" in detail:
                steps.append({
                    "op": "cast_type",
                    "params": {"column": col, "to": "float"},
                    "reason": f"Cast '{col}' from text to float.",
                })
        elif typ == "missing" and col:
            col_dtype = cols_info.get(col, {}).get("dtype", "")
            if "float" in col_dtype or "int" in col_dtype:
                steps.append({
                    "op": "fill_missing",
                    "params": {"column": col, "strategy": "median"},
                    "reason": f"Impute missing numeric values in '{col}' with median.",
                })
            else:
                steps.append({
                    "op": "fill_missing",
                    "params": {"column": col, "strategy": "mode"},
                    "reason": f"Impute missing categorical values in '{col}' with mode.",
                })

    return steps


def ask_json(system: str, user: str, max_tokens: int = 8000, retries: int = 3) -> dict:
    """LLM call returning a dict. Retries with exponential backoff; fallback if unavailable."""
    client = get_genai_client()
    if not client:
        raise RuntimeError("No Gemini API client available.")

    from google.genai import types

    for attempt in range(retries):
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system + "\nReply with a single valid JSON object only.",
                    response_mime_type="application/json",
                    max_output_tokens=max_tokens,
                ),
            )
            text = r.text
            return json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception as e:
            transient = any(
                k in str(e) for k in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
            )
            if not transient or attempt == retries - 1:
                raise
            time.sleep(1)


# Deterministic profiling, issue detection, quality score
SEVERITY_WEIGHT = {"high": 6, "medium": 3, "low": 1}
INFO_ONLY = {"anomalous_rows"}


def profile(df: pd.DataFrame, n_samples: int = 5) -> dict:
    return {
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": {
            c: {
                "dtype": str(df[c].dtype),
                "null_pct": round(float(df[c].isna().mean() * 100), 1),
                "n_unique": int(df[c].nunique()),
                "samples": df[c].dropna().astype(str).head(n_samples).tolist(),
            }
            for c in df.columns
        },
    }


def _sev(pct: float, high: float, mid: float) -> str:
    return "high" if pct >= high else "medium" if pct >= mid else "low"


def detect_anomalous_rows(df: pd.DataFrame) -> list:
    """ML check: IsolationForest on numeric columns."""
    n = len(df)
    num = [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])
        and df[c].nunique() > 2
        and df[c].nunique() < 0.95 * n
    ]
    if len(num) < 2 or n < 50:
        return []
    try:
        X = df[num].fillna(df[num].median())
        model = IsolationForest(n_estimators=100, random_state=42)
        model.fit(X.sample(min(n, 20000), random_state=42))
        scores = model.score_samples(X)
        q1, q3 = np.percentile(scores, [25, 75])
        k = int((scores < q1 - 3 * (q3 - q1)).sum())
        if k == 0:
            return []
        pct = k / n * 100
        return [{
            "column": None,
            "type": "anomalous_rows",
            "severity": _sev(pct, 10, 5),
            "detail": f"{k} rows ({pct:.1f}%) flagged by IsolationForest on {len(num)} numeric columns: {num}",
        }]
    except Exception as e:
        log.debug("IsolationForest skipped: %s", e)
        return []


def detect_issues(df: pd.DataFrame) -> list:
    """Rule-based detection: duplicates, missing, constant cols, wrong dtypes, outliers (3*IQR)."""
    issues, n = [], max(len(df), 1)

    def add(col, typ, sev, detail):
        issues.append({"column": col, "type": typ, "severity": sev, "detail": detail})

    dup = int(df.duplicated().sum())
    if dup:
        add(None, "duplicates", _sev(dup / n * 100, 10, 1), f"{dup} duplicate rows")

    for c in df.columns:
        s = df[c]
        null_pct = float(s.isna().mean() * 100)
        if null_pct > 0:
            add(c, "missing", _sev(null_pct, 30, 5), f"{null_pct:.1f}% missing")
        if s.nunique(dropna=True) <= 1:
            add(c, "constant", "low", "column has <= 1 distinct value")
            continue

        if s.dtype == object or pd.api.types.is_string_dtype(s):
            non_null = s.dropna()
            if non_null.empty:
                continue
            if pd.to_numeric(non_null, errors="coerce").notna().mean() > 0.9:
                add(c, "wrong_dtype", "high", "numeric values stored as text")
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    parsed = pd.to_datetime(non_null.head(500), errors="coerce")
                if parsed.notna().mean() > 0.9:
                    add(c, "wrong_dtype", "high", "dates stored as text")
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            q1, q3 = s.quantile([0.25, 0.75])
            iqr = q3 - q1
            if iqr > 0:
                out_pct = float(((s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)).mean() * 100)
                if out_pct > 0:
                    add(c, "outliers", _sev(out_pct, 5, 1), f"{out_pct:.1f}% beyond 3*IQR")
    issues += detect_anomalous_rows(df)
    return issues


def quality_score(issues: list, n_cols: int) -> float:
    """100 minus weighted issue penalty, normalised by dataset width."""
    penalty = sum(SEVERITY_WEIGHT[i["severity"]] for i in issues if i["type"] not in INFO_ONLY)
    return round(100 * (1 - min(1, penalty / (6 * (n_cols + 1)))), 1)


# Agent 1: Data Profiler
class DataProfilerAgent:
    NAME = "data_profiler"
    SYSTEM = (
        "You are a data identification expert. Given a dataset profile, identify what kind "
        "of data it is. Return JSON with keys: "
        "domain (short, e.g. 'hotel', 'e-commerce', 'telecom'), confidence (0-1), "
        "description (one sentence), "
        "column_roles (dict column -> one of: id, categorical, numeric, datetime, text, "
        "boolean, geo, price, rating, other), "
        "likely_target_columns (list of column names, may be empty)."
    )

    def run(self, df: pd.DataFrame) -> AgentMessage:
        run_id = uuid.uuid4().hex[:8]
        try:
            df = df.copy()
            # blank strings are hidden missing values: turn them into NaN so they get detected
            text_cols = [
                c for c in df.columns
                if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])
            ]
            blanks = {c: int(df[c].astype(str).str.strip().eq("").sum()) for c in text_cols}
            blanks = {c: n for c, n in blanks.items() if n}
            if text_cols:
                df[text_cols] = df[text_cols].replace(r"^\s*$", np.nan, regex=True)

            prof = profile(df)
            try:
                ident = ask_json(self.SYSTEM, json.dumps(prof, ensure_ascii=False))
            except Exception as e:
                log.warning("LLM identification failed (%s). Using deterministic domain induction.", e)
                ident = fallback_domain_identification(prof)

            issues = detect_issues(df)
            payload = {
                **ident,
                "profile": prof,
                "issues": issues,
                "quality_score": quality_score(issues, df.shape[1]),
            }
            log_steps = [{"step": "blank_strings_to_nan", "columns": blanks}] if blanks else []
            return AgentMessage(self.NAME, "ok", save_df(df, run_id, "raw"), payload, log=log_steps, run_id=run_id)
        except Exception as e:
            return AgentMessage(self.NAME, "error", "", {}, errors=[repr(e)], run_id=run_id)


# Agent 2: Data Cleaner
def _op_drop_duplicates(df, **_):
    return df.drop_duplicates()


def _op_drop_columns(df, columns, **_):
    return df.drop(columns=[c for c in columns if c in df.columns])


def _op_drop_missing_rows(df, column, **_):
    return df.dropna(subset=[column])


def _op_fill_missing(df, column, strategy, value=None, **_):
    s = df[column]
    if strategy == "mean":
        fill = s.mean()
    elif strategy == "median":
        fill = s.median()
    elif strategy == "mode":
        m = s.mode()
        fill = m.iloc[0] if len(m) else None
    elif strategy == "constant":
        fill = value
    else:
        raise ValueError(f"unknown strategy {strategy}")
    if fill is not None:
        df[column] = s.fillna(fill)
    return df


def _op_cast_type(df, column, to, **_):
    if to == "datetime":
        df[column] = pd.to_datetime(df[column], errors="coerce")
    elif to in ("int", "float"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if to == "int":
            df[column] = df[column].astype("Int64")
    elif to == "category":
        df[column] = df[column].astype("category")
    elif to == "str":
        df[column] = df[column].astype(str)
    else:
        raise ValueError(f"unknown type {to}")
    return df


def _op_standardize_text(df, column, **_):
    df[column] = df[column].where(df[column].isna(), df[column].astype(str).str.strip().str.lower())
    return df


def _op_clip_outliers(df, column, lower_q=0.01, upper_q=0.99, **_):
    lo, hi = df[column].quantile([lower_q, upper_q])
    df[column] = df[column].clip(lo, hi)
    return df


OPS = {
    "drop_duplicates": _op_drop_duplicates,
    "drop_columns": _op_drop_columns,
    "drop_missing_rows": _op_drop_missing_rows,
    "fill_missing": _op_fill_missing,
    "cast_type": _op_cast_type,
    "standardize_text": _op_standardize_text,
    "clip_outliers": _op_clip_outliers,
}


class DataCleanerAgent:
    NAME = "data_cleaner"
    SYSTEM = (
        "You are a data cleaning expert. Given a dataset's domain, column roles, profile and "
        "detected issues, produce a cleaning plan. Return JSON: "
        '{"steps": [{"op": <name>, "params": {...}, "reason": "<why, one sentence>"}]}. '
        "Allowed ops and params: drop_duplicates{}; drop_columns{columns}; "
        "drop_missing_rows{column}; fill_missing{column, strategy: mean|median|mode|constant, value?}; "
        "cast_type{column, to: datetime|int|float|category|str}; standardize_text{column}; "
        "clip_outliers{column, lower_q?, upper_q?}. "
        "Only use existing columns. Cast types before filling or clipping. "
        "Do not clean what is not broken. Issues of type anomalous_rows are informational only: "
        "never drop or change rows because of them."
    )

    def plan(self, payload: dict) -> list:
        try:
            ctx = {k: payload[k] for k in ("domain", "column_roles", "issues", "profile") if k in payload}
            return ask_json(self.SYSTEM, json.dumps(ctx, ensure_ascii=False))["steps"]
        except Exception as e:
            log.warning("LLM cleaning planning failed (%s). Using deterministic rules.", e)
            return fallback_cleaning_plan(payload)

    def run(self, msg: AgentMessage) -> AgentMessage:
        if msg.status != "ok":
            return AgentMessage(self.NAME, "error", msg.data_ref, {}, errors=["upstream error"], run_id=msg.run_id)
        try:
            df = pd.read_parquet(msg.data_ref)
            decisions = []

            for step in self.plan(msg.payload):
                op, params = step["op"], step.get("params", {})
                rec = {"op": op, "params": params, "reason": step.get("reason", "")}
                if op not in OPS:
                    decisions.append({**rec, "status": "skipped: unknown op"})
                    continue
                try:
                    col = params.get("column")
                    if col is not None and col not in df.columns:
                        raise KeyError(f"column '{col}' not found")
                    rows0, nulls0 = len(df), int(df.isna().sum().sum())
                    df = OPS[op](df.copy(), **params)
                    decisions.append({
                        **rec, "status": "ok",
                        "rows_removed": rows0 - len(df),
                        "null_change": int(df.isna().sum().sum()) - nulls0,
                    })
                except Exception as e:
                    decisions.append({**rec, "status": f"failed: {e}"})

            after_issues = detect_issues(df)
            payload = {
                "domain": msg.payload.get("domain", "generic"),
                "column_roles": msg.payload.get("column_roles", {}),
                "shape": list(df.shape),
                "quality_before": msg.payload.get("quality_score", 100.0),
                "quality_after": quality_score(after_issues, df.shape[1]),
                "decisions": decisions,
                "remaining_issues": after_issues,
            }
            return AgentMessage(self.NAME, "ok", save_df(df, msg.run_id, "clean"), payload, run_id=msg.run_id)
        except Exception as e:
            return AgentMessage(self.NAME, "error", msg.data_ref, {}, errors=[repr(e)], run_id=msg.run_id)


if __name__ == "__main__":
    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else "bi_pipeline/data/mock_clean_data.csv"
    if Path(test_file).is_file():
        df_in = pd.read_csv(test_file)
        p_out = DataProfilerAgent().run(df_in)
        print("PROFILER OUTPUT:")
        print(p_out.to_json())
        c_out = DataCleanerAgent().run(p_out)
        print("\nCLEANER OUTPUT:")
        print(c_out.to_json())
