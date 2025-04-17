import os
import platform
import pathlib

def get_appropriate_path():
    """根據運行平台選擇適合的檔案路徑"""
    system = platform.system()
    
    if system == "Darwin":  # Mac OS
        # 使用用戶的桌面
        return os.path.expanduser("~/Desktop/FOOD_桌遊_開發總結.txt")
    elif system == "Windows":
        # Windows路徑
        return os.path.join(os.path.expanduser("~"), "Desktop", "FOOD_桌遊_開發總結.txt")
    else:  # Linux或其他
        return "/mnt/data/FOOD_桌遊_開發總結.txt"

def ensure_directory_exists(file_path):
    """確保檔案的目錄存在"""
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

def main():
    # 取得適合當前系統的路徑
    file_path = get_appropriate_path()
    
    # 確保目錄存在
    ensure_directory_exists(file_path)
    
    # 顯示將要保存的位置
    print(f"檔案將保存至: {file_path}")
    
    # 寫入檔案
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("""
【F.O.O.D. 極致美味的盛宴之戰 桌遊企劃總結】

📌 最初構想：
- 設計一款以食物擬人為主題、雙方城堡對戰為核心的 TCG 桌遊，風格可愛奇怪，類似 Kanahei、角落生物感。
- 結合爐石戰記、戰錘：入侵的機制，加入「三面城牆」機制＋ Token 配置資源系統。

📌 核心玩法設計：
- 玩家有三面城牆：抽牌區、法力區、出牌區，放置 Token 決定行動資源。
- 每副套牌上限 50 點，每張卡有點數與稀有度（街邊小吃、家常料理、餐館招牌、星級餐點）。
- 同名卡張數限制：普通卡 4、精選卡 3、極品卡 2、傳說卡 1。

📌 卡牌類型：
人物、法術、場地、城堡、武器、防具（後改為料理工具、烹飪技術、任務牌）。

📌 食物陣營分類：
- 速食工會、火辣王國、甜點聯盟、健康綠洲、中立系。
- 每個陣營有正負面關鍵字、專屬流派。例：速食現炸速攻流、油膩控制流。

📌 基礎機制通用關鍵字（食物風味命名）：
開胃（戰吼）、回味（死亡之聲）、滋補（吸血）、現炸（衝鋒）、爆汁（溢出傷害）、拼盤（融合）、酥脆（護甲）、糖霜（聖盾）、腐壞（致命劇毒）等。

📌 副本模式構想：
- 黑暗食魔副本塔，玩家闖關對抗魔王。
- 魔王例：腐化發酵漢堡 Fermento、暴走麻辣鍋魂 Hellpot、珍奶王 Pearl Emperor。
- 副本專屬卡＋副本反撲事件卡＋淨化版角色卡機制。

📌 副本冒險塔構想（仿殺戮尖塔）：
- 分岔式冒險地圖，包含戰鬥、事件、商店、Boss。
- 擲骰控制 AI 行動：士兵骰、法術骰、位置骰，自定義六面。

📌 將擴充資料包、副本挑戰包、限量 Boss 包作為銷售模式。

📌 募資策略：以劇情副本包與主套牌同步發行，副本包含 Boss 卡、專屬法術卡、劇本說明、特殊骰子貼紙。

📌 流派分類與卡池擴充計畫已完成速食工會、火辣王國、甜點聯盟、健康綠洲、中立系。

📌 未來追加：海鮮深淵、飲料學派、酒精莊園、壽司帝國等陣營。

📌 美術風格：人物牌為餐盤＋桌布稀有度，法術等牌為菜單，城堡牌擬作食物塔外觀，Token 擬為叉子、湯匙、醬料瓶等。

📌 預計副本設計可選用既有卡＋副本專屬卡，副本魔王限定卡牌、副本限定事件與效果。

📌 重要副本規則：副本 2 才能使用淨化版角色，敵方血量+10。副本內有反撲事件卡觸發額外懲罰。

【目前保留副本構想，先專心完成第一波五陣營卡池】

-- 開發總結 by Willy x GPT-4 桌遊計畫工作紀錄
""")
    
    print(f"檔案已成功保存至: {file_path}")

if __name__ == "__main__":
    main()
