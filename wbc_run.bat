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
start http://localhost:5000/game/new

python app.py

echo.
echo =====================================================
echo  Server stopped. Press any key to exit.
echo =====================================================
pause
