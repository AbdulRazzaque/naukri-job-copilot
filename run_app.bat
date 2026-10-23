@echo off
echo ===================================================
echo Starting Naukri AI Job Copilot Full-Stack System
echo Location: E:\Private work\naukri-job-copilot
echo ===================================================

echo [1/3] Ensuring MySQL is running...
start /B "" "C:\xampp\mysql\bin\mysqld.exe"

echo [2/3] Starting Python FastAPI Backend on port 8000...
start "Naukri Backend (FastAPI)" cmd /k "cd /d E:\Private work\naukri-job-copilot\backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

echo [3/3] Starting Next.js Frontend Dashboard on port 3000...
start "Naukri Frontend (Next.js)" cmd /k "cd /d E:\Private work\naukri-job-copilot\frontend && npm run dev"

echo.
echo ===================================================
echo Done! Opening Dashboard in 3 seconds...
echo Dashboard URL: http://localhost:3000
echo ===================================================
timeout /t 3 >nul
start http://localhost:3000
