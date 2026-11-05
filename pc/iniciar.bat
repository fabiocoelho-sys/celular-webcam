@echo off
rem Abre o programa do PC do Celular Webcam.
rem Na primeira vez cria o ambiente Python em %LOCALAPPDATA%\celular-webcam (fora do OneDrive).
setlocal
set VENV=%LOCALAPPDATA%\celular-webcam\venv

if not exist "%VENV%\Scripts\pythonw.exe" (
    echo Preparando o ambiente Python pela primeira vez...
    python -m venv "%VENV%" || (echo Python nao encontrado. Instale o Python 3.12+ & pause & exit /b 1)
    "%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -q -r "%~dp0requirements.txt" || (pause & exit /b 1)
)

start "" "%VENV%\Scripts\pythonw.exe" "%~dp0app.py"
