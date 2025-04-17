@echo off
chcp 950
echo === 104 Job Scraper ===
echo Note: For educational purposes only.

REM 切換到批次檔所在目錄
cd /d "%~dp0"
echo Current directory: %CD%

REM 顯示目錄內容
echo Directory contents:
dir *.py

REM 檢查是否有爬蟲檔案
set SCRAPER_FILE=company_resume_scraper.py
if not exist %SCRAPER_FILE% (
    echo Error: Scraper file not found: %SCRAPER_FILE%
    echo Please make sure "%SCRAPER_FILE%" is in the same folder as this batch file
    pause
    exit 1
)

REM 檢查環境
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment
        pause
        exit 1
    )
)

REM 啟動虛擬環境
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: Failed to activate virtual environment
    pause
    exit 1
)

REM 安裝必要套件
echo Installing required packages...
pip install langchain langchain_openai langchain_community pandas openpyxl playwright python-dotenv

REM 安裝Playwright瀏覽器
echo Installing Playwright browsers...
python -m playwright install chromium

REM 執行爬蟲
echo Running scraper...
python %SCRAPER_FILE%
if %errorlevel% neq 0 (
    echo Error: Scraper execution failed
    pause
    exit 1
)

echo Scraper completed.
echo The program will automatically close after 60 minutes if not closed manually.
timeout /t 3600 /nobreak
pause
