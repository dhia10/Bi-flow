@echo off
set PYTHONIOENCODING=utf-8
set "PATH=C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts;C:\Users\DELL\AppData\Local\Programs\Python\Python311;%PATH%"

:: Load environment variables from .env if present
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

echo =========================================================================
echo  BI-Flow - LangGraph Studio Dev Server ^& LangSmith Tracing
echo =========================================================================
echo  Python     : 3.11.9
echo  Graph      : bi_flow (./Orchestrator/orchestrator/orchestrator.py:graph)
echo  Config     : langgraph.json
echo  LangSmith  : %LANGSMITH_TRACING% (Project: %LANGSMITH_PROJECT%)
echo  Local API  : http://127.0.0.1:2024
echo  Studio UI  : https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo =========================================================================
"C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts\langgraph.exe" dev --port 2024
pause
