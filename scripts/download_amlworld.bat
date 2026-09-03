@echo off
REM ===================================================================
REM  Download one AMLworld split into data\amlworld\.
REM
REM  Dataset: kaggle.com/datasets/ealtman2019/
REM             ibm-transactions-for-anti-money-laundering-aml
REM  Paper:   Altman et al., NeurIPS 2023, arXiv:2306.16424
REM  Licence: CDLA-Sharing-1.0
REM
REM  WHY THIS EXISTS. docs\ARCHITECTURE_UPLIFT.md item 0.5 calls adding a
REM  second AMLworld split "arguably the highest-value item in the entire
REM  plan" -- "the scorer is the bottleneck on performance; sample size is
REM  the bottleneck on knowing anything." Only HI-Small was ever fetched, so
REM  every interval in this repository rests on 370 labelled rings in one
REM  world, and nearly every experiment returned an inconclusive CI as a
REM  direct result.
REM
REM  ALL SIX SPLITS LIVE IN THE ONE KAGGLE DATASET, so a single token gets
REM  any of them. LI-Small is the recommended next one: same size as
REM  HI-Small, same format, but a LOWER illicit ratio -- an independent draw
REM  at a different fraud base rate, which is the thing that tests whether a
REM  conclusion transfers. sentinel\corpus\ already refuses to pool two
REM  datasets, so there is no risk of silently averaging them.
REM
REM  Prerequisite, one-time and manual: a Kaggle API token at
REM      %USERPROFILE%\.kaggle\kaggle.json
REM  Create it at kaggle.com/settings -> API -> "Create New Token".
REM  This script refuses to run without it and NEVER prompts for
REM  credentials. Do not paste the contents of that file anywhere.
REM
REM  Usage:
REM      scripts\download_amlworld.bat list        (show every file + size)
REM      scripts\download_amlworld.bat LI-Small    (default)
REM      scripts\download_amlworld.bat HI-Medium
REM ===================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
set "DEST=%REPO_ROOT%\data\amlworld"
set "SLUG=ealtman2019/ibm-transactions-for-anti-money-laundering-aml"

set "SPLIT=%~1"
if "%SPLIT%"=="" set "SPLIT=LI-Small"

echo(
echo === AMLworld download ===
echo Dataset:     %SLUG%
echo Destination: %DEST%
echo(

REM --- 1. Kaggle API token ------------------------------------------
if not exist "%USERPROFILE%\.kaggle\kaggle.json" (
  echo [FAIL] No Kaggle API token found at:
  echo        %USERPROFILE%\.kaggle\kaggle.json
  echo(
  echo   Create one yourself -- do not paste credentials into a chat:
  echo     1. Make a free account at https://www.kaggle.com
  echo     2. Sign in and open https://www.kaggle.com/settings
  echo     3. Under "API", click "Create New Token" ^(downloads kaggle.json^)
  echo     4. Move it to %USERPROFILE%\.kaggle\kaggle.json
  echo     5. Re-run this script.
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

REM --- 3. List mode --------------------------------------------------
REM  Offered as a first-class mode rather than a comment telling you to run
REM  it by hand. The exact filenames for splits other than HI-Small are NOT
REM  assumed anywhere in this script beyond the obvious naming pattern, and
REM  guessing a filename wastes a multi-gigabyte download to find out.
if /I "%SPLIT%"=="list" (
  echo [..] Files in the dataset:
  python -m kaggle datasets files -d %SLUG% -v
  echo(
  echo Re-run with a split name, e.g.:  scripts\download_amlworld.bat LI-Small
  exit /b 0
)

REM --- 4. Free disk space -------------------------------------------
REM  The gate is sized per split, and it is deliberately conservative,
REM  because this repository has already lost a dataset to an OPTIMISTIC
REM  disk gate: the Elliptic2 downloader wanted 60 GB, passed on a machine
REM  with 75 GB free, then died part-way through an 88 GB extraction and
REM  left four of five files with no archive to recover the fifth from.
REM  See scripts\download_elliptic2.bat. An under-estimate that lets a
REM  doomed job start is worse than a refusal.
REM
REM  HI-Small extracted, for scale: Trans 475 MB, accounts 34 MB,
REM  Patterns 0.3 MB. The Small splits are ~0.5 GB each; Medium is several
REM  GB; Large is tens of GB.
set "NEED_GB=5"
echo %SPLIT% | findstr /I "Medium" >nul && set "NEED_GB=25"
echo %SPLIT% | findstr /I "Large" >nul && set "NEED_GB=120"

for /f "usebackq" %%G in (`powershell -NoProfile -Command ^
  "[math]::Floor((Get-PSDrive -Name ((Get-Item '%REPO_ROOT%').PSDrive.Name)).Free/1GB)"`) do set "FREE_GB=%%G"
echo [..] Free space on the target drive: %FREE_GB% GB ^(want ^>^= %NEED_GB% GB for %SPLIT%^)
if %FREE_GB% LSS %NEED_GB% (
  echo [FAIL] Not enough free space for the %SPLIT% split.
  echo(
  echo        Run `scripts\download_amlworld.bat list` to see the real file
  echo        sizes before freeing space -- the numbers above are headroom
  echo        estimates, and the one lesson this repo paid for is that a
  echo        disk gate you talked yourself past costs the whole download.
  exit /b 1
)
echo [ok] Disk space sufficient.

REM --- 5. Download, per file -----------------------------------------
REM  Per-file, never the whole dataset. `kaggle datasets download` with no
REM  -f pulls ALL SIX SPLITS at once, which is tens of gigabytes and is the
REM  single easiest way to repeat the Elliptic2 failure on this machine.
if not exist "%DEST%" mkdir "%DEST%"

set "FAILED="
for %%F in ("%SPLIT%_Trans.csv" "%SPLIT%_accounts.csv" "%SPLIT%_Patterns.txt") do (
  echo(
  echo [..] %%~F
  python -m kaggle datasets download -d %SLUG% -f "%%~F" -p "%DEST%" --unzip --force
  if errorlevel 1 (
    echo [FAIL] could not fetch %%~F
    set "FAILED=1"
  )
)

if defined FAILED (
  echo(
  echo [FAIL] At least one file did not download.
  echo        Most likely the filenames for this split differ from the
  echo        HI-Small pattern. Run:
  echo            scripts\download_amlworld.bat list
  echo        and download the exact names it prints.
  exit /b 1
)

echo(
echo [ok] %SPLIT% downloaded into %DEST%
echo(
echo Next:
echo   1. python scripts\verify_patterns.py     ^(sanity-check the labels^)
echo   2. NOT YET POSSIBLE, and this says so rather than implying otherwise:
echo      "HI-Small" is still HARDCODED in about ten scripts
echo      ^(build_stream, build_queue, eval_funnel, eval_oracle, others^),
echo      so the pipeline cannot be pointed at this split until that is
echo      lifted into a single setting. Downloading is step one of two.
echo      Do NOT pool the two splits once it is: sentinel corpus refuses
echo      it, and it is right to.
exit /b 0
