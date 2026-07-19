@echo off
REM Lineage Detective — one-click setup + launch for Windows. Double-click this file.
title Lineage Detective
cd /d "%~dp0"
where py >nul 2>nul && (py quickstart.py) || (python quickstart.py)
echo.
echo (window stays open so you can read any messages above)
pause
