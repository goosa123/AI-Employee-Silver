@echo off
cd /d "%~dp0.."

REM Use the Python on PATH (works with any venv or system Python)
pythonw watchers\launcher.py

exit /b 0
