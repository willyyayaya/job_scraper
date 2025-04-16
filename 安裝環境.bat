@echo off
echo === 104爬蟲程式環境安裝 ===
echo 本腳本將為您安裝運行爬蟲所需的所有元件
echo 請稍等片刻...

REM 檢查是否已安裝Python
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo 未安裝Python！請先前往 https://www.python.org/downloads/ 下載安裝Python 3
    echo 安裝時請勾選"Add Python to PATH"選項
    echo 安裝完成後，請再次運行此腳本
    pause
    exit /b 1
)

REM 創建虛擬環境
echo 正在創建虛擬環境...
python -m venv venv
if %errorlevel% neq 0 (
    echo 創建虛擬環境失敗！
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

REM 安裝所需套件
echo 正在安裝必要套件...
pip install playwright pandas openpyxl Pillow
if %errorlevel% neq 0 (
    echo 安裝套件失敗！
    pause
    exit /b 1
)

REM 安裝Playwright瀏覽器
echo 正在安裝Playwright瀏覽器...
playwright install chromium
if %errorlevel% neq 0 (
    echo 安裝Playwright瀏覽器失敗！
    pause
    exit /b 1
)

echo 環境安裝完成！現在您可以運行「啟動爬蟲.bat」來開始使用爬蟲程式。
pause
