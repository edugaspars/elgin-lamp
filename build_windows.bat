@echo off
REM Gera dist\LampDesk.exe (um unico arquivo, sem janela de console).
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :erro

python -m pytest -q || goto :erro
python scripts\build.py || goto :erro

echo.
exit /b 0

:erro
echo.
echo Falhou. Veja as mensagens acima.
exit /b 1
