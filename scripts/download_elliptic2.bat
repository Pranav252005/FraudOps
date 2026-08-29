@echo off
REM ===================================================================
REM  Download the Elliptic2 dataset into data\elliptic2\.
REM
REM  Dataset: kaggle.com/datasets/ellipticco/elliptic2-data-set
REM  (official Elliptic Co. account; the same five CSVs the
REM   MITIBMxGraph/Elliptic2 guide and sentinel\data\elliptic2.py expect.)
REM  Paper: arXiv:2404.19109, "The Shape of Money Laundering".
REM
REM  Elliptic2 is PUBLIC on Kaggle. It is not licence-gated -- the
REM  elliptic.co/elliptic2 request form referenced by the upstream README
REM  is not the only route, and sentinel\data\elliptic2.py's docstring
REM  claim that "no script can fetch it unattended" is wrong.
REM
REM  Prerequisite, one-time and manual: a Kaggle API token at
REM      %USERPROFILE%\.kaggle\kaggle.json
REM  Create it at kaggle.com/settings -> API -> "Create New Token".
REM  This script will refuse to run without it and will never prompt
REM  for credentials.
REM
REM  Usage:  scripts\download_elliptic2.bat
REM ===================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
set "DEST=%REPO_ROOT%\data\elliptic2"
set "SLUG=ellipticco/elliptic2-data-set"
set "NEED_GB=60"

echo(
echo === Elliptic2 download ===
echo Destination: %DEST%
echo(

REM --- 1. Kaggle API token ------------------------------------------
if not exist "%USERPROFILE%\.kaggle\kaggle.json" (
  echo [FAIL] No Kaggle API token found at:
  echo        %USERPROFILE%\.kaggle\kaggle.json
  echo(
  echo   Create one yourself -- do not paste credentials into a chat:
  echo     1. Sign in at https://www.kaggle.com/settings
  echo     2. Under "API", click "Create New Token"
  echo     3. Move the downloaded kaggle.json to
  echo        %USERPROFILE%\.kaggle\kaggle.json
  echo     4. Re-run this script.
  exit /b 1
)
echo [ok] Kaggle token present.

REM --- 2. Kaggle CLI -------------------------------------------------
python -c "import kaggle" >nul 2>&1
if errorlevel 1 (
  echo [..] Installing the kaggle CLI into the active interpreter...
  python -m pip install --quiet --upgrade kaggle
  if errorlevel 1 (
    echo [FAIL] pip install kaggle failed.
    exit /b 1
  )
)
echo [ok] kaggle CLI available.

REM --- 3. Free disk space -------------------------------------------
REM  The archive is tens of GB and the extracted CSVs are larger again;
REM  background_edges.csv alone is ~196M rows.
for /f "usebackq" %%G in (`powershell -NoProfile -Command ^
  "[math]::Floor((Get-PSDrive -Name ((Get-Item '%REPO_ROOT%').PSDrive.Name)).Free/1GB)"`) do set "FREE_GB=%%G"
echo [..] Free space on the target drive: %FREE_GB% GB ^(want ^>^= %NEED_GB% GB^)
if %FREE_GB% LSS %NEED_GB% (
  echo [FAIL] Not enough free space. Archive + extracted copy need roughly
  echo        %NEED_GB% GB combined. Free some space, or pass a different
  echo        destination by editing DEST above.
  exit /b 1
)
echo [ok] Disk space sufficient.

REM --- 4. Download + extract ----------------------------------------
if not exist "%DEST%" mkdir "%DEST%"
echo(
echo [..] Downloading %SLUG% -- this is tens of GB and will take a while.
python -m kaggle datasets download -d %SLUG% -p "%DEST%" --unzip --force
if errorlevel 1 (
  echo [FAIL] kaggle download failed. Common causes:
  echo        - the token is expired or belongs to a different account
  echo        - you have not accepted the dataset's terms once, in the
  echo          browser, at https://www.kaggle.com/datasets/%SLUG%
  echo        - the download was interrupted; re-run to resume from scratch
  exit /b 1
)

REM --- 5. Verify the five files the loader requires ------------------
echo(
echo [..] Verifying required files...
set "MISSING="
for %%F in (background_nodes.csv background_edges.csv connected_components.csv nodes.csv edges.csv) do (
  if exist "%DEST%\%%F" (
    for %%S in ("%DEST%\%%F") do echo    [ok] %%F  %%~zS bytes
  ) else (
    echo    [MISSING] %%F
    set "MISSING=1"
  )
)
if defined MISSING (
  echo(
  echo [FAIL] Some required files are missing. If the archive extracted into
  echo        a subdirectory, move the CSVs up into %DEST% and re-verify with:
  echo          python -c "from pathlib import Path; import sentinel.data.elliptic2 as e; print(e.missing_files(Path(r'%DEST%')))"
  exit /b 1
)

echo(
echo [done] Elliptic2 is in %DEST%.
echo        Next: python scripts\eval_elliptic2.py
endlocal
exit /b 0
