@echo off
chcp 65001 >nul
title UrnaFacil
cd /d "%~dp0"

rem 1. Confere se o Python esta instalado
where py >nul 2>nul && (set "PY=py -3") || (where python >nul 2>nul && (set "PY=python") || set "PY=")
if "%PY%"=="" (
    echo O Python nao foi encontrado neste computador.
    echo Vou abrir a pagina de download. Na instalacao, marque "Add python.exe to PATH".
    echo Depois de instalar, de dois cliques neste arquivo de novo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

rem 2. Na primeira vez, cria um ambiente isolado e instala as dependencias
if not exist ".venv\Scripts\python.exe" (
    echo Primeira execucao: preparando o UrnaFacil. Isso leva 1 ou 2 minutos...
    %PY% -m venv .venv || goto erro
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt || goto erro
)

rem 3. Liga o servidor e abre o navegador
".venv\Scripts\python.exe" backend\iniciar.py || goto erro
exit /b 0

:erro
echo.
echo Algo deu errado. Confira sua conexao com a internet e tente de novo.
echo Se continuar, apague a pasta .venv e de dois cliques neste arquivo outra vez.
pause
exit /b 1
