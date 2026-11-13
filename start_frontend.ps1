# BI-Flow - Lanceur PowerShell Haute Fiabilite
$ErrorActionPreference = "Continue"

$pythonExe = "C:\Users\DELL\AppData\Local\Programs\Python\Python311\python.exe"
$langgraphExe = "C:\Users\DELL\AppData\Local\Programs\Python\Python311\Scripts\langgraph.exe"

Write-Host "=========================================================================" -ForegroundColor Cyan
Write-Host " BI-Flow - LangGraph Multi-Agents et Visualisation Executive" -ForegroundColor Cyan
Write-Host "=========================================================================" -ForegroundColor Cyan

# 1. Demarrage du serveur LangGraph Studio Dev (Port 2024)
Write-Host "[1/2] Demarrage du serveur LangGraph Studio Dev (Port 2024)..." -ForegroundColor Yellow
$langgraphProcess = Start-Process -FilePath $langgraphExe -ArgumentList "dev --port 2024 --host 127.0.0.1 --no-browser" -PassThru -WindowStyle Minimized

Start-Sleep -Seconds 3

# Verification du port 2024
$port2024Check = Test-NetConnection -ComputerName 127.0.0.1 -Port 2024 -InformationLevel Quiet
if ($port2024Check) {
    Write-Host "      LangGraph Dev est actif sur http://127.0.0.1:2024 (Statut: OK)" -ForegroundColor Green
} else {
    Write-Host "      Attente de disponibilite sur le port 2024..." -ForegroundColor Yellow
}

# 2. Demarrage du serveur FastAPI (Port 8000)
Write-Host "[2/2] Demarrage du serveur Web et API FastAPI (Port 8000)..." -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------------"
Write-Host " URL Principale : http://127.0.0.1:8000" -ForegroundColor White
Write-Host " Studio BI      : http://127.0.0.1:8000/studio" -ForegroundColor White
Write-Host " LangGraph API  : http://127.0.0.1:2024" -ForegroundColor White
Write-Host " LangSmith UI   : https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024" -ForegroundColor White
Write-Host "=========================================================================" -ForegroundColor Cyan

& $pythonExe -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8000
