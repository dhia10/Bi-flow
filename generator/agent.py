#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BI Agent v6.1  -  agent.py
================================================================
Agent BI universel: ingestion CSV/XLS/XLSX, extraction automatique
de KPIs, generation de SQL Apache Superset, catalogue kpis_catalog.json,
pipeline NL-SQL (RAG BM25 + Ollama + Gemini fallback), persistance
des visuels entre rechargements de page.

NOUVEAUTE v6.1 :
  - inject_where() : ajoute un WHERE col IN (...) a la requete SQL d'un visuel
  - POST /api/agent/filter-sql : filtre global (date, categorie, statut...) applique
    cote serveur aux visuels auto-generes (sans spec cote agent.js)

Integration dans start_server.py:
    import agent as BI_AGENT
    BI_AGENT.register(NoCacheHandler)

Standalone (debug):
    python agent.py --port 8081
================================================================
"""

import json
import os
import re
import io
import csv
import math
import copy
import time
import hashlib
import sqlite3
import threading
import traceback
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

HAS_PANDAS = False
HAS_OPENPYXL = False
HAS_XLRD = False

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    pass

try:
    from openpyxl import load_workbook
    HAS_OPENPYXL = True
except ImportError:
    pass

try:
    import xlrd
    HAS_XLRD = True
except ImportError:
    pass

# =================== CONFIG ===================
CFG = {
    "catalog_path"       : "kpis_catalog.json",
    "visuals_path"       : "visuals_state.json",
    "upload_dir"         : "uploads",
    "ollama_url"         : "http://localhost:11434",
    "ollama_model"       : "llama3.2:3b",
    "gemini_key"         : None,
    "gemini_model"       : "gemini-2.0-flash",
    "gemini_endpoint"    : "https://generativelanguage.googleapis.com/v1beta/models",
    "max_rows_sample"    : 50000,
    "max_kpis_per_file"  : 25,
    "pie_max_slices"     : 8,
    "top_n_default"      : 10,
    "timeout_llm"        : 20,
    "timeout_gemini"     : 15,
    "rag_top_k"          : 6,
    "bm25_k1"            : 1.2,
    "bm25_b"             : 0.75,
}

_catalog_lock = threading.Lock()
_tables = {}
_sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)

# =================== UTILS ===================
_FR_CHARS = str.maketrans("aaaeeeeiioouuc", "aaaeeeeiioouuc")

def ascii_norm(s):
    import unicodedata
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode("ascii")

def tokenize(s):
    return re.findall(r"[a-zA-Z]+", ascii_norm(str(s)))

def humanize(col):
    s = re.sub(r"[\(\)\[\]_\-\/\\]", " ", str(col)).strip()
    return re.sub(r"\s+", " ", s).title()

def slugify(s):
    s = ascii_norm(str(s))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_").upper()
    return s[:40]

def qi(s):
    return '"' + str(s).replace('"', '""') + '"'

def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None

def fmt_value(v, kind="measure"):
    if v is None:
        return "N/A"
    try:
        f = float(v)
        if kind == "pct":
            return f"{f:.1f}%"
        if f >= 1e12:
            return f"${f/1e12:.2f}T"
        if f >= 1e9:
            return f"${f/1e9:.2f}B"
        if f >= 1e6:
            return f"${f/1e6:.2f}M"
        if f >= 1000:
            return f"{f:,.0f}"
        return f"{f:.2f}"
    except Exception:
        return str(v)

def guess_kind(col):
    c = ascii_norm(col)
    if any(k in c for k in ["revenue","revenu","chiffre","ca","sales","vente","montant",
                              "prix","price","salaire","income","profit","cost","cout",
                              "valeur","value","market","gdp","pib","trade","export","import"]):
        return "money"
    if any(k in c for k in ["count","nombre","nb","qty","quantity","total","num"]):
        return "count"
    if any(k in c for k in ["pct","percent","ratio","rate","taux","part","share",
                              "growth","croissance","inflation","unemployment"]):
        return "pct"
    return "measure"

def guess_chart_type(dim_type, measure_kind, n_distinct):
    if dim_type == "time":
        return "line"
    if n_distinct <= 6:
        return "pie"
    return "bar"

def make_kpi_id(table, measure, dim=None):
    parts = ["KPI", slugify(table), slugify(measure)]
    if dim:
        parts.append(slugify(dim))
    return "_".join(parts)[:60]


# =================== FILE INGESTION ===================
def _rows_from_csv(content, filename):
    for enc in ("utf-8-sig","utf-8","latin-1","cp1252"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("latin-1", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for i, row in enumerate(reader):
        if i >= CFG["max_rows_sample"]:
            break
        rows.append(dict(row))
    cols = list(rows[0].keys()) if rows else []
    return rows, cols

def _rows_from_xlsx(path):
    if HAS_PANDAS:
        df = pd.read_excel(path, nrows=CFG["max_rows_sample"])
        cols = list(df.columns.astype(str))
        rows = [{str(k): (None if pd.isna(v) else v) for k, v in r.items()} for _, r in df.iterrows()]
        return rows, cols
    if HAS_OPENPYXL:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        raw = list(ws.iter_rows(values_only=True))
        wb.close()
        if not raw:
            return [], []
        cols = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(raw[0])]
        rows = [{cols[i]: raw[r][i] for i in range(len(cols))} for r in range(1, min(len(raw), CFG["max_rows_sample"]+1))]
        return rows, cols
    raise RuntimeError("Pandas ou openpyxl requis pour lire les fichiers XLSX.")

def _rows_from_xls(path):
    if HAS_PANDAS:
        df = pd.read_excel(path, nrows=CFG["max_rows_sample"])
        cols = list(df.columns.astype(str))
        rows = [{str(k): (None if pd.isna(v) else v) for k, v in r.items()} for _, r in df.iterrows()]
        return rows, cols
    if HAS_XLRD:
        wb = xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        cols = [str(ws.cell_value(0, c)) for c in range(ws.ncols)]
        rows = [{cols[c]: ws.cell_value(r, c) for c in range(ws.ncols)} for r in range(1, min(ws.nrows, CFG["max_rows_sample"]+1))]
        return rows, cols
    raise RuntimeError("Pandas ou xlrd requis pour lire les fichiers XLS.")

def _cast_types(rows, cols):
    if not rows:
        return rows
    numeric_cols = set()
    for col in cols:
        successes = 0
        for row in rows[:200]:
            v = row.get(col)
            if v is None or v == "":
                continue
            try:
                float(str(v).replace(",", ".").replace(" ", ""))
                successes += 1
            except Exception:
                break
        else:
            if successes > 0:
                numeric_cols.add(col)
    result = []
    for row in rows:
        new_row = {}
        for col, v in row.items():
            if col in numeric_cols and v not in (None, ""):
                try:
                    fv = float(str(v).replace(",", ".").replace(" ", ""))
                    new_row[col] = int(fv) if fv == int(fv) and abs(fv) < 1e15 else fv
                except Exception:
                    new_row[col] = v
            else:
                new_row[col] = v
        result.append(new_row)
    return result

def _load_into_sqlite(table_name, rows, cols, schema):
    if not rows or not cols:
        return
    try:
        safe_cols = [f'"{c}" REAL' if c in schema.get("num", []) else f'"{c}" TEXT' for c in cols]
        _sqlite_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        _sqlite_conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(safe_cols)})')
        placeholders = ", ".join(["?"] * len(cols))
        def _sql_val(v):
            if v is None:
                return None
            if hasattr(v, "isoformat"):
                return v.isoformat()
            if not isinstance(v, (int, float, str, bytes, bool)):
                return str(v)
            return v
        val_tuples = [tuple(_sql_val(r.get(c)) for c in cols) for r in rows]
        _sqlite_conn.executemany(f'INSERT INTO "{table_name}" VALUES ({placeholders})', val_tuples)
        _sqlite_conn.commit()
    except Exception as _e:
        print(f"[agent.py] SQLite load error on {table_name}: {_e}")

def ingest_file(path):
    p = Path(path)
    suffix = p.suffix.lower()
    table_name = slugify(p.stem)

    if suffix in (".xlsx", ".xls") and HAS_PANDAS:
        try:
            xl = pd.ExcelFile(str(p))
            sheets = xl.sheet_names
            primary_info = None
            for sname in sheets:
                df = pd.read_excel(xl, sheet_name=sname, nrows=CFG["max_rows_sample"])
                cols = list(df.columns.astype(str))
                rows = [{str(k): (None if pd.isna(v) else v) for k, v in r.items()} for _, r in df.iterrows()]
                rows = _cast_types(rows, cols)
                schema = analyze_schema(rows, cols)
                s_table = slugify(sname) if len(sheets) > 1 else table_name
                alias_table = ascii_norm(sname).replace(" ", "_")
                _tables[s_table] = rows
                _tables[alias_table] = rows
                _load_into_sqlite(s_table, rows, cols, schema)
                _load_into_sqlite(alias_table, rows, cols, schema)
                info = {"table_name": s_table, "filename": p.name, "rows": rows, "columns": cols, "n_rows": len(rows), "schema": schema, "sheet": sname}
                if primary_info is None:
                    primary_info = info
            if primary_info is not None:
                return primary_info
        except Exception:
            pass

    if suffix == ".csv":
        rows, cols = _rows_from_csv(p.read_bytes(), p.name)
    elif suffix == ".xlsx":
        rows, cols = _rows_from_xlsx(str(p))
    elif suffix == ".xls":
        rows, cols = _rows_from_xls(str(p))
    else:
        raise ValueError(f"Format non supporte: {suffix}")
    rows = _cast_types(rows, cols)
    schema = analyze_schema(rows, cols)
    _tables[table_name] = rows
    alias_table = ascii_norm(p.stem).replace(" ", "_")
    _tables[alias_table] = rows
    _load_into_sqlite(table_name, rows, cols, schema)
    _load_into_sqlite(alias_table, rows, cols, schema)
    return {"table_name": table_name, "filename": p.name, "rows": rows, "columns": cols, "n_rows": len(rows), "schema": schema}

# =================== SCHEMA ANALYSIS ===================
_TIME_PATTERNS = [r"^\d{4}$", r"^\d{4}-\d{2}(-\d{2})?$", r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$"]
_TIME_KEYWORDS = ["date","year","annee","mois","month","jour","day","period","quarter","trimestre","week","time"]
_GEO_KEYWORDS  = ["country","pays","region","ville","city","province","state","continent","zone","area","location"]

def analyze_schema(rows, cols):
    if not rows:
        return {"num":[],"cat":[],"time":[],"geo":[],"bool":[],"id":[],"text":[]}
    num_cols, cat_cols, time_cols, geo_cols, bool_cols, id_cols, text_cols = [], [], [], [], [], [], []
    for col in cols:
        col_lower = ascii_norm(col)
        sample = [rows[i].get(col) for i in range(min(200, len(rows))) if rows[i].get(col) not in (None, "")]
        if not sample:
            continue
        n_distinct = len(set(str(v) for v in sample))
        n_sample = len(sample)
        num_count = sum(1 for v in sample if safe_float(v) is not None)
        is_numeric = num_count / n_sample > 0.85
        is_time = any(kw in col_lower for kw in _TIME_KEYWORDS)
        if not is_time and not is_numeric:
            str_sample = [str(v) for v in sample[:10]]
            is_time = all(any(re.match(p, s) for p in _TIME_PATTERNS) for s in str_sample[:5] if s)
        is_geo = any(kw in col_lower for kw in _GEO_KEYWORDS)
        str_vals = set(ascii_norm(str(v)) for v in sample[:50])
        is_bool = str_vals.issubset({"0","1","true","false","oui","non","yes","no"})
        is_id = (n_distinct / n_sample > 0.95) and not is_numeric
        if is_bool:
            bool_cols.append(col)
        elif is_time:
            time_cols.append(col)
        elif is_numeric:
            num_cols.append(col)
        elif is_geo:
            geo_cols.append(col)
        elif is_id:
            id_cols.append(col)
        elif n_distinct <= max(50, n_sample * 0.3):
            cat_cols.append(col)
        else:
            text_cols.append(col)
    return {"num":num_cols,"cat":cat_cols,"time":time_cols,"geo":geo_cols,"bool":bool_cols,"id":id_cols,"text":text_cols}


# =================== SQL GENERATOR ===================
def gen_sql_aggregate(table, measure, agg="SUM", alias=None):
    a = alias or ascii_norm(measure).replace(" ", "_")
    return f'SELECT {agg}({qi(measure)}) AS {qi(a)} FROM {qi(table)};'

def gen_sql_by_dim(table, measure, dim, agg="SUM", top_n=10, sort="DESC", filters=None):
    a = ascii_norm(measure).replace(" ", "_")
    where = ""
    if filters:
        clauses = [f'{qi(f["col"])} = \'{f["val"]}\'' for f in filters]
        where = " WHERE " + " AND ".join(clauses)
    limit = f" LIMIT {top_n}" if top_n else ""
    return f'SELECT {qi(dim)}, {agg}({qi(measure)}) AS {qi(a)} FROM {qi(table)}{where} GROUP BY {qi(dim)} ORDER BY {qi(a)} {sort}{limit};'

def gen_sql_count_by_dim(table, dim, top_n=10):
    return f'SELECT {qi(dim)}, COUNT(*) AS "count" FROM {qi(table)} GROUP BY {qi(dim)} ORDER BY "count" DESC LIMIT {top_n};'

def gen_sql_trend(table, measure, time_col, agg="SUM"):
    a = ascii_norm(measure).replace(" ", "_")
    return f'SELECT {qi(time_col)}, {agg}({qi(measure)}) AS {qi(a)} FROM {qi(table)} GROUP BY {qi(time_col)} ORDER BY {qi(time_col)} ASC;'

# =================== IN-MEMORY SQL EXECUTOR ===================
def _parse_sql(sql):
    sql = sql.strip().rstrip(";")
    sql_norm = re.sub(r"\s+", " ", sql, flags=re.IGNORECASE)
    m = re.match(r"SELECT\s+(.+?)\s+FROM\s+([^\s]+)", sql_norm, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse SQL: {sql[:80]}")
    select_raw = m.group(1).strip()
    from_table = m.group(2).strip().strip('"').strip("'").strip("`")
    rest = sql_norm[m.end():]
    where_clause = None
    mw = re.search(r"\bWHERE\b(.+?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", rest, re.IGNORECASE)
    if mw:
        where_clause = mw.group(1).strip()
    group_cols = []
    mg = re.search(r"\bGROUP\s+BY\s+(.+?)(?:\bORDER\b|\bLIMIT\b|$)", rest, re.IGNORECASE)
    if mg:
        group_cols = [c.strip().strip('"') for c in mg.group(1).split(",")]
    order_cols = []
    mo = re.search(r"\bORDER\s+BY\s+(.+?)(?:\bLIMIT\b|$)", rest, re.IGNORECASE)
    if mo:
        for part in mo.group(1).split(","):
            part = part.strip()
            asc_desc = "DESC" if "DESC" in part.upper() else "ASC"
            col = re.sub(r"\b(ASC|DESC)\b", "", part, flags=re.IGNORECASE).strip().strip('"')
            order_cols.append({"col": col, "dir": asc_desc})
    limit = None
    ml = re.search(r"\bLIMIT\s+(\d+)", rest, re.IGNORECASE)
    if ml:
        limit = int(ml.group(1))
    select_cols = []
    for part in _split_select(select_raw):
        part = part.strip()
        alias = None
        ma = re.match(r"(.+?)\s+AS\s+([^\s,]+)$", part, re.IGNORECASE)
        if ma:
            expr_raw = ma.group(1).strip()
            alias = ma.group(2).strip().strip('"')
        else:
            expr_raw = part
        agg_m = re.match(r"(SUM|COUNT|AVG|MIN|MAX)\s*\(\s*(.+?)\s*\)", expr_raw, re.IGNORECASE)
        if agg_m:
            fn = agg_m.group(1).upper()
            inner = agg_m.group(2).strip()
            col_name = "*" if inner == "*" else inner.strip('"')
            select_cols.append({"type":"agg","fn":fn,"col":col_name,"alias":alias or f"{fn.lower()}_{col_name}"})
        else:
            col_name = expr_raw.strip('"')
            select_cols.append({"type":"col","col":col_name,"alias":alias or col_name})
    return {"select":select_cols,"from":from_table,"where":where_clause,"group_by":group_cols,"order_by":order_cols,"limit":limit}

def _split_select(s):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts

def _eval_where(row, clause):
    if not clause:
        return True
    parts = re.split(r"\bAND\b", clause, flags=re.IGNORECASE)
    for part in parts:
        or_parts = re.split(r"\bOR\b", part.strip(), flags=re.IGNORECASE)
        any_true = False
        for op in or_parts:
            op = op.strip()
            m = re.match(r'"?(\w[\w\s]*?)"?\s*(=|!=|<>|>=|<=|>|<|LIKE)\s*(.+)', op, re.IGNORECASE)
            if not m:
                continue
            col = m.group(1).strip().strip('"')
            op_sym = m.group(2).upper()
            val_raw = m.group(3).strip()
            row_val = row.get(col)
            if row_val is None:
                continue
            if val_raw.startswith("'") and val_raw.endswith("'"):
                cmp = val_raw[1:-1]
                row_str = str(row_val)
                if op_sym == "=":
                    any_true = any_true or (row_str.lower() == cmp.lower())
                elif op_sym in ("!=","<>"):
                    any_true = any_true or (row_str.lower() != cmp.lower())
                elif op_sym == "LIKE":
                    pat = cmp.replace("%",".*").replace("_",".")
                    any_true = any_true or bool(re.search(pat, row_str, re.IGNORECASE))
            else:
                try:
                    cmp_num = float(val_raw)
                    row_num = safe_float(row_val)
                    if row_num is None:
                        continue
                    if op_sym == "=":   any_true = any_true or (row_num == cmp_num)
                    elif op_sym in ("!=","<>"):  any_true = any_true or (row_num != cmp_num)
                    elif op_sym == ">":  any_true = any_true or (row_num > cmp_num)
                    elif op_sym == "<":  any_true = any_true or (row_num < cmp_num)
                    elif op_sym == ">=": any_true = any_true or (row_num >= cmp_num)
                    elif op_sym == "<=": any_true = any_true or (row_num <= cmp_num)
                except Exception:
                    pass
        if not any_true:
            return False
    return True

def execute_sql(sql, tables=None):
    clean_sql = (sql or "").strip().rstrip(";")
    if not clean_sql:
        return []
    try:
        cur = _sqlite_conn.cursor()
        cur.execute(clean_sql)
        if cur.description:
            col_names = [d[0] for d in cur.description]
            return [dict(zip(col_names, row)) for row in cur.fetchall()]
    except Exception:
        pass
    tables = tables or _tables
    try:
        parsed = _parse_sql(sql)
    except Exception:
        return []
    table_name = parsed["from"]
    rows = tables.get(table_name)
    if rows is None:
        for k in tables:
            if k.lower().startswith(table_name.lower()[:8]) or table_name.lower().startswith(k.lower()[:8]):
                rows = tables[k]
                break
    if rows is None:
        return []
    if parsed["where"]:
        rows = [r for r in rows if _eval_where(r, parsed["where"])]
    if parsed["group_by"]:
        groups = {}
        gkeys = parsed["group_by"]
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in gkeys)
            groups.setdefault(key, []).append(row)
        result_rows = []
        for key, group in groups.items():
            out = {gkeys[i]: key[i] for i in range(len(gkeys))}
            for sel in parsed["select"]:
                if sel["type"] == "agg":
                    fn, col, alias = sel["fn"], sel["col"], sel["alias"]
                    if fn == "COUNT":
                        out[alias] = len(group)
                    else:
                        vals = [safe_float(r.get(col)) for r in group if safe_float(r.get(col)) is not None]
                        if fn == "SUM":   out[alias] = sum(vals) if vals else None
                        elif fn == "AVG": out[alias] = sum(vals)/len(vals) if vals else None
                        elif fn == "MIN": out[alias] = min(vals) if vals else None
                        elif fn == "MAX": out[alias] = max(vals) if vals else None
            result_rows.append(out)
    else:
        first_agg = next((s for s in parsed["select"] if s["type"]=="agg"), None)
        if first_agg:
            fn, col, alias = first_agg["fn"], first_agg["col"], first_agg["alias"]
            if fn == "COUNT":
                val = len(rows)
            else:
                vals = [safe_float(r.get(col)) for r in rows if safe_float(r.get(col)) is not None]
                if fn == "SUM":   val = sum(vals) if vals else None
                elif fn == "AVG": val = sum(vals)/len(vals) if vals else None
                elif fn == "MIN": val = min(vals) if vals else None
                elif fn == "MAX": val = max(vals) if vals else None
                else:             val = None
            result_rows = [{alias: val}]
        else:
            result_rows = []
            for row in rows:
                out = {}
                for sel in parsed["select"]:
                    out[sel["alias"]] = row.get(sel["col"])
                result_rows.append(out)
    for ob in reversed(parsed["order_by"]):
        rev = ob["dir"] == "DESC"
        result_rows.sort(key=lambda r: (r.get(ob["col"]) is None, r.get(ob["col"]) or 0), reverse=rev)
    if parsed["limit"] is not None:
        result_rows = result_rows[:parsed["limit"]]
    return [{k: v for k, v in r.items() if k is not None} for r in result_rows]


# =================== [v6.1] INJECTION DE FILTRE WHERE ===================
def inject_where(sql, filters):
    """
    Ajoute `WHERE col IN (...)` (ou complete un WHERE existant) a la requete SQL
    d'un visuel. `filters` = [{"col": "statut", "values": ["Actif"]}, ...].
    Retourne None si aucune colonne du filtre n'existe dans la table source
    (le visuel n'est alors pas concerne par ce filtre global).
    """
    sql = "\n".join(
        l for l in (sql or "").strip().rstrip(";").splitlines()
        if not l.strip().startswith("--")
    )
    m = re.search(r'\bFROM\s+"?([A-Za-z0-9_\.]+)"?', sql, re.I)
    if not m:
        return None
    table = m.group(1).split(".")[-1]
    try:
        cols = {r[1] for r in _sqlite_conn.execute(f'PRAGMA table_info("{table}")')}
    except Exception:
        return None
    if not cols:
        return None
    conds = []
    for f in filters or []:
        col = next((c for c in cols if c.lower() == str(f.get("col", "")).lower()), None)
        vals = f.get("values") or []
        if col and vals:
            in_list = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
            conds.append(f'"{col}" IN ({in_list})')
    if not conds:
        return None
    cond = " AND ".join(conds)
    if re.search(r'\bWHERE\b', sql, re.I):
        return re.sub(r'\bWHERE\b', f'WHERE {cond} AND', sql, count=1, flags=re.I)
    tail = re.search(r'\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b', sql, re.I)
    if tail:
        return sql[:tail.start()] + f'WHERE {cond} ' + sql[tail.start():]
    return sql + f' WHERE {cond}'

def detect_filter(text):
    """Cherche dans toutes les tables SQLite une colonne texte dont des valeurs sont citées dans le prompt."""
    t = " " + re.sub(r"[^a-z0-9]+", " ", ascii_norm(text)) + " "
    best = None
    tables = [r[0] for r in _sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for tname in tables:
        cols = [r[1] for r in _sqlite_conn.execute(f'PRAGMA table_info("{tname}")') if str(r[2]).upper() == "TEXT"]
        for col in cols:
            try:
                vals = [r[0] for r in _sqlite_conn.execute(
                    f'SELECT DISTINCT "{col}" FROM "{tname}" WHERE "{col}" IS NOT NULL LIMIT 500')]
            except Exception:
                continue
            if not (2 <= len(vals) <= 300):
                continue
            hits = []
            for v in vals:
                a = re.sub(r"[^a-z0-9]+", " ", ascii_norm(v)).strip()
                if len(a) >= 3 and f" {a} " in t:
                    hits.append(str(v))
            if hits:
                c = re.sub(r"[^a-z0-9]+", " ", ascii_norm(col)).strip()
                score = len(hits) + (3 if f" {c} " in t else 0)
                if not best or score > best["score"]:
                    best = {"col": col, "values": hits, "score": score}
    return best

# =================== KPI EXTRACTOR ===================
def extract_kpis(info):
    table  = info["table_name"]
    rows   = info["rows"]
    schema = info["schema"]
    label  = humanize(info["filename"].rsplit(".", 1)[0])
    kpis   = []
    used   = set()

    def add(k):
        if k["id"] not in used:
            used.add(k["id"])
            kpis.append(k)

    num_cols  = schema["num"][:12]
    cat_cols  = schema["cat"][:8]
    time_cols = schema["time"][:2]
    geo_cols  = schema["geo"][:3]

    # 1. Global card KPI per numeric column
    for mc in num_cols:
        kind = guess_kind(mc)
        agg  = "SUM" if kind in ("money","measure") else "COUNT"
        sql  = gen_sql_aggregate(table, mc, agg)
        res  = execute_sql(sql)
        raw  = list(res[0].values())[0] if res else 0
        kid  = make_kpi_id(table, mc)
        add({
            "id": kid, "name": f"Total {humanize(mc)} - {label}",
            "domain": label, "category": "Global",
            "description": f"{agg} de la colonne {mc} dans {label}.",
            "source_table": label, "table_name": table,
            "aggregation_type": agg, "metric_column": mc,
            "dimension_column": None, "chart_type": "card",
            "superset_chart_type": "big_number_total",
            "sql_superset": sql, "raw_value": raw,
            "current_value_formatted": fmt_value(raw, kind),
            "suggested_prompts": [f"Total {humanize(mc)}", f"KPI global {humanize(mc)}", f"Valeur totale de {humanize(mc)}"],
            "active": True, "source_file": info["filename"], "top_n": None,
            "dax_measure": f"{humanize(mc)} Total = {agg}('{label}'[{mc}])",
            "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/{slugify(mc).lower()}/total"},
        })

    # 2. Measure x Categorical dimension
    for mc in num_cols[:8]:
        kind = guess_kind(mc)
        agg  = "SUM" if kind in ("money","measure") else "AVG"
        for dc in cat_cols[:5]:
            n_dist = len(set(str(r.get(dc,"")) for r in rows if r.get(dc)))
            if n_dist < 2 or n_dist > 200:
                continue
            chart = guess_chart_type("cat", kind, n_dist)
            top_n = CFG["pie_max_slices"] if chart == "pie" else CFG["top_n_default"]
            sql   = gen_sql_by_dim(table, mc, dc, agg=agg, top_n=top_n)
            res   = execute_sql(sql)
            if not res:
                continue
            kid = make_kpi_id(table, mc, dc)
            add({
                "id": kid, "name": f"{humanize(mc)} par {humanize(dc)}",
                "domain": label, "category": humanize(dc),
                "description": f"{agg}({mc}) groupe par {dc}.",
                "source_table": label, "table_name": table,
                "aggregation_type": agg, "metric_column": mc,
                "dimension_column": dc, "chart_type": chart,
                "superset_chart_type": "echarts_bar" if chart=="bar" else "pie",
                "sql_superset": sql, "raw_value": None,
                "current_value_formatted": None,
                "suggested_prompts": [f"{humanize(mc)} par {humanize(dc)}", f"Top {top_n} {humanize(dc)} selon {humanize(mc)}", f"Affiche {humanize(mc)} par {humanize(dc)}"],
                "active": True, "source_file": info["filename"], "top_n": top_n,
                "dax_measure": f"{humanize(mc)} By {humanize(dc)} = {agg}('{label}'[{mc}])",
                "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/{slugify(mc).lower()}/by/{slugify(dc).lower()}"},
                "_data": res,
            })

    # 3. Count by categorical dimension
    for dc in cat_cols[:4]:
        n_dist = len(set(str(r.get(dc,"")) for r in rows if r.get(dc)))
        if n_dist < 2 or n_dist > 100:
            continue
        chart = "pie" if n_dist <= 6 else "bar"
        top_n = CFG["pie_max_slices"] if chart == "pie" else CFG["top_n_default"]
        sql   = gen_sql_count_by_dim(table, dc, top_n=top_n)
        res   = execute_sql(sql)
        if not res:
            continue
        kid = make_kpi_id(table, "count", dc)
        add({
            "id": kid, "name": f"Distribution {humanize(dc)}",
            "domain": label, "category": humanize(dc),
            "description": f"Nombre d'entrees par {dc}.",
            "source_table": label, "table_name": table,
            "aggregation_type": "COUNT", "metric_column": "*",
            "dimension_column": dc, "chart_type": chart,
            "superset_chart_type": "echarts_bar" if chart=="bar" else "pie",
            "sql_superset": sql, "raw_value": len(rows),
            "current_value_formatted": str(len(rows)),
            "suggested_prompts": [f"Distribution {humanize(dc)}", f"Combien de {humanize(dc)}", f"Repartition par {humanize(dc)}"],
            "active": True, "source_file": info["filename"], "top_n": top_n,
            "dax_measure": f"Count {humanize(dc)} = COUNT('{label}'[{dc}])",
            "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/count/{slugify(dc).lower()}"},
            "_data": res,
        })

    # 4. Temporal trend
    for mc in num_cols[:4]:
        kind = guess_kind(mc)
        agg  = "SUM" if kind in ("money","measure") else "AVG"
        for tc in time_cols[:2]:
            sql = gen_sql_trend(table, mc, tc, agg=agg)
            res = execute_sql(sql)
            if len(res) < 2:
                continue
            kid = make_kpi_id(table, mc, tc)
            add({
                "id": kid, "name": f"Evolution {humanize(mc)} dans le temps",
                "domain": label, "category": "Temporel",
                "description": f"Tendance temporelle de {mc} par {tc}.",
                "source_table": label, "table_name": table,
                "aggregation_type": agg, "metric_column": mc,
                "dimension_column": tc, "chart_type": "line",
                "superset_chart_type": "echarts_line",
                "sql_superset": sql, "raw_value": None,
                "current_value_formatted": None,
                "suggested_prompts": [f"Evolution de {humanize(mc)} par {humanize(tc)}", f"Tendance {humanize(mc)}", f"Courbe {humanize(mc)}"],
                "active": True, "source_file": info["filename"], "top_n": None,
                "dax_measure": f"{humanize(mc)} Trend = {agg}('{label}'[{mc}])",
                "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/{slugify(mc).lower()}/trend"},
                "_data": res,
            })

    # 5. Geographic KPIs
    for mc in num_cols[:3]:
        agg = "SUM"
        for gc in geo_cols[:2]:
            sql = gen_sql_by_dim(table, mc, gc, agg=agg, top_n=15)
            res = execute_sql(sql)
            if not res:
                continue
            kid = make_kpi_id(table, mc, gc)
            add({
                "id": kid, "name": f"{humanize(mc)} par {humanize(gc)}",
                "domain": label, "category": "Geographique",
                "description": f"{agg}({mc}) par zone geographique ({gc}).",
                "source_table": label, "table_name": table,
                "aggregation_type": agg, "metric_column": mc,
                "dimension_column": gc, "chart_type": "bar",
                "superset_chart_type": "echarts_bar",
                "sql_superset": sql, "raw_value": None,
                "current_value_formatted": None,
                "suggested_prompts": [f"{humanize(mc)} par {humanize(gc)}", f"Top pays selon {humanize(mc)}"],
                "active": True, "source_file": info["filename"], "top_n": 15,
                "dax_measure": f"{humanize(mc)} By Geo = {agg}('{label}'[{mc}])",
                "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/{slugify(mc).lower()}/geo"},
                "_data": res,
            })

    return kpis[:CFG["max_kpis_per_file"]]

def kpi_to_visual_config(kpi):
    chart_type = kpi.get("chart_type", "bar")
    data = kpi.get("_data") or []
    if not data:
        sql = kpi.get("sql_superset", "")
        if sql:
            data = execute_sql(sql)
    if not data and chart_type != "card":
        return None
    mc = kpi.get("metric_column", "")
    dc = kpi.get("dimension_column", "")
    keys = list(data[0].keys()) if data else []
    label_field = dc if dc and dc in keys else (keys[0] if keys else "label")
    num_keys = [k for k in keys if k != label_field]
    value_field = num_keys[0] if num_keys else (keys[1] if len(keys) > 1 else "value")
    card_val = kpi.get("raw_value") if kpi.get("raw_value") is not None else kpi.get("current_value", 0)
    card_fmt = kpi.get("current_value_formatted") or (f"{card_val:,.2f}" if isinstance(card_val, (int, float)) else str(card_val))
    return {
        "id"         : f"kpi-{kpi['id'].lower().replace('_','-')}",
        "kpi_id"     : kpi["id"],
        "title"      : kpi["name"],
        "subtitle"   : f"Dataset: {kpi.get('source_file','')} | SQL Superset",
        "chartType"  : chart_type,
        "domain"     : kpi.get("domain",""),
        "data"       : data,
        "labelField" : label_field,
        "valueField" : value_field,
        "metricLabel": humanize(mc),
        "sql"        : kpi.get("sql_superset",""),
        "dax"        : kpi.get("dax_measure", "-- Mesure DAX"),
        "superset"   : { "viz_type": "echarts_timeseries_bar" if chart_type == "bar" else ("pie" if chart_type == "pie" else "echarts_timeseries_line"), "metric": mc },
        "active"     : kpi.get("active", True),
        "source_file": kpi.get("source_file",""),
        "top_n"      : kpi.get("top_n", CFG["top_n_default"]),
        "cardValue"  : card_val,
        "cardValueFormatted": card_fmt,
        "cardBenchmark": kpi.get("description", "Mesure calculée"),
    }


# =================== CATALOG MANAGER ===================
def load_catalog():
    p = Path(CFG["catalog_path"])
    if not p.exists():
        return {"metadata":{"version":"1.0.0","datasets":[],"generated_by":"BI Agent v6.1"},"kpis":[]}
    with open(p,"r",encoding="utf-8") as f:
        return json.load(f)

def save_catalog(catalog):
    with _catalog_lock:
        with open(CFG["catalog_path"],"w",encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)

def replace_catalog_from_upload(kpis, info, auto_visuals=None):
    old_catalog = load_catalog()
    dashboard_bg = old_catalog.get("metadata", {}).get("dashboard_background", "")
    # Preserve existing prompt_visuals (NL-created) across dataset change
    old_prompt_visuals = old_catalog.get("prompt_visuals", [])
    catalog = {
        "metadata": {
            "version": "2.0.0",
            "active_dataset": info["filename"],
            "table_name": info["table_name"],
            "n_rows": info["n_rows"],
            "columns": info["columns"],
            "datasets": [info["filename"]],
            "last_updated": datetime.now().isoformat(),
            "generated_by": "Dynamic BI Engine (User Dataset Upload)"
        },
        "kpis": kpis
    }
    if dashboard_bg:
        catalog["metadata"]["dashboard_background"] = dashboard_bg
    # Save auto-generated visuals so they survive F5
    if auto_visuals:
        catalog["auto_visuals"] = auto_visuals
    # Keep prompt visuals (user-created via chat) if dataset context didn't change radically
    if old_prompt_visuals:
        catalog["prompt_visuals"] = old_prompt_visuals
    save_catalog(catalog)
    return catalog

def upsert_kpis(kpis, dataset_label=""):
    catalog = load_catalog()
    existing = {k["id"]: i for i, k in enumerate(catalog["kpis"])}
    for kpi in kpis:
        clean = dict(kpi)
        if kpi["id"] in existing:
            catalog["kpis"][existing[kpi["id"]]].update(clean)
        else:
            catalog["kpis"].append(clean)
    if dataset_label and dataset_label not in catalog["metadata"].get("datasets",[]):
        catalog["metadata"].setdefault("datasets",[]).append(dataset_label)
    catalog["metadata"]["last_updated"] = datetime.now().isoformat()
    catalog["metadata"]["generated_by"] = "BI Agent v6.1"
    save_catalog(catalog)
    return catalog

def delete_kpi_from_catalog(kpi_id):
    catalog = load_catalog()
    orig = len(catalog["kpis"])
    catalog["kpis"] = [k for k in catalog["kpis"] if k["id"] != kpi_id]
    if len(catalog["kpis"]) < orig:
        save_catalog(catalog)
        return True
    return False

def get_kpi(kpi_id):
    for k in load_catalog().get("kpis",[]):
        if k["id"] == kpi_id:
            return k
    return None

# =================== VISUAL MANAGER ===================
def load_visuals():
    p = Path(CFG["visuals_path"])
    if not p.exists():
        return {"visuals":[]}
    with open(p,"r",encoding="utf-8") as f:
        return json.load(f)

def save_visuals(state):
    with open(CFG["visuals_path"],"w",encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def upsert_visual(visual_cfg):
    state = load_visuals()
    cfg_id = visual_cfg.get("id","")
    existing = {v["id"]: i for i, v in enumerate(state["visuals"]) if "id" in v}
    save_vc = {k: v for k, v in visual_cfg.items() if k != "data"}
    if cfg_id in existing:
        state["visuals"][existing[cfg_id]].update(save_vc)
    else:
        state["visuals"].append(save_vc)
    save_visuals(state)

def delete_visual(visual_id):
    state = load_visuals()
    state["visuals"] = [v for v in state["visuals"] if v.get("id") != visual_id]
    save_visuals(state)
    catalog = load_catalog()
    changed = False
    if "auto_visuals" in catalog and isinstance(catalog["auto_visuals"], list):
        orig_av = len(catalog["auto_visuals"])
        catalog["auto_visuals"] = [v for v in catalog["auto_visuals"] if v.get("id") != visual_id and v.get("title") != visual_id and v.get("kpi_id") != visual_id]
        if len(catalog["auto_visuals"]) != orig_av:
            changed = True
    if visual_id.startswith("kpi-"):
        for k in catalog.get("kpis", []):
            if f"kpi-{k['id'].lower().replace('_','-')}" == visual_id:
                k["active"] = False
                changed = True
    if changed:
        save_catalog(catalog)

# =================== PROMPT VISUALS PERSISTENCE ===================
def load_prompt_visuals():
    """Load visuals created by agent prompts from kpis_catalog.json (with fallback to visuals_state.json)."""
    try:
        catalog = load_catalog()
        if "prompt_visuals" in catalog and isinstance(catalog["prompt_visuals"], list):
            return catalog["prompt_visuals"]
    except Exception:
        pass
    p = Path(CFG["visuals_path"])
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("prompt_visuals", [])
    except Exception:
        return []

def save_prompt_visuals(visuals_list):
    """Persist the list of prompt-created visuals into kpis_catalog.json and visuals_state.json."""
    try:
        catalog = load_catalog()
        catalog["prompt_visuals"] = visuals_list
        catalog.setdefault("metadata", {})["last_updated"] = datetime.now().isoformat()
        save_catalog(catalog)
    except Exception as e:
        print(f"[agent.py] Failed to save prompt_visuals to kpis_catalog.json: {e}")

    p = Path(CFG["visuals_path"])
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {"visuals": []}
    except Exception:
        state = {"visuals": []}
    state["prompt_visuals"] = visuals_list
    state["prompt_visuals_updated"] = datetime.now().isoformat()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def upsert_prompt_visual(entry):
    """Add or update a prompt-created visual by its sid."""
    visuals = load_prompt_visuals()
    sid = entry.get("sid", "")
    idx = next((i for i, v in enumerate(visuals) if v.get("sid") == sid), -1)
    if idx >= 0:
        visuals[idx] = entry
    else:
        visuals.append(entry)
    save_prompt_visuals(visuals)

def delete_prompt_visual(sid):
    """Remove a prompt-created visual by its sid from kpis_catalog.json and visuals_state.json."""
    visuals = load_prompt_visuals()
    new_list = [v for v in visuals if v.get("sid") != sid]
    if len(new_list) != len(visuals):
        save_prompt_visuals(new_list)
        return True
    return False

# =================== BM25 RAG ENGINE ===================
class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.k1 = k1; self.b = b; self.docs = docs; self.N = len(docs)
        self.doc_tokens = [tokenize(d) for d in docs]
        self.df = {}
        self.avgdl = 0
        for tokens in self.doc_tokens:
            self.avgdl += len(tokens)
            for t in set(tokens):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = self.avgdl / self.N if self.N else 1

    def score(self, query):
        from collections import Counter
        q_tokens = tokenize(query)
        scores = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            dl = len(tokens)
            s  = 0.0
            for t in q_tokens:
                if t not in self.df:
                    continue
                idf = math.log((self.N - self.df[t] + 0.5) / (self.df[t] + 0.5) + 1)
                num = tf[t] * (self.k1 + 1)
                den = tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s  += idf * num / den
            scores.append(s)
        return scores

class RAGStore:
    def __init__(self):
        self._kpis = []
        self._bm25 = None

    def build(self, kpis):
        self._kpis = kpis
        docs = []
        for k in kpis:
            text = " ".join(filter(None,[
                k.get("name",""), k.get("description",""), k.get("domain",""),
                k.get("category",""), k.get("metric_column",""),
                k.get("dimension_column",""),
                " ".join(k.get("suggested_prompts",[])),
            ]))
            docs.append(text)
        if docs:
            self._bm25 = BM25(docs, CFG["bm25_k1"], CFG["bm25_b"])

    def search(self, query, top_k=None):
        top_k = top_k or CFG["rag_top_k"]
        if not self._bm25 or not self._kpis:
            return []
        scores = self._bm25.score(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [{**self._kpis[i], "_score": s} for i, s in ranked[:top_k] if s > 0]

    def refresh(self):
        catalog = load_catalog()
        self.build(catalog.get("kpis",[]))

RAG = RAGStore()

def _rag_context(query):
    results = RAG.search(query, top_k=5)
    if not results:
        return ""
    lines = ["KPIs pertinents dans le catalogue:"]
    for r in results:
        lines.append(f"- {r['name']} ({r.get('chart_type','bar')}) | SQL: {r.get('sql_superset','')[:80]}")
    return "\n".join(lines)

# =================== LLM INTEGRATION ===================
def _http_post(url, payload, timeout):
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None

def call_ollama(messages, model=None, json_mode=False):
    model = model or CFG["ollama_model"]
    payload = {"model":model,"messages":messages,"stream":False}
    if json_mode:
        payload["format"] = "json"
    result = _http_post(f"{CFG['ollama_url']}/api/chat", payload, CFG["timeout_llm"])
    if not result:
        return None
    try:
        return result["message"]["content"]
    except Exception:
        return None

def call_gemini(prompt, context=""):
    key = CFG.get("gemini_key")
    if not key:
        return None
    full = f"{context}\n\n{prompt}" if context else prompt
    model = CFG.get("gemini_model","gemini-2.0-flash")
    url   = f"{CFG['gemini_endpoint']}/{model}:generateContent?key={key}"
    payload = {"contents":[{"parts":[{"text":full}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":1024}}
    result = _http_post(url, payload, CFG["timeout_gemini"])
    if not result:
        return None
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None

def call_llm(messages, context="", json_mode=False):
    result = call_ollama(messages, json_mode=json_mode)
    if result:
        return result
    prompt = "\n".join(m.get("content","") for m in messages if m.get("role")=="user")
    gem = call_gemini(prompt, context)
    return gem or ""

def ollama_online():
    try:
        urllib.request.urlopen(f"{CFG['ollama_url']}/api/tags", timeout=2)
        return True
    except Exception:
        return False


# =================== INTENT PARSER ===================
_RE_TOP    = re.compile(r"\btop\s*(\d+)\b", re.I)
_RE_BOTTOM = re.compile(r"\b(?:bottom|pire|moins bon|dernier)\s*(\d+)\b", re.I)
_RE_DELETE = re.compile(r"\b(supprime|efface|retire|enleve|delete|remove)\b", re.I)
_RE_UPDATE = re.compile(r"\b(modifie|change|met a jour|update|ajuste|transforme|convertis)\b", re.I)
_RE_CREATE = re.compile(r"\b(montre|affiche|cree|donne|genere|visualise|chart|graphique|voir)\b", re.I)
_RE_CHART  = re.compile(r"\b(bar|barre|camembert|pie|donut|line|courbe|ligne|carte|card|scatter)\b", re.I)
_CHART_ALIASES = {"barre":"bar","camembert":"pie","donut":"pie","courbe":"line","ligne":"line","carte":"card","nuage":"scatter"}
_STOPWORDS = {"le","la","les","de","du","des","un","une","par","dans","avec","pour","sur","et","ou","en",
              "selon","me","moi","tu","il","je","top","bottom","qui","quel","quelle","quels","quelles",
              "est","sont","show","montre","donne","affiche","voir","cree","genere","me","moi","je"}

def parse_intent(text):
    t = ascii_norm(text.strip())
    action = "create"
    if _RE_DELETE.search(t):  action = "delete"
    elif _RE_UPDATE.search(t): action = "update"
    top_n = CFG["top_n_default"]
    sort  = "DESC"
    m = _RE_TOP.search(t)
    if m:
        top_n = int(m.group(1))
    m = _RE_BOTTOM.search(t)
    if m:
        top_n = int(m.group(1)); sort = "ASC"
    chart_type = None
    m = _RE_CHART.search(text)
    if m:
        chart_type = _CHART_ALIASES.get(m.group(1).lower(), m.group(1).lower())
    keywords = [w for w in tokenize(t) if w not in _STOPWORDS and len(w) > 2]
    return {"action":action,"top_n":top_n,"sort":sort,"chart_type":chart_type,"keywords":keywords,"raw":text}

def build_adhoc_kpi(intent, base_kpi, tables):
    if not tables and not base_kpi:
        return None
    if base_kpi and base_kpi.get("table_name") in tables:
        table_name = base_kpi["table_name"]
        mc = base_kpi.get("metric_column","")
        dc = base_kpi.get("dimension_column","")
        agg = base_kpi.get("aggregation_type","SUM")
    else:
        table_name = list(tables.keys())[0] if tables else ""
        mc, dc, agg = "", "", "SUM"
    if not table_name or table_name not in tables:
        if tables:
            table_name = list(tables.keys())[0]
        else:
            return None
    rows = tables.get(table_name, [])
    if not rows:
        return None
    schema = analyze_schema(rows, list(rows[0].keys()))
    kws = intent["keywords"]
    best_mc, best_dc = mc, dc
    for kw in kws:
        for col in schema["num"]:
            if kw in ascii_norm(col) and not best_mc:
                best_mc = col; break
        for col in schema["cat"] + schema["geo"]:
            if kw in ascii_norm(col) and not best_dc:
                best_dc = col; break
    if not best_mc and schema["num"]:
        best_mc = schema["num"][0]
    if not best_dc and schema["cat"]:
        best_dc = schema["cat"][0]
    chart_type = intent.get("chart_type") or guess_chart_type("cat" if best_dc else "global", guess_kind(best_mc) if best_mc else "measure", 20)
    top_n = intent["top_n"]
    sort  = intent["sort"]
    if best_dc:
        sql = gen_sql_by_dim(table_name, best_mc, best_dc, agg=agg, top_n=top_n, sort=sort)
    elif best_mc:
        sql = gen_sql_aggregate(table_name, best_mc, agg=agg)
        chart_type = "card"
    else:
        return None
    kid  = make_kpi_id(table_name, best_mc or "count", best_dc)
    data = execute_sql(sql)
    label = humanize(table_name)
    return {
        "id": kid, "name": f"{humanize(best_mc or 'Count')} par {humanize(best_dc)}" if best_dc else f"Total {humanize(best_mc)}",
        "domain": label, "category": humanize(best_dc or "Global"),
        "description": f"KPI genere par prompt: {intent['raw']}",
        "source_table": label, "table_name": table_name,
        "aggregation_type": agg, "metric_column": best_mc,
        "dimension_column": best_dc, "chart_type": chart_type,
        "superset_chart_type": "echarts_bar",
        "sql_superset": sql, "raw_value": None, "current_value_formatted": None,
        "suggested_prompts": [intent["raw"]],
        "active": True, "source_file": table_name+".csv", "top_n": top_n,
        "dax_measure": "", "_data": data,
        "api_endpoint": {"method":"GET","path":f"/api/v1/kpi/{slugify(best_mc or 'count').lower()}/adhoc"},
    }

def process_prompt(text, conversation_history=None):
    RAG.refresh()
    intent  = parse_intent(text)
    results = RAG.search(" ".join(intent["keywords"]) or text, top_k=8)
    action  = intent["action"]

    if action == "delete":
        if results:
            kpi = results[0]
            delete_kpi_from_catalog(kpi["id"])
            vid = f"kpi-{kpi['id'].lower().replace('_','-')}"
            delete_visual(vid)
            return {"reply":f"Supprime: **{kpi['name']}** (retire du catalogue et de la page).","deleted":[vid],"kpi_id":kpi["id"],"action":"delete"}
        return {"reply":"Aucun KPI trouve pour la suppression.", "action":"delete"}

    base_kpi = results[0] if results else None

    # Try existing KPI with table data
    if base_kpi and base_kpi.get("sql_superset") and base_kpi.get("table_name") in _tables:
        sql = base_kpi.get("sql_superset","")
        if intent["top_n"] != CFG["top_n_default"] and "LIMIT" in sql.upper():
            sql = re.sub(r"LIMIT\s+\d+", f"LIMIT {intent['top_n']}", sql, flags=re.I)
        if intent["sort"] == "ASC" and "ORDER BY" in sql.upper():
            sql = re.sub(r"ORDER BY (.+?) DESC", r"ORDER BY \1 ASC", sql, flags=re.I)
        data = execute_sql(sql)
        if data:
            vc = kpi_to_visual_config({**base_kpi, "_data":data, "sql_superset":sql})
            if vc:
                if intent.get("chart_type"):
                    vc["chartType"] = intent["chart_type"]
                vc["top_n"] = intent["top_n"]
                upsert_visual(vc)
                base_kpi["active"] = True
                upsert_kpis([base_kpi], base_kpi.get("domain",""))
                flag = "mis a jour" if action=="update" else "cree"
                return {"reply":f"Visuel {flag}: **{vc['title']}** ({vc['chartType']}) top {intent['top_n']}.","created":[vc["id"]],"visual_config":vc,"sql":sql,"action":action}

    # Ad-hoc KPI
    adhoc = build_adhoc_kpi(intent, base_kpi, _tables)
    if adhoc:
        vc = kpi_to_visual_config(adhoc)
        if vc:
            if intent.get("chart_type"):
                vc["chartType"] = intent["chart_type"]
            upsert_visual(vc)
            upsert_kpis([adhoc], adhoc.get("domain",""))
            return {"reply":f"Visuel cree: **{vc['title']}** ({vc['chartType']}) top {intent['top_n']}.","created":[vc["id"]],"visual_config":vc,"sql":adhoc.get("sql_superset",""),"action":"create"}

    # LLM fallback
    rag_ctx = _rag_context(text)
    messages = [
        {"role":"system","content":f"Tu es un assistant BI expert. Reponds en JSON avec: reply, sql, chart_type, title.\n{rag_ctx}"},
        {"role":"user","content":text},
    ]
    llm_raw = call_llm(messages, context=rag_ctx, json_mode=True)
    if llm_raw:
        try:
            out = json.loads(llm_raw)
            return {"reply":out.get("reply","Reponse generee par LLM."),"sql":out.get("sql",""),"action":"create"}
        except Exception:
            return {"reply":llm_raw,"action":"create"}

    return {"reply":"Aucun KPI correspondant trouve. Chargez un fichier de donnees d abord.", "action":"none"}


# =================== MULTIPART PARSER ===================
def _parse_multipart(handler):
    ct = handler.headers.get("Content-Type","")
    if "multipart/form-data" not in ct:
        return None, None, "Content-Type must be multipart/form-data"
    boundary = None
    for p in ct.split(";"):
        p = p.strip()
        if p.startswith("boundary="):
            boundary = p[len("boundary="):].strip()
            break
    if not boundary:
        return None, None, "No boundary found"
    length = int(handler.headers.get("Content-Length",0))
    body   = handler.rfile.read(length)
    b_sep  = f"--{boundary}".encode()
    for part in body.split(b_sep):
        if not part or not b"\r\n\r\n" in part:
            continue
        header_raw, _, content = part.partition(b"\r\n\r\n")
        content = content.rstrip(b"\r\n")
        headers = {}
        for line in header_raw.decode("utf-8","replace").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        cd = headers.get("content-disposition","")
        if 'filename="' in cd:
            m = re.search(r'filename="([^"]+)"', cd)
            if m:
                return m.group(1), content, None
    return None, None, "No file found in request"

# =================== HTTP HELPERS ===================
def _send_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type","application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def _read_json_body(handler):
    length = int(handler.headers.get("Content-Length",0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}

# =================== REST HANDLERS ===================
def _handle_GET(handler, path, params):
    if path == "/api/agent/health":
        _send_json(handler, {
            "status":"ok","version":"6.1",
            "ollama":ollama_online(),"gemini_key":bool(CFG.get("gemini_key")),
            "tables_loaded":list(_tables.keys()),"rag_size":len(RAG._kpis),
        })
        return

    if path == "/api/agent/catalog":
        _send_json(handler, load_catalog())
        return

    if path == "/api/agent/catalog/full":
        RAG.refresh()
        catalog = load_catalog()
        visuals = []
        for kpi in catalog.get("kpis",[]):
            if not kpi.get("active", True):
                continue
            vc = kpi_to_visual_config(kpi)
            if vc:
                visuals.append(vc)
        _send_json(handler, {"kpis":catalog.get("kpis",[]),"visuals":visuals})
        return

    if path == "/api/agent/visuals":
        state = load_visuals()
        enriched = []
        for v in state.get("visuals",[]):
            sql = v.get("sql","")
            if sql and _tables:
                data = execute_sql(sql)
                if data:
                    v = {**v, "data":data}
            enriched.append(v)
        _send_json(handler, {"visuals":enriched})
        return

    # ── Prompt visuals (NL-agent created, restored on reload) ──
    if path == "/api/agent/visuals/prompt":
        visuals = load_prompt_visuals()
        _send_json(handler, {"visuals": visuals, "count": len(visuals)})
        return

    if path == "/api/agent/visuals/seed":
        RAG.refresh()
        catalog = load_catalog()
        seed = []
        # First: try auto_visuals saved in catalog (generated by file upload)
        auto_visuals = catalog.get("auto_visuals", [])
        if auto_visuals:
            # Re-execute SQL to get fresh data for each auto-visual
            for av in auto_visuals:
                sql = av.get("sql", "")
                if sql and _tables:
                    fresh_data = execute_sql(sql)
                    if fresh_data:
                        av = dict(av)
                        av["data"] = fresh_data
                if av.get("data") or av.get("chartType") == "card":
                    seed.append(av)
        # Fallback: rebuild from kpis catalog
        if not seed:
            for kpi in catalog.get("kpis",[]):
                if not kpi.get("active", True):
                    continue
                vc = kpi_to_visual_config(kpi)
                if vc and vc.get("data"):
                    seed.append(vc)
        _send_json(handler, {"visuals":seed,"count":len(seed)})
        return

    if path == "/api/agent/tables":
        info = {t: {"n_rows":len(r),"columns":list(r[0].keys()) if r else []} for t, r in _tables.items()}
        _send_json(handler, {"tables":info})
        return

    m = re.match(r"^/api/agent/kpi/(.+)$", path)
    if m:
        kpi_id = urllib.parse.unquote(m.group(1))
        kpi = get_kpi(kpi_id)
        if not kpi:
            _send_json(handler, {"error":"KPI not found"}, 404); return
        vc = kpi_to_visual_config(kpi)
        _send_json(handler, {"kpi":kpi,"visual":vc})
        return

    if path == "/api/agent/dashboard-bg":
        catalog = load_catalog()
        bg = catalog.get("metadata", {}).get("dashboard_background", "")
        _send_json(handler, {"background": bg})
        return

    _send_json(handler, {"error":f"Unknown endpoint: {path}"}, 404)


def _handle_POST(handler, path):
    if path == "/api/agent/upload":
        fname, content, err = _parse_multipart(handler)
        if err or not content:
            _send_json(handler, {"success":False,"error":err or "No file"}, 400); return
        upload_dir = Path(CFG["upload_dir"])
        upload_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^\w\.\-]", "_", fname)
        file_path  = upload_dir / safe_name
        file_path.write_bytes(content)
        try:
            info = ingest_file(str(file_path))
        except Exception as e:
            _send_json(handler, {"success":False,"error":str(e)}, 500); return
        kpis = extract_kpis(info)
        RAG.refresh()
        visuals = []
        for kpi in kpis:
            vc = kpi_to_visual_config(kpi)
            if vc and vc.get("data"):
                visuals.append(vc)
        # Save auto-visuals to catalog (stripped of heavy data, re-fetched via SQL on reload)
        auto_visuals_for_catalog = []
        for vc in visuals:
            save_vc = {k: v for k, v in vc.items() if k != "data"}
            save_vc["sql"] = vc.get("sql", "")
            auto_visuals_for_catalog.append(save_vc)
        replace_catalog_from_upload(kpis, info, auto_visuals=auto_visuals_for_catalog)
        save_visuals({"visuals": visuals})
        _send_json(handler, {
            "success": True,
            "filename": fname,
            "table_name": info["table_name"],
            "n_rows": info["n_rows"],
            "columns": info["columns"],
            "n_kpis": len(kpis),
            "kpis": kpis,
            "visuals": visuals,
            "rows": info["rows"][:300]
        })
        return

    if path == "/api/agent/prompt":
        body = _read_json_body(handler)
        text = body.get("prompt") or body.get("text","")
        if not text:
            _send_json(handler, {"error":"No prompt provided"}, 400); return
        response = process_prompt(text, body.get("history",[]))
        _send_json(handler, response)
        return

    if path == "/api/agent/catalog/update":
        body = _read_json_body(handler)
        kpi  = body.get("kpi")
        if not kpi or not kpi.get("id"):
            _send_json(handler, {"error":"Invalid KPI data"}, 400); return
        upsert_kpis([kpi], kpi.get("domain",""))
        RAG.refresh()
        _send_json(handler, {"success":True,"id":kpi["id"]})
        return

    if path == "/api/agent/visuals":
        body = _read_json_body(handler)
        vis  = body.get("visual")
        if not vis:
            _send_json(handler, {"error":"No visual provided"}, 400); return
        upsert_visual(vis)
        _send_json(handler, {"success":True,"id":vis.get("id")})
        return

    # ── Prompt visuals persistence (created by NL agent) ──
    if path == "/api/agent/visuals/prompt":
        body = _read_json_body(handler)
        entry = body.get("visual")
        if not entry or not entry.get("sid"):
            _send_json(handler, {"error":"No visual entry or missing sid"}, 400); return
        upsert_prompt_visual(entry)
        _send_json(handler, {"success":True, "sid": entry["sid"]})
        return

    # ── Batch save all prompt visuals (full state sync) ──
    if path == "/api/agent/visuals/prompt/batch":
        body = _read_json_body(handler)
        visuals = body.get("visuals", [])
        save_prompt_visuals(visuals)
        _send_json(handler, {"success":True, "count": len(visuals)})
        return

    if path == "/api/agent/gemini-key":
        body = _read_json_body(handler)
        key  = body.get("key","").strip()
        if not key:
            _send_json(handler, {"error":"No key provided"}, 400); return
        CFG["gemini_key"] = key
        _send_json(handler, {"success":True,"message":"Cle Gemini configuree."})
        return

    if path == "/api/agent/execute-sql":
        body = _read_json_body(handler)
        sql  = body.get("sql","")
        if not sql:
            _send_json(handler, {"error":"No SQL provided"}, 400); return
        rows = execute_sql(sql)
        _send_json(handler, {"rows":rows,"count":len(rows)})
        return
    if path == "/api/agent/detect-filter":
        body = _read_json_body(handler)
        _send_json(handler, {"filter": detect_filter(body.get("text", ""))})
        return
    # ── [v6.1] Filtre global : re-execute la SQL d'un visuel avec un WHERE col IN (...) ──
    if path == "/api/agent/filter-sql":
        body = _read_json_body(handler)
        new_sql = inject_where(body.get("sql", ""), body.get("filters", []))
        if not new_sql:
            _send_json(handler, {"applicable": False, "rows": []})
            return
        rows = execute_sql(new_sql)
        _send_json(handler, {"applicable": True, "sql": new_sql, "rows": rows, "count": len(rows)})
        return

    if path == "/api/agent/dashboard-bg":
        body = _read_json_body(handler)
        bg = body.get("background", "")
        if bg:
            catalog = load_catalog()
            catalog.setdefault("metadata", {})["dashboard_background"] = bg
            catalog["metadata"]["last_updated"] = datetime.now().isoformat()
            save_catalog(catalog)
        _send_json(handler, {"success": True, "background": bg})
        return

    _send_json(handler, {"error":f"Unknown POST endpoint: {path}"}, 404)


def _handle_DELETE(handler, path):
    m = re.match(r"^/api/agent/catalog/(.+)$", path)
    if m:
        kpi_id = urllib.parse.unquote(m.group(1))
        ok = delete_kpi_from_catalog(kpi_id)
        vid = f"kpi-{kpi_id.lower().replace('_','-')}"
        delete_visual(vid)
        RAG.refresh()
        _send_json(handler, {"success":ok,"deleted_id":kpi_id})
        return
    # ── Delete prompt visual by sid ──
    m = re.match(r"^/api/agent/visuals/prompt/(.+)$", path)
    if m:
        sid = urllib.parse.unquote(m.group(1))
        ok = delete_prompt_visual(sid)
        _send_json(handler, {"success":ok, "deleted_sid": sid})
        return
    m = re.match(r"^/api/agent/visuals/(.+)$", path)
    if m:
        vid = urllib.parse.unquote(m.group(1))
        delete_visual(vid)
        _send_json(handler, {"success":True,"deleted_id":vid})
        return
    _send_json(handler, {"error":f"Unknown DELETE endpoint: {path}"}, 404)


def handle_request(handler, method):
    parsed = urllib.parse.urlparse(handler.path)
    path   = parsed.path.rstrip("/") or "/"
    params = dict(urllib.parse.parse_qsl(parsed.query))
    try:
        if method == "GET":      _handle_GET(handler, path, params)
        elif method == "POST":   _handle_POST(handler, path)
        elif method == "DELETE": _handle_DELETE(handler, path)
        else:
            _send_json(handler, {"error":f"Method {method} not allowed"}, 405)
    except Exception:
        tb = traceback.format_exc()
        print(f"[agent.py] Error in {method} {path}:\n{tb}")
        _send_json(handler, {"error":"Internal server error","detail":tb[-500:]}, 500)


# =================== REGISTER (patch NoCacheHandler) ===================
def register(handler_class):
    """
    Monkey-patch an HTTP handler class to add /api/agent/* routes.
    Call this once in start_server.py BEFORE creating HTTPServer.

    Example:
        import agent as BI_AGENT
        BI_AGENT.register(NoCacheHandler)
        server = HTTPServer(("0.0.0.0", 8080), NoCacheHandler)
    """
    original_GET  = handler_class.do_GET
    original_POST = handler_class.do_POST

    def patched_GET(self):
        if self.path.split("?")[0].rstrip("/").startswith("/api/agent"):
            handle_request(self, "GET")
        else:
            original_GET(self)

    def patched_POST(self):
        if self.path.split("?")[0].rstrip("/").startswith("/api/agent"):
            handle_request(self, "POST")
        else:
            original_POST(self)

    def patched_DELETE(self):
        if self.path.split("?")[0].rstrip("/").startswith("/api/agent"):
            handle_request(self, "DELETE")
        else:
            _send_json(self, {"error":"Not found"}, 404)

    def patched_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization")
        self.end_headers()

    handler_class.do_GET     = patched_GET
    handler_class.do_POST    = patched_POST
    handler_class.do_DELETE  = patched_DELETE
    handler_class.do_OPTIONS = patched_OPTIONS

    # Build RAG from existing catalog
    RAG.refresh()

    # Pre-load files in uploads/ and root datasets
    candidate_paths = []
    upload_dir = Path(CFG["upload_dir"])
    if upload_dir.exists():
        candidate_paths.extend(sorted(upload_dir.iterdir()))
    for default_fname in ["pwc_clients_analysis_clean.xlsx", "pwc_events_clean.xlsx", "world_economics_clean.xlsx"]:
        dfp = Path(default_fname)
        if dfp.exists():
            candidate_paths.append(dfp)

    loaded_names = set()
    for fp in candidate_paths:
        if fp.name in loaded_names:
            continue
        if fp.suffix.lower() in (".csv",".xlsx",".xls"):
            try:
                info = ingest_file(str(fp))
                loaded_names.add(fp.name)
                print(f"[agent.py] Pre-loaded: {fp.name} ({info['n_rows']} rows, table: {info['table_name']})")
            except Exception as e:
                print(f"[agent.py] Warning: could not pre-load {fp.name}: {e}")

    print(f"[agent.py] BI Agent v6.1 registered.")
    print(f"[agent.py] Tables: {list(_tables.keys()) or ['none']}")
    print(f"[agent.py] Catalog KPIs: {len(RAG._kpis)} | Ollama: {'online' if ollama_online() else 'offline'}")
    print(f"[agent.py] Endpoints: /api/agent/health | /api/agent/upload | /api/agent/prompt | /api/agent/catalog/full | /api/agent/filter-sql")

# =================== STANDALONE MODE ===================
if __name__ == "__main__":
    import argparse
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    ap = argparse.ArgumentParser(description="BI Agent v6.1 Standalone")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--gemini-key", default="")
    args = ap.parse_args()

    if args.gemini_key:
        CFG["gemini_key"] = args.gemini_key

    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    class AgentHandler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Access-Control-Allow-Methods","GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers","Content-Type")
            super().end_headers()
        def log_message(self, fmt, *args):
            pass

    register(AgentHandler)

    server = HTTPServer(("0.0.0.0", args.port), AgentHandler)
    print(f"\n{'='*50}")
    print(f"  BI Agent v6.1 - Standalone Server")
    print(f"  URL : http://localhost:{args.port}")
    print(f"  API : http://localhost:{args.port}/api/agent/health")
    print(f"{'='*50}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[agent.py] Stopped.")
        server.shutdown()