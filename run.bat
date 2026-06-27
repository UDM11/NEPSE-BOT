@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

:: ===========================================================
::  NEPSE ULTRA TRADING BOT - Launcher
::  Version: 1.0
:: ===========================================================

:MENU
cls
echo.
echo  +------------------------------------------------------+
echo  ^|         [LIVE]  NEPSE ULTRA TRADING BOT            ^|
echo  ^|            IPO Upper-Circuit Engine                  ^|
echo  +------------------------------------------------------+
echo.
echo   [1]  Run Bot  (Production - Real Broker Login)
echo   [2]  Run Bot  (Simulate Mode - No Real Orders)
echo   [3]  Run Bot  (No Dashboard - Headless Only)
echo   [4]  Run Bot  (Simulate + No Dashboard)
echo   [5]  Install / Update Dependencies
echo   [6]  Install Playwright Browsers
echo   [7]  View Live Logs  (tail)
echo   [8]  Open Dashboard in Browser
echo   [0]  Exit
echo.
echo  ------------------------------------------------------
set /p CHOICE="  Select option: "

if "%CHOICE%"=="1" goto RUN_PROD
if "%CHOICE%"=="2" goto RUN_SIM
if "%CHOICE%"=="3" goto RUN_NO_DASH
if "%CHOICE%"=="4" goto RUN_SIM_NO_DASH
if "%CHOICE%"=="5" goto INSTALL_DEPS
if "%CHOICE%"=="6" goto INSTALL_PLAYWRIGHT
if "%CHOICE%"=="7" goto VIEW_LOGS
if "%CHOICE%"=="8" goto OPEN_DASHBOARD
if "%CHOICE%"=="0" goto EXIT
goto MENU

:: ---------------------------------------------------------
:RUN_PROD
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [LIVE] Starting in PRODUCTION mode                 ^|
echo  ^|  * Real Naasa X broker login                        ^|
echo  ^|  * Dashboard: http://localhost:8080                 ^|
echo  ^|  * Press Ctrl+C to stop                             ^|
echo  +------------------------------------------------------+
echo.
call :CHECK_VENV
echo  Starting bot...
echo.
.venv\Scripts\python main.py
echo.
echo  Bot stopped. Press any key to return to menu.
pause >nul
goto MENU

:: ---------------------------------------------------------
:RUN_SIM
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [SIM] Starting in SIMULATE mode                    ^|
echo  ^|  * No real orders placed                            ^|
echo  ^|  * Simulated market ticks                           ^|
echo  ^|  * Dashboard: http://localhost:8080                 ^|
echo  ^|  * Press Ctrl+C to stop                             ^|
echo  +------------------------------------------------------+
echo.
call :CHECK_VENV
echo  Starting bot in simulate mode...
echo.
.venv\Scripts\python main.py --simulate
echo.
echo  Bot stopped. Press any key to return to menu.
pause >nul
goto MENU

:: ---------------------------------------------------------
:RUN_NO_DASH
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [LIVE] Starting in PRODUCTION (No Dashboard) mode  ^|
echo  ^|  * Real Naasa X broker login                        ^|
echo  ^|  * No web dashboard (logs only)                     ^|
echo  ^|  * Press Ctrl+C to stop                             ^|
echo  +------------------------------------------------------+
echo.
call :CHECK_VENV
echo  Starting bot without dashboard...
echo.
.venv\Scripts\python main.py --no-dashboard
echo.
echo  Bot stopped. Press any key to return to menu.
pause >nul
goto MENU

:: ---------------------------------------------------------
:RUN_SIM_NO_DASH
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [SIM] Starting in SIMULATE + No Dashboard mode     ^|
echo  ^|  * No real orders, no web dashboard                 ^|
echo  ^|  * Fast dry-run for testing                         ^|
echo  ^|  * Press Ctrl+C to stop                             ^|
echo  +------------------------------------------------------+
echo.
call :CHECK_VENV
echo  Starting simulate + no dashboard...
echo.
.venv\Scripts\python main.py --simulate --no-dashboard
echo.
echo  Bot stopped. Press any key to return to menu.
pause >nul
goto MENU

:: ---------------------------------------------------------
:INSTALL_DEPS
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [DEPS] Installing / Updating Python Dependencies   ^|
echo  +------------------------------------------------------+
echo.

if not exist ".venv" (
    echo  Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Failed to create venv. Is Python installed?
        pause
        goto MENU
    )
    echo  Virtual environment created.
)

echo  Upgrading pip...
.venv\Scripts\python -m pip install --upgrade pip --quiet

echo  Installing requirements...
.venv\Scripts\pip install -r requirements.txt
echo.
echo  [SUCCESS] Dependencies installed successfully.
pause
goto MENU

:: ---------------------------------------------------------
:INSTALL_PLAYWRIGHT
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [PLAYWRIGHT] Installing Playwright Browsers        ^|
echo  +------------------------------------------------------+
echo.
call :CHECK_VENV
.venv\Scripts\python -m playwright install chromium
echo.
echo  [SUCCESS] Playwright Chromium installed.
pause
goto MENU

:: ---------------------------------------------------------
:VIEW_LOGS
cls
echo.
echo  +------------------------------------------------------+
echo  ^|  [LOGS] Live Log Tail (logs\nepse_bot.log)          ^|
echo  ^|  Press Ctrl+C to stop tailing                       ^|
echo  +------------------------------------------------------+
echo.
if not exist "logs\nepse_bot.log" (
    echo  Log file not found. Has the bot been run yet?
    pause
    goto MENU
)
powershell -Command "Get-Content -Path 'logs\nepse_bot.log' -Wait -Tail 40"
goto MENU

:: ---------------------------------------------------------
:OPEN_DASHBOARD
cls
echo.
echo  Opening Dashboard at http://localhost:8080 ...
echo.
start "" "http://localhost:8080"
timeout /t 2 >nul
goto MENU

:: ---------------------------------------------------------
:CHECK_VENV
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [WARNING] Virtual environment not found!
    echo  Run option [5] to install dependencies first.
    echo.
    pause
    goto MENU
)
exit /b

:: ---------------------------------------------------------
:EXIT
cls
echo.
echo  Goodbye!
echo.
exit /b 0
