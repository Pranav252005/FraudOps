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
set "NEED_GB=32"

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
REM  CORRECTED. This gate used to want 60 GB and then run `--unzip` over the
REM  whole dataset. That is wrong twice over: the extracted set is about 88 GB
REM  (background_edges.csv alone is 82,877,432,755 bytes), so 60 GB was an
REM  under-estimate that PASSED on a machine with 75 GB free and then died
REM  part-way, leaving four of the five files extracted and the largest one
REM  missing. That is exactly what happened.
REM
REM  The fix is not a bigger number, it is not extracting. The two large files
REM  are downloaded as per-file zips and left compressed; sentinel's loader
REM  streams CSV rows straight out of them (see Source in
REM  sentinel\data\elliptic2.py). Only the three small files are unpacked.
REM
REM    background_edges.csv    82.9 GB extracted   ~24.5 GB zipped  -> KEEP ZIPPED
REM    background_nodes.csv     5.3 GB extracted    ~1.3 GB zipped  -> KEEP ZIPPED
REM    connected_components.csv, nodes.csv, edges.csv  ~20 MB total -> unzip
REM
REM  So the requirement is ~26 GB, and NEED_GB is set to 32 for headroom.
for /f "usebackq" %%G in (`powershell -NoProfile -Command ^
  "[math]::Floor((Get-PSDrive -Name ((Get-Item '%REPO_ROOT%').PSDrive.Name)).Free/1GB)"`) do set "FREE_GB=%%G"
echo [..] Free space on the target drive: %FREE_GB% GB ^(want ^>^= %NEED_GB% GB^)
if %FREE_GB% LSS %NEED_GB% (
  echo [FAIL] Not enough free space. The compressed layout needs roughly
  echo        %NEED_GB% GB. Free some space, or pass a different destination
  echo        by editing DEST above.
  echo        Do NOT work around this by extracting -- the extracted set is
  echo        about 88 GB and nothing in this project reads it that way.
  exit /b 1
)
echo [ok] Disk space sufficient.

REM --- 4. Download, per file -----------------------------------------
REM  Per-file rather than the whole dataset, so the two large files can be
REM  left compressed. `-f <name>` yields <name>.zip, which the loader reads
REM  in place.
if not exist "%DEST%" mkdir "%DEST%"

echo(
echo [..] Small files ^(~20 MB^), unpacked.
for %%F in (connected_components.csv nodes.csv edges.csv) do (
  if exist "%DEST%\%%F" (
    echo    [skip] %%F already present
  ) else (
    python -m kaggle datasets download -d %SLUG% -f %%F -p "%DEST%" --unzip --force
    if errorlevel 1 (
      echo [FAIL] kaggle download failed for %%F. Common causes:
      echo        - the token is expired or belongs to a different account
      echo        - you have not accepted the dataset's terms once, in the
      echo          browser, at https://www.kaggle.com/datasets/%SLUG%
      exit /b 1
    )
  )
)

echo(
echo [..] Large files, left ZIPPED on purpose. background_edges.csv is the
echo      big one -- expect ~24.5 GB and a long download.
for %%F in (background_nodes.csv background_edges.csv) do (
  if exist "%DEST%\%%F" (
    echo    [skip] %%F already extracted
  ) else if exist "%DEST%\%%F.zip" (
    echo    [skip] %%F.zip already present
  ) else (
    python -m kaggle datasets download -d %SLUG% -f %%F -p "%DEST%" --force
    if errorlevel 1 (
      echo [FAIL] kaggle download failed for %%F.
      exit /b 1
    )
  )
)

REM --- 5. Verify the five files the loader requires ------------------
echo(
echo [..] Verifying required files...
REM  Either form counts: the loader reads <name>.csv or <name>.csv.zip.
set "MISSING="
for %%F in (background_nodes.csv background_edges.csv connected_components.csv nodes.csv edges.csv) do (
  if exist "%DEST%\%%F" (
    for %%S in ("%DEST%\%%F") do echo    [ok] %%F  %%~zS bytes
  ) else if exist "%DEST%\%%F.zip" (
    for %%S in ("%DEST%\%%F.zip") do echo    [ok] %%F.zip  %%~zS bytes ^(streamed, not extracted^)
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
