@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%CD%"

set "PY=python"
where python >nul 2>&1 || set "PY=py"

REM Prefer whatever Python already has the dependencies. A virtual environment
REM is only built if the system interpreter cannot run the app as-is.
set "VPY=%PY%"
"%VPY%" -c "import uvicorn, fastapi, numpy, httpx" >nul 2>&1
if not errorlevel 1 goto :run

if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "VPY=%ROOT%\.venv\Scripts\python.exe"
  "%ROOT%\.venv\Scripts\python.exe" -c "import uvicorn, fastapi, numpy, httpx" >nul 2>&1
  if not errorlevel 1 goto :run
)

echo Installing dependencies into your Python...
"%PY%" -m pip install --disable-pip-version-check -r "%ROOT%\requirements.txt"
set "VPY=%PY%"
"%VPY%" -c "import uvicorn, fastapi, numpy, httpx" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Could not install the dependencies. Run this by hand and read the error:
  echo     python -m pip install -r requirements.txt
  echo.
  exit /b 1
)

:run
if exist "%ROOT%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\.env") do set "%%a=%%b"
)
echo.
echo   Sentinel is starting on http://127.0.0.1:8000
echo   Press Ctrl+C to stop.
echo.
cd /d "%ROOT%\backend"
"%VPY%" -m uvicorn app:app --host 127.0.0.1 --port 8000
