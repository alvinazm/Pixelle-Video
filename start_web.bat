@echo off
chcp 65001 >nul 2>&1

echo 🚀 Starting  Web UI...
echo.

uv run streamlit run web/app.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo   [ERROR] Failed to Start
    echo ========================================
    echo.
    echo It appears you downloaded the SOURCE CODE directly.
    echo.
    echo ========================================
    echo.
    pause
)


