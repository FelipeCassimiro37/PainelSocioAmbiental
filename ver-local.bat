@echo off
chcp 65001 >nul
title Painel Socioambiental - servidor local
cd /d "%~dp0"

echo.
echo  SERVIDOR LOCAL DO PAINEL
echo  ========================
echo.
echo  O painel le os dados de arquivos separados, e o navegador so permite
echo  isso atraves de um servidor. Este atalho sobe um servidor na sua
echo  propria maquina - nada sai para a internet.
echo.

set "PYEXE="
call :testar py -3
if defined PYEXE goto achou
call :testar python
if defined PYEXE goto achou

echo  Python nao encontrado. Baixe em https://www.python.org/downloads/
echo  marcando "Add python.exe to PATH".
echo.
pause
exit /b 1

:achou
echo  Abrindo http://localhost:8000 no navegador...
start "" http://localhost:8000
echo.
echo  Para encerrar, feche esta janela.
echo.
%PYEXE% -m http.server 8000
exit /b

:testar
%* -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYEXE=%*"
exit /b
