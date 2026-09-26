/r@echo off
rem Arranca o VintedBot: cria o venv e instala dependencias na primeira vez.
setlocal
cd /d "%~dp0"

if not exist ".env" (
    echo Falta o ficheiro .env. Copia o .env.example para .env e preenche o TELEGRAM_TOKEN.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo A criar o ambiente virtual...
    python -m venv .venv || exit /b 1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
)

".venv\Scripts\python.exe" -m vintedbot.main %*
