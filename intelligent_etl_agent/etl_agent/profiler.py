"""Bounded, format-aware profiling with semantic types; never feeds full rows to an LLM."""
from __future__ import annotations
import json
import re
from pathlib import Path
import pandas as pd
from .relationships import infer_relationships

KEY_WORDS = {'id', 'key', 'code', 'ref', 'uuid', 'identifier', 'tracking_no'}
DURATION_WORDS = {'days', 'hours', 'minutes', 'seconds', 'nights', 'duration', 'elapsed', 'age', 'lead_time'}
DATE_WORDS = {'date', 'timestamp', 'datetime', 'created_at', 'updated_at', 'dispatched_on', 'ordered_at', 'start_date', 'end_date', 'checkin', 'checkout', 'departure', 'arrival'}

def _tokens(s: str) -> set[str]:
    return set(filter(None, re.split(r'[^a-z0-9]+', s.lower())))

def _date_ratio(series: pd.Series, name: str) -> float:
    if pd.api.types.is_datetime64_any_dtype(series):return 1.0
    if pd.api.types.is_numeric_dtype(series):return 0.0
    low = name.lower(); tok = _tokens(name)
    if tok & DURATION_WORDS and not (tok & {'date', 'timestamp', 'datetime'}):return 0.0
    v = series.dropna().astype(str).head(100)
    if v.empty:return 0.0
    iso = v.str.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]|$)').mean()
    hint = low in DATE_WORDS or any(k in low for k in ('_date','date_','timestamp','_at','checkin','checkout','dispatched','departure'))
    if not hint and iso < .8:return 0.0
    if iso < .5 and not hint:return 0.0
    return round(float(pd.to_datetime(v, errors='coerce').notna().mean()),4)

def semantic_type(name: str, series: pd.Series, date_ratio: float) -> str:
    tok = _tokens(name); low = name.lower()
    if tok & DURATION_WORDS and not (tok & {'date', 'timestamp'}):return 'duration'
    if date_ratio >= .8:return 'date'
    if low in ('date','time') and date_ratio >= .5:return 'date'
    if tok & KEY_WORDS or low.endswith(('_id','_code','_ref','_key')):return 'identifier'
    if pd.api.types.is_numeric_dtype(series):
        if any(x in low for x in ('rate','per_','price','cost','fee','tariff')):return 'rate_or_money'
        if any(x in low for x in ('qty','quantity','count','units','weight','kwh','usage','amount','total','volume')):return 'measure'
        return 'numeric'
    return 'categorical_or_text'

def profile_dataframe(name: str, df: pd.DataFrame) -> dict:
    cols=[]
    for col in df.columns:
        series=df[col]; non_null=series.dropna();ratio=_date_ratio(series,str(col))
        meta={'name':str(col),'dtype':str(series.dtype),'semantic_type':semantic_type(str(col),series,ratio),
              'null_count':int(series.isna().sum()),'null_ratio':round(float(series.isna().mean()),4) if len(series) else 0,
              'unique_count':int(series.nunique(dropna=True)),
              'unique_ratio':round(float(series.nunique(dropna=True)/max(1,len(non_null))),4),
              'date_parse_ratio':ratio,
              'sample_values':[str(x)[:90] for x in non_null.astype(str).drop_duplicates().head(4)]}
        if pd.api.types.is_numeric_dtype(series) and len(non_null):
            meta['statistics']={'min':float(non_null.min()),'max':float(non_null.max()),'mean':round(float(non_null.mean()),3)}
        cols.append(meta)
    return {'table':name,'rows':len(df),'columns_count':len(df.columns),
            'duplicate_rows':int(df.duplicated().sum()),'columns':cols}

def load_data_directory(input_dir: str|Path) -> dict[str,pd.DataFrame]:
    folder=Path(input_dir)
    if not folder.is_dir():raise FileNotFoundError(f'Input folder not found: {folder}')
    paths=sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.csv','.xlsx','.json'))
    if not paths:raise FileNotFoundError(f'No CSV, XLSX or JSON files in {folder}')
    frames={}
    for path in paths:
        if path.suffix.lower()=='.csv':df=pd.read_csv(path,low_memory=False)
        elif path.suffix.lower()=='.xlsx':df=pd.read_excel(path)
        else:
            obj=json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(obj,list):df=pd.json_normalize(obj)
            elif isinstance(obj,dict) and isinstance(obj.get('records'),list):df=pd.json_normalize(obj['records'])
            else:raise ValueError(f'{path.name}: JSON must be an array or a records array')
        if df.empty:raise ValueError(f'{path.name}: input contains zero rows')
        if not df.columns.is_unique:raise ValueError(f'{path.name}: duplicate column names')
        if any(not isinstance(c,str) or not c.strip() for c in df.columns):raise ValueError(f'{path.name}: invalid column name')
        if path.stem in frames:raise ValueError(f'Conflicting input table name {path.stem} across file extensions')
        frames[path.stem]=df
    return frames

load_csv_directory=load_data_directory  # back-compat

def build_profile(frames: dict[str,pd.DataFrame]) -> dict:
    meta={n:profile_dataframe(n,df) for n,df in frames.items()}
    return {'table_count':len(frames),'tables':meta,'relationship_candidates':infer_relationships(frames)}
