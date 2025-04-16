#!/bin/bash

# 顯示歡迎訊息
echo "=== 104爬蟲程式環境安裝 ==="
echo "本腳本將為您安裝運行爬蟲所需的所有元件"
echo "請稍等片刻..."

# 獲取當前目錄
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 檢查是否已安裝Python
if ! command -v python3 &> /dev/null; then
    echo "未安裝Python！請先前往 https://www.python.org/downloads/ 下載安裝Python 3"
    echo "安裝完成後，請再次運行此腳本"
    read -p "按Enter鍵結束..."
    exit 1
fi

# 創建虛擬環境
echo "正在創建虛擬環境..."
python3 -m venv venv

# 啟用虛擬環境
source venv/bin/activate

# 安裝所需套件
echo "正在安裝必要套件..."
pip install playwright pandas openpyxl Pillow

# 安裝Playwright瀏覽器
echo "正在安裝Playwright瀏覽器..."
export PLAYWRIGHT_BROWSERS_PATH=0
playwright install chromium

echo "環境安裝完成！現在您可以運行「啟動爬蟲.command」來開始使用爬蟲程式。"
read -p "按Enter鍵結束..."
