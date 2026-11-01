@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PATH=C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts;C:\Users\DELL\AppData\Local\Programs\Python\Python311;%PATH%"

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

echo =========================================================================
echo  🚀 BI-Flow - Plateforme Multi-Agents LangGraph & Visualisation Executive
echo =========================================================================
echo  [1/2] Démarrage du serveur LangGraph Studio Dev (Port 2024)...
start /B "" "C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts\langgraph.exe" dev --port 2024 >nul 2>&1

echo  [2/2] Démarrage du serveur Web & API FastAPI (Port 8000)...
echo -------------------------------------------------------------------------
echo  URL Principale : http://127.0.0.1:8000
echo  LangGraph API  : http://127.0.0.1:2024
echo  LangSmith UI   : https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo =========================================================================
py -3.11 -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000
pause
