@echo off
set PYTHONIOENCODING=utf-8
set "PATH=C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts;C:\Users\DELL\AppData\Local\Programs\Python\Python311;%PATH%"

echo =========================================================================
echo  BI-Flow - Interface Web LangGraph Multi-Agents (7 Noeuds)
echo =========================================================================
echo  URL Principale : http://127.0.0.1:8000
echo  Documentation  : http://127.0.0.1:8000/docs
echo =========================================================================
py -3.11 -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000
pause
