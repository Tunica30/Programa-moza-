@echo off
cd /d "%~dp0"
call "%~dp0_buscar_python.bat" || exit /b 1
%PY% -m moza_bridge --perfil nfs_heat
if errorlevel 1 pause
