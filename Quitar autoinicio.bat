@echo off
rem Quita el autoarranque de LLM Scout
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LLM Scout.vbs"
if exist "%VBS%" (
  del "%VBS%"
  echo Autoarranque quitado.
) else (
  echo No habia autoarranque instalado.
)
exit /b
