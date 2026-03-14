@echo off
setlocal

set "PYTHON_EXE="

if exist "%~dp0.venv312\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv312\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0.venv-check\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv-check\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"

if not defined PYTHON_EXE (
    echo No working Python interpreter was found.
    exit /b 1
)

"%PYTHON_EXE%" -m bot %*
