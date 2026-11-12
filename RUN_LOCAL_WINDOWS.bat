@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
title Fual Wyckoff-SMC - Local Futures Analyst
echo ==========================================
echo    FUAL LOCAL WYCKOFF-SMC ANALYST
echo    READ ONLY - NO ORDERS
echo ==========================================
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (
  where python >nul 2>nul
  if errorlevel 1 (echo Python 3 is not installed or not on PATH.&echo Install Python from https://www.python.org/downloads/windows/&pause&exit /b 1)
  set "PY=python"
)
set "SYMBOL=BTCUSDT"
set /p "SYMBOL=Futures symbol [BTCUSDT]: "
if "%SYMBOL%"=="" set "SYMBOL=BTCUSDT"
echo.
echo Requesting verified closed candles for %SYMBOL% ...
%PY% -m scripts.run_public_futures_signal --symbol "%SYMBOL%" --output "reports\public_futures_signal.json"
set "RESULT=%errorlevel%"
echo.
echo Report: %CD%\reports\public_futures_signal.json
if not "%RESULT%"=="0" echo DATA UNAVAILABLE OR ERROR - NO TRADE SIGNAL
echo This report is research only; manually review before any trade.
pause
exit /b %RESULT%
