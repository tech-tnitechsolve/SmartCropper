@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Smart Subject Cropper — Launcher
color 0B

:: ══════════════════════════════════════════════════════════
::  CẤU HÌNH
:: ══════════════════════════════════════════════════════════
set "VENV=.venv"
set "PY_MAJ=3"
set "PY_MIN=12"
set "MAIN=main.py"
set "REQ=requirements.txt"
set "VPY=%VENV%\Scripts\python.exe"
set "VPIP=%VENV%\Scripts\pip.exe"
set "LOCK=%VENV%\.running"

cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   SMART SUBJECT CROPPER — Launcher              ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ══════════════════════════════════════════════════════════
::  GUARD — Chống chạy trùng
:: ══════════════════════════════════════════════════════════
if exist "%LOCK%" (
    set /p "LOCK_PID=" <"%LOCK%"
    tasklist /FI "PID eq !LOCK_PID!" /NH 2>nul | findstr /i "python" >nul 2>&1
    if !errorlevel!==0 (
        echo  [!] App dang chay ^(PID: !LOCK_PID!^)
        echo      Neu bi treo, xoa file: %LOCK%
        timeout /t 4 >nul
        exit /b 0
    )
    del "%LOCK%" >nul 2>&1
)

:: ══════════════════════════════════════════════════════════
::  CHECK file cần thiết
:: ══════════════════════════════════════════════════════════
if not exist "%MAIN%" (
    echo  [ERROR] Thieu %MAIN%
    echo          %cd%
    pause & exit /b 1
)
if not exist "%REQ%" (
    echo  [ERROR] Thieu %REQ%
    echo          %cd%
    pause & exit /b 1
)

:: ══════════════════════════════════════════════════════════
::  BƯỚC 1 — Môi trường ảo
::
::  Có + đúng 3.12 → skip
::  Không/hỏng     → tìm Python, tạo mới
:: ══════════════════════════════════════════════════════════
echo  [1/3] Moi truong ao...

if exist "%VPY%" (
    "%VPY%" -c "import sys;exit(0 if sys.version_info[:2]==(%PY_MAJ%,%PY_MIN%) else 1)" >nul 2>&1
    if !errorlevel!==0 (
        echo        OK — san sang
        goto :CHECK_PKG
    )
    echo        Loi hoac sai version — xoa tao lai...
    rmdir /s /q "%VENV%" >nul 2>&1
) else (
    echo        Chua co — tao moi...
)

set "PY_CMD="

where py >nul 2>&1
if !errorlevel!==0 (
    py -%PY_MAJ%.%PY_MIN% --version >nul 2>&1
    if !errorlevel!==0 (
        set "PY_CMD=py -%PY_MAJ%.%PY_MIN%"
        goto :FOUND_PY
    )
)
where python >nul 2>&1
if !errorlevel!==0 (
    python -c "import sys;exit(0 if sys.version_info[:2]==(%PY_MAJ%,%PY_MIN%) else 1)" >nul 2>&1
    if !errorlevel!==0 (
        set "PY_CMD=python"
        goto :FOUND_PY
    )
)
where python3 >nul 2>&1
if !errorlevel!==0 (
    python3 -c "import sys;exit(0 if sys.version_info[:2]==(%PY_MAJ%,%PY_MIN%) else 1)" >nul 2>&1
    if !errorlevel!==0 (
        set "PY_CMD=python3"
        goto :FOUND_PY
    )
)

echo.
echo  [ERROR] Khong tim thay Python %PY_MAJ%.%PY_MIN%.x!
echo          Tai: https://www.python.org/downloads/
echo          Tick "Add Python to PATH" khi cai.
echo.
pause & exit /b 1

:FOUND_PY
for /f "tokens=*" %%v in ('!PY_CMD! --version 2^>nul') do echo        %%v

if exist "%VENV%" rmdir /s /q "%VENV%" >nul 2>&1
!PY_CMD! -m venv "%VENV%"
if !errorlevel! neq 0 (
    echo  [ERROR] Tao venv that bai!
    pause & exit /b 1
)
echo        Tao venv xong

:: ══════════════════════════════════════════════════════════
::  BƯỚC 2 — Package
::
::  Import 7 package cốt lõi:
::    → Đủ: chạy luôn
::    → Thiếu: pip install từ requirements.txt
:: ══════════════════════════════════════════════════════════
:CHECK_PKG
echo  [2/3] Thu vien...

set "MISSING="
for %%m in (cv2 numpy PIL rembg psutil PyQt6 onnxruntime) do (
    "%VPY%" -c "import %%m" >nul 2>&1
    if !errorlevel! neq 0 set "MISSING=!MISSING! %%m"
)

if "!MISSING!"=="" (
    echo        OK — du het
    goto :RUN
)

echo        Thieu:!MISSING!
echo.
echo        Dang cai tu %REQ%...
echo        ^(Lan dau mat 2-5 phut^)
echo.

"%VPIP%" install --upgrade pip >nul 2>&1
"%VPIP%" install -r "%REQ%"
if !errorlevel! neq 0 (
    echo.
    echo  [ERROR] Cai that bai! Kiem tra mang roi thu lai.
    pause & exit /b 1
)

set "FAIL="
for %%m in (cv2 numpy PIL rembg psutil PyQt6 onnxruntime) do (
    "%VPY%" -c "import %%m" >nul 2>&1
    if !errorlevel! neq 0 set "FAIL=!FAIL! %%m"
)
if not "!FAIL!"=="" (
    echo.
    echo  [ERROR] Van thieu:!FAIL!
    echo          Thu xoa %VENV%\ roi chay lai.
    pause & exit /b 1
)
echo.
echo        Cai xong — OK

:: ══════════════════════════════════════════════════════════
::  BƯỚC 3 — Chạy
:: ══════════════════════════════════════════════════════════
:RUN
echo  [3/3] Khoi dong...
echo.
echo  ════════════════════════════════════════════════════
echo   Dong cua so nay = tat app
echo  ════════════════════════════════════════════════════
echo.

if not exist "%LOCK%" echo 0> "%LOCK%"

"%VPY%" "%MAIN%"

if exist "%LOCK%" del "%LOCK%" >nul 2>&1
echo.
echo  App da dong.
timeout /t 2 >nul
endlocal