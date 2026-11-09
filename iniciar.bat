@echo off
REM Doble clic para abrir MOZA Bridge con el perfil general.
REM Para NFS Heat usa iniciar_nfs_heat.bat
cd /d "%~dp0"
call "%~dp0_buscar_python.bat" || exit /b 1
%PY% -m moza_bridge --perfil general
if errorlevel 1 pause
