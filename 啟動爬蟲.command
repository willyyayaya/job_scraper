#!/bin/bash

# 獲取當前目錄
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 顯示歡迎訊息
echo "=== 104人力銀行求職者爬蟲 ==="
echo "注意：使用本工具需遵守104相關使用條款及個人資料保護法"
echo "      僅供學習研究使用，請勿用於商業或非法用途"

# 檢查是否已安裝環境
if [ ! -d "venv" ]; then
    echo "尚未安裝環境！請先運行「安裝環境.command」"
    read -p "按Enter鍵結束..."
    exit 1
fi

# 啟用虛擬環境
source venv/bin/activate

# 運行爬蟲程式
python3 company_resume_scraper.py

# 等待用戶按鍵結束
read -p "爬蟲結束。按Enter鍵關閉視窗..."
