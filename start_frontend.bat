@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PATH=C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts;C:\Users\DELL\AppData\Local\Programs\Python\Python311;%PATH%"

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

echo =========================================================================
echo  BI-Flow - Plateforme Multi-Agents LangGraph et Visualisation Executive
echo =========================================================================
echo  [1/2] Demarrage du serveur LangGraph Studio Dev (Port 2024)...
start "LangGraph Dev" /B "C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts\langgraph.exe" dev --port 2024 --no-browser

echo  [2/2] Demarrage du serveur Web et API FastAPI (Port 8000)...
echo -------------------------------------------------------------------------
echo  URL Principale : http://127.0.0.1:8000
echo  LangGraph API  : http://127.0.0.1:2024
echo  LangSmith UI   : https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo =========================================================================
"C:\Users\DELL\AppData\Local\Programs\Python\Python311\python.exe" -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000
pause
