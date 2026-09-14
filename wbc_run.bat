@echo off
cd /d "%~dp0"
title WBC Screen Baseball Management

echo =====================================================
echo    W.B.C Screen Baseball Management System
echo    World Believers Club
echo =====================================================
echo.

python -m pip install -r requirements.txt -q

echo Starting Web Application...
python -c "import subprocess; [subprocess.run(['taskkill', '/F', '/PID', l.split()[-1]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for l in subprocess.getoutput('netstat -ano').splitlines() if ':5000 ' in l and 'LISTENING' in l]"
start http://localhost:5000

python app.py

echo.
echo =====================================================
echo  Server stopped. Press any key to exit.
echo =====================================================
pause
