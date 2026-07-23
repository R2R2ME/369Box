@echo off
REM Launch 369box (prefer "Run as administrator" for write protection)
cd /d "%~dp0"
python main.py
if errorlevel 1 pause
