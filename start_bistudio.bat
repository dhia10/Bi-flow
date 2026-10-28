@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo =========================================================================
echo  BI Studio & AI Copilot - Visualisations Superset et Mesures DAX
echo =========================================================================
echo  URL Principale : http://localhost:8085
echo =========================================================================
cd generator
py -3.11 start_server.py --port 8085
