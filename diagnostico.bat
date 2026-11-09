@echo off
cd /d "%~dp0"
python -m moza_bridge --listar > diagnostico.txt
type diagnostico.txt
echo.
echo Se guardo en diagnostico.txt
pause
