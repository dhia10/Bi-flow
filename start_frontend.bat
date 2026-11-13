@echo off
setlocal enabledelayedexpansion

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=C:\Users\DELL\AppData\Local\Programs\Python\Python311\python.exe"
set "LANGGRAPH_EXE=C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts\langgraph.exe"

echo =========================================================================
echo  BI-Flow - LangGraph Multi-Agents et Visualisation Executive
echo =========================================================================

echo  [1/2] Demarrage du serveur LangGraph Studio Dev (Port 2024)...
start "LangGraph Dev 2024" "%LANGGRAPH_EXE%" dev --port 2024 --host 127.0.0.1 --no-browser

echo  Attente de 3 secondes pour l initialisation de LangGraph Dev...
timeout /t 3 /nobreak >nul

echo  [2/2] Demarrage du serveur FastAPI (Port 8000)...
echo -------------------------------------------------------------------------
echo  URL Principale : http://127.0.0.1:8000
echo  Studio BI      : http://127.0.0.1:8000/studio
echo  LangGraph API  : http://127.0.0.1:2024
echo  LangSmith UI   : https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo =========================================================================
"%PYTHON_EXE%" -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000
pause
