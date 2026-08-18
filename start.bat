@echo off
rem Launch the quota monitor widget without a console window.
rem Requires Python 3 on PATH (standard library only).
set "PY=pythonw.exe"
where pythonw.exe >nul 2>nul || set "PY=python.exe"
start "" "%PY%" "%~dp0quota_monitor.py"
