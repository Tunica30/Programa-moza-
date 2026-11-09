@echo off
cd /d "%~dp0"
call "%~dp0_buscar_python.bat" || exit /b 1
call "%~dp0_dependencias.bat" || exit /b 1
%PY% -m moza_bridge --listar > diagnostico.txt 2>&1
type diagnostico.txt
echo.
echo Se guardo en diagnostico.txt
pause
