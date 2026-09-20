@echo off
rem Instala el autoarranque de LLM Scout (atajo VBS oculto en Inicio de Windows)
setlocal
cd /d "%~dp0"
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LLM Scout.vbs"
> "%VBS%" echo Set sh = CreateObject("WScript.Shell")
>> "%VBS%" echo sh.CurrentDirectory = "%~dp0."
>> "%VBS%" echo sh.Run "cmd /c pythonw scout.py", 0, False
echo Instalado en: "%VBS%"
exit /b
