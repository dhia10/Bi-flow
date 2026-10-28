"""Optional FastAPI endpoints. Runs persist their outputs; no temporary deleted reports."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import FastAPI,UploadFile,File,Query,HTTPException
from etl_agent import ETLAgent
app=FastAPI(title='BI-FLOW Intelligent ETL Agent',version='3.0')
@app.get('/health')
def health():return {'status':'ok','agent':'intelligent_etl_agent'}
@app.post('/etl/run-demo')
def run_demo(use_llm:bool=Query(True),schema:str=Query('star',pattern='^(star|snowflake|auto)$')):
    try:return ETLAgent(use_llm,schema=schema).run('data/input',Path('data/output')/'api_demo')
    except Exception as exc:raise HTTPException(status_code=422,detail=str(exc))
@app.post('/etl/run')
async def run_etl(files:list[UploadFile]=File(...),use_llm:bool=Query(True),schema:str=Query('star',pattern='^(star|snowflake|auto)$')):
    run_id=uuid4().hex[:12]
    with TemporaryDirectory() as d:
        inp=Path(d)
        for f in files:
            filename=Path(f.filename or '').name
            if filename in ('','.','..') or Path(filename).suffix.lower() not in ('.csv','.json','.xlsx'):
                raise HTTPException(status_code=400,detail='Expected CSV/XLSX/JSON files')
            blob=await f.read()
            if len(blob)>40_000_000:raise HTTPException(status_code=413,detail='Single file exceeds 40 MB API limit; use CLI')
            (inp/filename).write_bytes(blob)
        try:return ETLAgent(use_llm,schema=schema).run(inp,Path('data/output')/'api_runs'/run_id)
        except Exception as exc:raise HTTPException(status_code=422,detail=str(exc))
