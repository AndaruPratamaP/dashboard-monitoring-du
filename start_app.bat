@echo off
title PUVA EVAL-CORE Launcher
echo ========================================================
echo   PUVA EVAL-CORE (Bank Indonesia DU Quarterly Evaluation)
echo ========================================================
echo.
if /I "%~1"=="demo" (
  echo [demo] Database demo baru: backend\demo.db ^(puva_eval.db tidak tersentuh^)
  del /q "%~dp0backend\demo.db" "%~dp0backend\demo.db-wal" "%~dp0backend\demo.db-shm" 2>nul
  set "DATABASE_PATH=%~dp0backend\demo.db"
)

echo [1/2] Menjalankan Backend FastAPI (Port 8000)...
start "PUVA EVAL-CORE - Backend API" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

echo [2/2] Menjalankan Frontend Next.js Dev Mode (Port 3000)...
start "PUVA EVAL-CORE - Frontend Web" cmd /k "cd /d "%~dp0frontend" && npm run dev -- -H 0.0.0.0 -p 3000"

echo.
echo Aplikasi sedang dijalankan!
echo - Akses Lokal: http://localhost:3000
echo - Swagger API: http://localhost:8000/docs
echo.
echo Jendela ini dapat ditutup.
pause
