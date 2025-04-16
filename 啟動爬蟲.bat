@echo off
echo === 104人力銀行求職者爬蟲 ===
echo 注意：使用本工具需遵守104相關使用條款及個人資料保護法
echo       僅供學習研究使用，請勿用於商業或非法用途

REM 檢查是否已安裝環境
if not exist venv (
    echo 尚未安裝環境！請先運行「安裝環境.bat」
    pause
    exit /b 1
)

REM 啟用虛擬環境
echo 正在啟動虛擬環境...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 啟動虛擬環境失敗！
    pause
    exit /b 1
)

REM 運行爬蟲程式
echo 正在運行爬蟲程式...
python company_resume_scraper.py
if %errorlevel% neq 0 (
    echo 爬蟲程式執行失敗！
    pause
    exit /b 1
)

REM 等待用戶按鍵結束
echo 爬蟲結束。
pause
