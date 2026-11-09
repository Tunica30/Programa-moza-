@echo off
cd /d "%~dp0"
call "%~dp0_buscar_python.bat" || exit /b 1
echo Usando: %PY%
%PY% --version
echo Instalando dependencias de MOZA Bridge...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Hubo un error instalando las dependencias. Mandale una foto de esta ventana a Claude.
  pause
  exit /b 1
)
echo.
echo Si es la primera vez, vgamepad abre el instalador de ViGEmBus: aceptalo.
echo Listo. Ahora ejecuta diagnostico.bat o iniciar.bat
pause
