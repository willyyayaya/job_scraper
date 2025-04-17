@echo off
echo === 104 Resume Scraper Environment Setup ===
echo This script will install all components required to run the scraper
echo Please wait a moment...

REM Check if Python is installed
python --version | findstr /i "3." > nul
if %errorlevel% neq 0 (
    echo Error: Python 3.x is not installed
    echo Please download and install Python 3 from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit 1
)

REM Check network connection
ping -n 1 www.google.com > nul
if %errorlevel% neq 0 (
    echo Error: Network connection issue detected
    echo Please check your internet connection and try again
    pause
    exit 1
)

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo Error: Failed to create virtual environment
    pause
    exit 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: Failed to activate virtual environment
    pause
    exit 1
)

REM Update pip
echo Updating pip...
python -m pip install --upgrade pip

REM Install required packages
echo Installing required packages...
pip install playwright pandas openpyxl Pillow
if %errorlevel% neq 0 (
    echo Error: Failed to install packages
    pause
    exit 1
)

REM Install Playwright browser
echo Installing Playwright Chromium browser...
playwright install chromium
if %errorlevel% neq 0 (
    echo Error: Failed to install Playwright browser
    pause
    exit 1
)

echo Installation completed successfully!
echo You can now run "startcraper.bat" to start the scraper.
pause
