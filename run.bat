@echo off
REM Launch the SUST-Preli FastAPI service from cmd.exe.
REM Usage:
REM   run.bat                  :: bind 0.0.0.0:8000
REM   run.bat 8765             :: bind 0.0.0.0:8765
REM   run.bat 127.0.0.1 8765   :: bind 127.0.0.1:8765

setlocal

set "HOST=0.0.0.0"
set "PORT=8000"
if not "%1"=="" set "HOST=%1"
if not "%2"=="" set "PORT=%2"

REM cd into the directory holding this batch file (the project root).
cd /d "%~dp0"

echo [run.bat] cwd       = %cd%
echo [run.bat] launching uvicorn on http://%HOST%:%PORT%

uvicorn main:app --host %HOST% --port %PORT%

endlocal