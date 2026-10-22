@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

rem Legacy Qwen3-ASR server launcher for Windows. Port 8399.

set "PYEXE="
if exist ".asr-venv\Scripts\python.exe" set "PYEXE=.asr-venv\Scripts\python.exe"
if not defined PYEXE if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE if exist "backend\.venv\Scripts\python.exe" set "PYEXE=backend\.venv\Scripts\python.exe"
if not defined PYEXE goto no_env

"%PYEXE%" -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ('qwen_asr', 'torch', 'soundfile', 'numpy')) else 1)" >nul 2>nul
if errorlevel 1 goto missing_deps

echo [INFO] Starting legacy Qwen3-ASR server at http://127.0.0.1:8399
echo [INFO] Keep this window open while transcribing.
"%PYEXE%" asr_server.py 8399
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] ASR server exited with code %RC%.
  pause
)
exit /b 0

:no_env
echo [ERROR] No Python environment was found for the legacy ASR server.
echo.
echo Create a dedicated environment with:
echo     py -3.12 -m venv .asr-venv
echo     .asr-venv\Scripts\python.exe -m pip install -U pip
echo     .asr-venv\Scripts\python.exe -m pip install qwen_asr torch soundfile numpy
echo.
echo Then double-click this file again.
pause
exit /b 1

:missing_deps
echo [ERROR] The selected Python environment is missing legacy ASR dependencies.
echo         Needed: qwen_asr torch soundfile numpy
echo         Selected: %PYEXE%
echo.
echo Create a dedicated environment with:
echo     py -3.12 -m venv .asr-venv
echo     .asr-venv\Scripts\python.exe -m pip install -U pip
echo     .asr-venv\Scripts\python.exe -m pip install qwen_asr torch soundfile numpy
echo.
echo Then double-click this file again.
pause
exit /b 1
