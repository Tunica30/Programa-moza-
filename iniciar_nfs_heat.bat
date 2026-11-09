@echo off
cd /d "%~dp0"
python -m moza_bridge --perfil nfs_heat
if errorlevel 1 pause
