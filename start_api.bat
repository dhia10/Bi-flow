@echo off
echo ===================================================
echo     Demarrage du Dashboard Executif Bi-Flow (Port 8000)
echo ===================================================
echo Tableau de Bord Interactif : http://127.0.0.1:8000/
echo Documentation OpenAPI/Docs : http://127.0.0.1:8000/docs
echo.
echo Ouverture automatique de votre navigateur...
start http://127.0.0.1:8000/
echo Lancement du serveur uvicorn FastAPI...
python -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000 --reload
