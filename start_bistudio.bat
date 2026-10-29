@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo =========================================================================
echo  BI Studio & AI Copilot - Visualisations Superset et Mesures DAX
echo =========================================================================
echo  Synchronisation des KPIs et du Dataset actif depuis le workflow LangGraph...
py -3.11 generator\workflow_bridge.py
echo -------------------------------------------------------------------------
echo  URL Principale : http://localhost:8085
echo =========================================================================
cd generator
py -3.11 start_server.py --port 8085
