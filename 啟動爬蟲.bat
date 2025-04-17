@echo off
echo === 104 Resume Scraper ===
echo Note: Using this tool requires compliance with 104 terms of service and privacy laws
echo       For educational and research purposes only. Not for commercial or illegal use.

REM 切換到批次檔所在目錄
cd /d "%~dp0"
echo Current directory: %CD%

REM 顯示目錄內容以便診斷
echo Directory contents:
dir *.py

REM Check if environment is installed
if not exist venv (
    echo Error: Environment not installed
    echo Please run "install_environment.bat" first
    pause
    exit 1
)

REM Check folder permissions
echo Checking folder permissions...
mkdir test_permission > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: No write permission in current folder
    echo Please try running as administrator
    pause
    exit 1
) else (
    rmdir test_permission
)

REM Check if script exists
if not exist company_resume_scraper.py (
    echo Error: Scraper file not found
    echo Please make sure "company_resume_scraper.py" is in the same folder as this batch file
    echo File name must match exactly: company_resume_scraper.py
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

REM Run scraper
echo Running scraper...
python company_resume_scraper.py
if %errorlevel% neq 0 (
    echo Error: Scraper execution failed
    pause
    exit 1
)

echo Scraper completed.
echo The program will automatically close after 60 minutes if not closed manually.
timeout /t 3600 /nobreak > nul
pause
