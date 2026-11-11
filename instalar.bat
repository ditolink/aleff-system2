@echo off
chcp 65001 >nul
echo ================================================
echo   Aleff Media System - Instalando dependencias
echo ================================================
python --version >nul 2>&1
if errorlevel 1 (echo ERRO: Python nao encontrado. Baixe em python.org & pause & exit /b 1)
echo Instalando pacotes...
python -m pip install -r requirements.txt
echo.
echo ================================================
echo   Instalacao concluida!
echo   Agora configure o .env e clique em iniciar.bat
echo ================================================
pause
