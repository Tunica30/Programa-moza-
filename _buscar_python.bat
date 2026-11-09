@echo off
REM Busca un Python que funcione y lo deja en la variable PY.
REM Prueba primero "py" (instalador de python.org) y despues "python".
REM El acceso directo de la Microsoft Store falla con --version, asi que se descarta.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (py --version >nul 2>nul && set "PY=py")
if not defined PY (python --version >nul 2>nul && set "PY=python")
if not defined PY (
  echo.
  echo No se encontro Python instalado.
  echo  1. Abri una consola ^(tecla Windows, escribi cmd, Enter^) y ejecuta:  py install default
  echo     o instala Python desde https://www.python.org/downloads/
  echo  2. En Configuracion ^> Aplicaciones ^> Configuracion avanzada de aplicaciones ^>
  echo     Alias de ejecucion de aplicaciones: DESACTIVA "Instalador de aplicacion python.exe"
  echo     y "python3.exe", y ACTIVA los de "Python".
  echo  3. Cerra esta ventana y volve a intentar.
  echo.
  pause
  exit /b 1
)
exit /b 0
