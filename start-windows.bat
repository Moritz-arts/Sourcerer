@echo off
setlocal
chcp 65001 >nul 2>&1
title Sourcerer
:: Finds a Python 3.10+ and hands over to Sourcerer_files\launch.py, which does
:: everything else. setlocal keeps every variable inside this script when it
:: is run from an open console.
::
:: No ( ) blocks: cmd expands a variable before it parses a block, and one ")"
:: in a message ends the block early (TrackImage lost its whole start that
:: way). Plain gotos cannot do that. And no "cd": started from a \\server
:: share, cmd cannot change into it and silently stays in C:\Windows -- every
:: path below is absolute instead.
set "SDIR=%~dp0Sourcerer_files"
if exist "%SDIR%\launch.py" goto :find_python
echo  [ERROR] Sourcerer_files\launch.py not found next to this launcher.
echo          Unpack the whole ZIP, keeping start-windows.bat and the
echo          Sourcerer_files folder side by side.
goto :fail

:find_python
:: Each candidate must be 3.10 or newer, not merely present: a py launcher that
:: picks an old 3.9 must not hide a current python on PATH. "call" because a
:: python that is itself a .bat or .cmd -- pyenv-win's shims -- would otherwise
:: take over this script for good and never come back.
:: The py launcher first: it finds a python.org install even when "Add to PATH"
:: was not ticked. Plain "python" may be the Microsoft Store stub, which fails
:: the check like a missing one.
set "PY="
call py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if "%errorlevel%"=="0" set "PY=py -3"
if defined PY goto :run
call python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if "%errorlevel%"=="0" set "PY=python"
if defined PY goto :run
echo  [ERROR] Sourcerer needs Python 3.10 or newer, and none was found.
echo          Install a current one from python.org and run this file again.
goto :fail

:run
call %PY% "%SDIR%\launch.py" %*
set "RC=%errorlevel%"
:: A double-clicked window closes the moment the program ends; stay open so
:: what it said can be read.
echo.
pause
exit /b %RC%

:fail
echo.
pause
exit /b 1
