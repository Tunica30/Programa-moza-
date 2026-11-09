@echo off
cd /d "%~dp0"
echo Instalando dependencias de MOZA Bridge...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Si es la primera vez, vgamepad abre el instalador de ViGEmBus: aceptalo.
echo Listo. Ahora ejecuta iniciar.bat
pause
