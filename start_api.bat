@echo off
echo ===================================================
echo     Demarrage de l'API FastAPI Bi-Flow (Port 8000)
echo ===================================================
echo Documentation Swagger : http://127.0.0.1:8000/docs
echo.
python -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000 --reload
