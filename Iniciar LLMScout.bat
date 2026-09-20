@echo off
rem LLM Scout - lanza el panel sin ventana de consola
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  call :lanzar pythonw
) else (
  call :lanzar python
)
exit /b

:lanzar
start "LLM Scout" /b %1 "%~dp0scout.py"
goto :eof
