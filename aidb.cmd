@echo off
setlocal
:: ai-dev-browser CLI — zero-dependency bootstrap for Windows.
::
:: Usage:
::   aidb <tool> [args]        Run a tool directly
::   aidb --list               List available tools
::   aidb <tool> --help        Tool-specific help
::
:: On first run, installs uv (if needed) and sets up the environment.
:: Requires: PowerShell. Does NOT require Python pre-installed.

where uv >nul 2>&1
if %errorlevel% neq 0 (
    :: Check common install locations before downloading
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
        goto :found_uv
    )
    if exist "%APPDATA%\uv\bin\uv.exe" (
        set "PATH=%APPDATA%\uv\bin;%PATH%"
        goto :found_uv
    )
    echo Installing uv ^(Python package manager^)... 1>&2
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%APPDATA%\uv\bin;%PATH%"
)
:found_uv

if "%~1"=="" goto :help
if "%~1"=="--help" goto :help
if "%~1"=="-h" goto :help

if "%~1"=="--list" (
    for %%f in ("%~dp0ai_dev_browser\tools\*.py") do (
        set "name=%%~nf"
        setlocal enabledelayedexpansion
        if not "!name:~0,1!"=="_" echo !name!
        endlocal
    )
    exit /b 0
)

:: Replace hyphens with underscores in tool name
set "tool=%~1"
set "tool=%tool:-=_%"
shift

uv run --directory "%~dp0." python -m "ai_dev_browser.tools.%tool%" %*
exit /b %errorlevel%

:help
echo Usage: aidb ^<tool^> [args]
echo.
echo Run 'aidb --list' to see available tools.
echo Run 'aidb ^<tool^> --help' for tool-specific help.
exit /b 0
