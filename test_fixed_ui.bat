@echo off
echo Testing Fixed UI Version of RDN Fee Scraper...
echo.
echo Checking for Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

echo Checking for required packages...
pip show selenium >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Installing required packages...
    pip install -r requirements.txt
)

echo Starting server with UI fixes...
python server-upgradedv2.py
pause