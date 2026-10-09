@echo off
chcp 65001 >nul 2>&1
title Sourcerer
:: Everything Sourcerer owns lives one level down, in Sourcerer_files. This
:: launcher is the only thing in the unpacked folder, so it steps in there itself.
:: No ( ) blocks around text with brackets in it: cmd expands a variable before
:: it parses the block, and one ")" in a message ends the block early (TrackImage
:: lost its whole start that way). Plain gotos cannot do that.
set "SDIR=%~dp0Sourcerer_files"
if exist "%SDIR%\app.py" goto :found
echo  [ERROR] Sourcerer_files\app.py not found next to this launcher.
echo          Unpack the whole ZIP, keeping start-windows.bat and the
echo          Sourcerer_files folder side by side.
goto :fail
:found
cd /d "%SDIR%"
echo.
echo  ========================================
echo   Sourcerer v0.0 - Setup ^& Start
echo  ========================================
echo.

:: The py launcher first: it finds a python.org install even when "Add to PATH"
:: was not ticked. Plain "python" may be the Microsoft Store stub, which
:: answers nothing useful -- the version check below catches that too.
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :have_py
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :have_py
echo  [ERROR] Python not found. Install Python 3.10 or newer from python.org
echo          and run this file again.
goto :fail
:have_py
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto :py_ok
echo  [ERROR] This Python is older than 3.10. Install a current one from
echo          python.org and run this file again.
goto :fail
:py_ok

set "VPY=%SDIR%\venv\Scripts\python.exe"
if exist "%VPY%" goto :venv_ok
echo  [1/3] Creating the Python environment...
%PY% -m venv venv
if exist "%VPY%" goto :venv_ok
echo  [ERROR] Could not create it, see above.
goto :fail
:venv_ok
:: Everything Sourcerer needs lives in THIS venv; per-user packages stay out.
set "PYTHONNOUSERSITE=1"

:: Only when requirements.txt changed -- pip on every start costs seconds for nothing.
fc /b requirements.txt venv\requirements.installed >nul 2>&1
if not errorlevel 1 goto :deps_ok
echo  [2/3] Installing dependencies...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :deps_fail
copy /y requirements.txt venv\requirements.installed >nul
goto :deps_ok
:deps_fail
echo  [ERROR] Installing dependencies failed, see above.
goto :fail
:deps_ok

echo  [3/3] Starting Sourcerer...
echo.
"%VPY%" app.py %*
:: A double-clicked window closes the moment the program ends; stay open so
:: what it said can be read.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
