@echo off
REM Instala las dependencias si faltan (se llama desde los otros .bat).
%PY% -c "import pygame" >nul 2>nul
if not errorlevel 1 exit /b 0
echo Falta instalar las librerias. Instalando (solo la primera vez)...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%~dp0requirements.txt"
%PY% -c "import pygame" >nul 2>nul
if errorlevel 1 (
  echo.
  echo No se pudieron instalar las librerias. Mandale una foto de esta ventana a Claude.
  pause
  exit /b 1
)
exit /b 0
