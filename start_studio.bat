@echo off
set PYTHONIOENCODING=utf-8
echo =========================================================================
echo  BI-Flow - LangGraph Studio Dev Server
echo =========================================================================
echo  Graph : bi_flow (./Orchestrator/orchestrator/orchestrator.py:graph)
echo  Config: langgraph.json
echo  Local API: http://127.0.0.1:2024
echo  Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo =========================================================================
langgraph dev --port 2024
pause
