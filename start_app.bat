@echo off
title PUVA EVAL-CORE Launcher
echo ========================================================
echo   PUVA EVAL-CORE (Bank Indonesia DU Quarterly Evaluation)
echo ========================================================
echo.
echo [1/2] Menjalankan Backend FastAPI (Port 8000)...
start "PUVA EVAL-CORE - Backend API" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

echo [2/2] Menjalankan Frontend Next.js (Port 3000)...
start "PUVA EVAL-CORE - Frontend Web" cmd /k "cd /d "%~dp0frontend" && npm run start -- -H 0.0.0.0 -p 3000"

echo.
echo Aplikasi sedang dijalankan!
echo - Akses Lokal: http://localhost:3000
echo - Swagger API: http://localhost:8000/docs
echo.
echo Jendela ini dapat ditutup.
pause
