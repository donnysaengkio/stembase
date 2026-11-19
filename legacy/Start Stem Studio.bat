@echo off
title Stem Studio
cd /d "%~dp0"
echo Starting Stem Studio... your browser will open at http://127.0.0.1:7860
echo Keep this window open while you use the app. Close it to stop.
python app.py
if errorlevel 1 (
  echo.
  echo Stem Studio stopped with an error. If packages are missing, run "Install requirements.bat".
  pause
)
