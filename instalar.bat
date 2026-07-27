@echo off
chcp 65001 >nul
echo ================================================
echo   Aleff Media System - Instalando dependencias
echo ================================================
python --version >nul 2>&1
if errorlevel 1 (echo ERRO: Python nao encontrado. Baixe em python.org & pause & exit /b 1)
echo Instalando pacotes...
python -m pip install flask flask-cors python-dotenv google-api-python-client google-auth-httplib2 google-auth-oauthlib werkzeug
echo.
echo ================================================
echo   Instalacao concluida!
echo   Agora configure o .env e clique em iniciar.bat
echo ================================================
pause
