@echo off
setlocal
:: ai-dev-browser CLI — zero-dependency bootstrap for Windows.
::
:: Usage:
::   adb <tool> [args]
::   adb --list
::   adb page-find --help
::
:: On first run, installs uv (if needed) and sets up the environment.
:: Requires: PowerShell. Does NOT require Python pre-installed.

where uv >nul 2>&1
if %errorlevel% neq 0 (
    :: Check common install locations before downloading
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
        goto :run
    )
    if exist "%APPDATA%\uv\bin\uv.exe" (
        set "PATH=%APPDATA%\uv\bin;%PATH%"
        goto :run
    )
    echo Installing uv ^(Python package manager^)... 1>&2
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%APPDATA%\uv\bin;%PATH%"
)

:run
uv run --directory "%~dp0." python -m ai_dev_browser %*
