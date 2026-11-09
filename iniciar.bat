@echo off
REM Doble clic para abrir MOZA Bridge con el perfil general.
REM Para NFS Heat usá iniciar_nfs_heat.bat
cd /d "%~dp0"
python -m moza_bridge --perfil general
if errorlevel 1 pause
