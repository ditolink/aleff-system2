@echo off
chcp 65001 >nul
echo ================================================
echo   Aleff Media System - Iniciando...
echo ================================================
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (echo ERRO: Python nao encontrado. & pause & exit /b 1)
if not exist ".env" (echo ERRO: Arquivo .env nao encontrado. & pause & exit /b 1)
if not exist "data" mkdir data
echo Inicializando banco...
set PYTHONPATH=.
python backend\utils\db_init.py
echo.
echo Sistema rodando em: http://localhost:3001
echo Nao feche esta janela!
echo.
timeout /t 2 /nobreak >nul
start http://localhost:3001
set PYTHONPATH=.
python backend\server.py
pause
