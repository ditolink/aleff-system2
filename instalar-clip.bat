@echo off
chcp 65001 >nul
echo ================================================
echo   Aleff Media System - Instalando OpenCLIP
echo   (analise visual de imagens sem internet)
echo ================================================
echo Isso pode demorar alguns minutos...
python -m pip install open-clip-torch torch Pillow requests
echo.
echo ================================================
echo   OpenCLIP instalado!
echo   Na aba "IA de Tags" do admin, selecione
echo   "OpenCLIP" para usar visao computacional.
echo ================================================
pause
