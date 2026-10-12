@echo off
REM Gera dist\ElginLamp.exe (um unico arquivo, sem janela de console).
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :erro

python -m pytest -q || goto :erro
python scripts\make_icon.py || goto :erro

pyinstaller --noconfirm --clean --onefile --windowed ^
    --name ElginLamp ^
    --icon build\icon.ico ^
    --paths . ^
    --collect-submodules tinytuya ^
    --collect-submodules tuya_sharing ^
    --exclude-module tkinter ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.Qt3DCore ^
    elgin_lamp\__main__.py || goto :erro

echo.
echo Pronto: dist\ElginLamp.exe
exit /b 0

:erro
echo.
echo Falhou. Veja as mensagens acima.
exit /b 1
