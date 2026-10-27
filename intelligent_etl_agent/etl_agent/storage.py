from __future__ import annotations
from pathlib import Path
import re
import sqlite3
import pandas as pd

try:
    import duckdb
except ImportError:  # Allows a basic demo even if DuckDB is not installed yet.
    duckdb = None

def _safe_identifier(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if not cleaned:
        raise ValueError("Invalid table name.")
    return cleaned

def save_outputs(output_dir, fact_name, fact, dimensions):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fact_name = _safe_identifier(fact_name)
    fact_csv = output_dir / f"{fact_name}.csv"
    fact.to_csv(fact_csv, index=False)

    dimension_files = {}
    for name, df in dimensions.items():
        safe = _safe_identifier(name)
        path = output_dir / f"{safe}.csv"
        df.to_csv(path, index=False)
        dimension_files[safe] = str(path)

    if duckdb is not None:
        db_path = output_dir / "bi_flow.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            con.register("_fact_df", fact)
            con.execute(f'CREATE OR REPLACE TABLE "{fact_name}" AS SELECT * FROM _fact_df')
            con.unregister("_fact_df")
            for name, df in dimensions.items():
                safe = _safe_identifier(name)
                con.register("_dim_df", df)
                con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _dim_df')
                con.unregister("_dim_df")
        finally:
            con.close()
        db_engine = "duckdb"
    else:
        db_path = output_dir / "bi_flow.sqlite"
        con = sqlite3.connect(db_path)
        try:
            fact.to_sql(fact_name, con, if_exists="replace", index=False)
            for name, df in dimensions.items():
                df.to_sql(_safe_identifier(name), con, if_exists="replace", index=False)
        finally:
            con.close()
        db_engine = "sqlite_fallback"

    return {
        "fact_csv": str(fact_csv),
        "dimension_csvs": dimension_files,
        "database": str(db_path),
        "database_engine": db_engine,
    }
