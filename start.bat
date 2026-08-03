@echo off
title Aleff — aleffthiago.com.br (local)
cd /d "%~dp0"
color 0A
echo.
echo  ========================================
echo   ALEFF THIAGO — site pronto
echo  ========================================
echo.
echo  USE SEMPRE:  http://127.0.0.1:3001/
echo  (nao misture com localhost — quebra o login)
echo.
echo  Login .... http://127.0.0.1:3001/loginsite.html
echo  Busca .... http://127.0.0.1:3001/search.html
echo.
echo  Contas: sanmuel (dev)  |  aleff (admin)  — senhas no .env
echo.
echo  NAO FECHE ESTA JANELA.
echo  ========================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3001 ^| findstr LISTENING') do (
  echo  Liberando porta 3001...
  taskkill /F /PID %%a >nul 2>&1
)

echo  Subindo servidor...
echo  Em 5 segundos o site abre sozinho.
echo.

REM Abre o navegador 5s depois — tempo pra Flask subir
start "" cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:3001/"

python -m backend.server
if errorlevel 1 (
  color 0C
  echo.
  echo  ERRO ao subir. Confira o Python.
  echo.
)
pause
