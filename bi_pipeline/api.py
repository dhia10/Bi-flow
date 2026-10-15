from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd

from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent
from bi_pipeline.schemas.state_schema import PipelineRunOutput

app = FastAPI(
    title="Bi-flow Multi-Agent API for n8n",
    description="REST API bridging local n8n workflows with Agent 5 (DuckDB) and Agent 6 (Analyst)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent5 = BISemanticKPIAgent()
agent6 = BIAnalystAgent()


class AnalyzePathRequest(BaseModel):
    file_path: Optional[str] = None
    dataset_name: str = "Enterprise Dataset"
    domain_hint: Optional[str] = None


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "bi-flow-n8n-bridge", "version": "1.0.0"}


@app.post("/api/analyze/file")
async def analyze_uploaded_file(file: UploadFile = File(...), dataset_name: str = "Uploaded Dataset") -> Dict[str, Any]:
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        sem = agent5.analyze(df, dataset_name=dataset_name)
        ana = agent6.analyze(sem)
        output = PipelineRunOutput(
            semantic_state=sem,
            analyst_state=ana,
            total_execution_time_ms=sem.execution_time_ms + 10.0,
        )
        return output.model_dump(mode="json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze")
def analyze_path(req: AnalyzePathRequest) -> Dict[str, Any]:
    try:
        if req.file_path and Path(req.file_path).is_file():
            p = Path(req.file_path)
        else:
            p = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"

        df = pd.read_csv(p)
        sem = agent5.analyze(df, dataset_name=req.dataset_name, domain_hint=req.domain_hint)
        ana = agent6.analyze(sem)
        output = PipelineRunOutput(
            semantic_state=sem,
            analyst_state=ana,
            total_execution_time_ms=sem.execution_time_ms + 10.0,
        )
        return output.model_dump(mode="json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
