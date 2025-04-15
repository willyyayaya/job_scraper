import asyncio
import time
import os
import logging
import pandas as pd
import json
from datetime import datetime
from playwright.async_api import async_playwright
import tempfile
import requests
import shutil
from urllib.parse import urlparse, quote
import urllib3

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("resume_scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("104_resume_scraper")

class ResumeScraperConfig:
    """爬蟲配置類"""
    def __init__(self, username="", password="", search_keyword=""):
        self.username = username  # 104企業會員帳號
        self.password = password  # 104企業會員密碼
        self.search_keyword = search_keyword  # 搜尋關鍵字
        
        # 網站URL
        self.vip_url = "https://vip.104.com.tw/"  # VIP系統首頁
        self.search_url = "https://vip.104.com.tw/search"  # 搜尋頁面URL
        
        # 建立輸出目錄
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_dir = f"resume_data_{self.timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)

class ResumeScraper:
    """104求職者資料爬蟲類"""
    
    def __init__(self, config=None):
        self.config = config or ResumeScraperConfig()
        self.browser = None
        self.context = None
        self.page = None
    
    async def initialize(self):
        """初始化瀏覽器"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=False)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self.context.new_page()
        logger.info("瀏覽器初始化成功")
    
    async def login(self):
        """登入至VIP系統"""
        try:
            # 步驟1: 進入VIP首頁
            await self.page.goto(self.config.vip_url)
            logger.info("已進入VIP首頁")
            
            # 步驟2: 檢查是否已經在repeatLogin頁面
            current_url = self.page.url
            if "repeatLogin" in current_url:
                logger.info("檢測到重複登入頁面")
                
                # 等待頁面完全載入
                await self.page.wait_for_load_state('networkidle', timeout=15000)
                
                # 找到並點擊"將目前帳號登出，立即登入"按鈕
                try:
                    # 先保存頁面截圖來分析問題
                    screenshot_path = os.path.join(self.config.output_dir, f"repeat_login_{int(time.time())}.png")
                    await self.page.screenshot(path=screenshot_path)
                    
                    # 嘗試列出頁面上所有按鈕及其文本以便診斷
                    button_texts = await self.page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim());
                    }''')
                    logger.info(f"頁面上所有按鈕文本: {button_texts}")
                    
                    # 使用更嚴格的選擇器策略
                    await self.page.click('button:has-text("將目前帳號登出，立即登入")', strict=True, timeout=5000)
                    logger.info("成功點擊「將目前帳號登出，立即登入」按鈕")
                except Exception as e:
                    logger.warning(f"嚴格選擇器失敗: {e}")
                    
                    # 嘗試使用最簡單的文本選擇方式
                    try:
                        await self.page.click('text="將目前帳號登出，立即登入"')
                        logger.info("通過文本內容點擊按鈕成功")
                    except Exception as text_e:
                        logger.warning(f"文本選擇器失敗: {text_e}")
                        
                        # 最後嘗試通過JavaScript找出並點擊按鈕
                        try:
                            result = await self.page.evaluate('''() => {
                                // 嘗試找到精確包含特定文本的按鈕
                                const allElements = document.querySelectorAll('*');
                                for (const el of allElements) {
                                    if (el.textContent.includes('將目前帳號登出，立即登入')) {
                                        el.click();
                                        return `點擊了包含文本的元素: ${el.tagName}`;
                                    }
                                }
                                return "未找到按鈕";
                            }''')
                            logger.info(f"JavaScript執行結果: {result}")
                        except Exception as js_e:
                            logger.error(f"JavaScript方法失敗: {js_e}")
                
                # 等待更長時間確保頁面轉換
                await asyncio.sleep(8)
                
                # 檢查是否仍在重複登入頁面
                if "repeatLogin" in self.page.url:
                    logger.warning("仍在重複登入頁面，嘗試直接訪問首頁")
                    await self.page.goto("https://vip.104.com.tw/index/index")
                    await asyncio.sleep(5)
            
            # 步驟3: 點擊登入按鈕
            login_button_selectors = [
                'a:text("登入")', 
                'button:text("登入")', 
                '.login-btn',
                'a[href*="login"]'
            ]
            
            for selector in login_button_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    await self.page.click(selector)
                    logger.info(f"已點擊登入按鈕 '{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"點擊登入按鈕 '{selector}' 失敗: {e}")
                    continue
            
            # 步驟4: 等待登入表單加載
            await asyncio.sleep(2)
            
            # 步驟5: 填寫帳號
            await self.page.fill('input[type="text"]', self.config.username)
            logger.info("已填寫帳號")
            
            # 步驟6: 填寫密碼
            await self.page.fill('input[type="password"]', self.config.password)
            logger.info("已填寫密碼")
            
            # 步驟7: 點擊登入按鈕
            submit_button_selectors = [
                'button[type="submit"]',
                'button:text("登入")',
                'input[type="submit"]'
            ]
            
            for selector in submit_button_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    await self.page.click(selector)
                    logger.info(f"已點擊提交按鈕 '{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"點擊提交按鈕 '{selector}' 失敗: {e}")
                    continue
            
            # 步驟8: 等待系統處理，準備接收驗證碼
            logger.info("登入提交完成，準備接收郵箱驗證碼...")
            
            # 步驟9: 等待驗證碼頁面加載
            await asyncio.sleep(5)
            
            # 步驟10: 檢查當前頁面，判斷是否已經成功登入或需要驗證碼
            current_url = self.page.url
            if "/index/index" in current_url:
                logger.info("已直接成功登入VIP系統，無需輸入驗證碼")
                return True
            
            # 步驟11: 等待用戶輸入驗證碼
            logger.info("請等待10秒，系統正在發送驗證碼到您的信箱...")
            for i in range(10, 0, -5):
                logger.info(f"剩餘等待時間: {i} 秒")
                await asyncio.sleep(5)
            
            logger.info("請檢查您的電子郵件並輸入收到的驗證碼")
            user_captcha = input("請輸入您收到的郵箱驗證碼: ")
            
            # 步驟12: 填入驗證碼
            captcha_selectors = [
                'input[name="captcha"]',
                'input[placeholder*="驗證碼"]',
                'input[type="text"]:not([autocomplete="username"])'
            ]
            
            for selector in captcha_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    await self.page.fill(selector, user_captcha)
                    logger.info(f"已填入驗證碼")
                    break
                except Exception as e:
                    logger.debug(f"填入驗證碼失敗: {e}")
                    continue
            
            # 步驟13: 提交驗證碼
            submit_captcha_selectors = [
                'button[type="submit"]',
                'button:text("確認")',
                'button:text("提交")',
                'input[type="submit"]'
            ]
            
            for selector in submit_captcha_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    await self.page.click(selector)
                    logger.info(f"已提交驗證碼")
                    break
                except Exception as e:
                    logger.debug(f"提交驗證碼失敗: {e}")
                    continue
            
            # 步驟14: 等待驗證處理
            await asyncio.sleep(5)
            
            # 步驟15: 最終檢查是否登入成功
            current_url = self.page.url
            if "/index/index" in current_url:
                logger.info("驗證成功，已登入VIP系統")
                return True
            else:
                logger.warning(f"可能未成功登入，當前URL: {current_url}")
                return False
            
        except Exception as e:
            logger.error(f"登入過程發生異常: {e}")
            screenshot_path = os.path.join(self.config.output_dir, f"login_error_{int(time.time())}.png")
            await self.page.screenshot(path=screenshot_path)
            logger.info(f"錯誤頁面截圖已保存至: {screenshot_path}")
            return False
    
    async def search(self):
        """搜索履歷功能"""
        try:
            # 檢查是否在首頁
            current_url = self.page.url
            if "/index/index" not in current_url and "vip.104.com.tw" not in current_url:
                logger.warning("似乎未在VIP系統主頁，嘗試重新導航")
                await self.page.goto(self.config.vip_url)
                await asyncio.sleep(3)
            
            logger.info("開始搜尋流程")
            
            # 嘗試找到搜尋輸入框
            search_input_selectors = [
                'input[data-qa-id="inputKeywordSearch"]',
                'input[placeholder="請輸入關鍵字"]',
                'input.form-input--dark',
                'input.form-control.form-input',
                'input[placeholder*="搜尋"]',
                'input[type="search"]',
                '.search-input',
                'input[name="keyword"]',
                'input[data-testid="search-input"]',
                '.header-search input'
            ]
            
            search_input_found = False
            for selector in search_input_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    await self.page.fill(selector, self.config.search_keyword)
                    logger.info(f"已輸入搜尋關鍵詞: {self.config.search_keyword}")
                    search_input_found = True
                    
                    # 按下Enter鍵執行搜尋
                    await self.page.press(selector, 'Enter')
                    logger.info("已按下Enter鍵執行搜尋")
                    break
                except Exception as e:
                    logger.debug(f"使用選擇器 '{selector}' 搜尋失敗: {e}")
                    continue
            
            if not search_input_found:
                logger.warning("無法找到搜尋輸入框，嘗試直接進入搜尋頁面")
                await self.page.goto(self.config.search_url)
                await asyncio.sleep(3)
                
                # 再次嘗試在搜尋頁面找到輸入框
                for selector in search_input_selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=5000)
                        await self.page.fill(selector, self.config.search_keyword)
                        logger.info(f"已在搜尋頁面輸入關鍵詞: {self.config.search_keyword}")
                        
                        # 按下Enter鍵執行搜尋
                        await self.page.press(selector, 'Enter')
                        logger.info("已按下Enter鍵執行搜尋")
                        search_input_found = True
                        break
                    except Exception as e:
                        logger.debug(f"在搜尋頁面使用選擇器 '{selector}' 失敗: {e}")
                        continue
            
            if not search_input_found:
                logger.error("無法找到搜尋輸入框，搜尋失敗")
                return False
            
            # 等待搜尋結果加載
            logger.info("等待搜尋結果加載...")
            await asyncio.sleep(5)
            
            # 確認搜尋成功
            current_url = self.page.url
            if "search" in current_url:
                logger.info(f"搜尋成功，當前URL: {current_url}")
                
                # 截圖搜尋結果頁面
                screenshot_path = os.path.join(self.config.output_dir, f"search_results_{int(time.time())}.png")
                await self.page.screenshot(path=screenshot_path)
                logger.info(f"搜尋結果頁面截圖已保存至: {screenshot_path}")
                
                return True
            else:
                logger.warning(f"搜尋可能未成功，當前URL: {current_url}")
                return False
            
        except Exception as e:
            logger.error(f"搜尋過程發生異常: {e}")
            screenshot_path = os.path.join(self.config.output_dir, f"search_error_{int(time.time())}.png")
            await self.page.screenshot(path=screenshot_path)
            logger.info(f"錯誤頁面截圖已保存至: {screenshot_path}")
            return False
    
    async def extract_results(self):
        """從搜尋結果頁面提取履歷卡片信息，包含大頭照和更多求職者資訊"""
        try:
            logger.info("開始提取履歷卡片信息，包含大頭照")
            
            # 建立照片存儲目錄
            photos_dir = os.path.join(self.config.output_dir, "profile_photos")
            os.makedirs(photos_dir, exist_ok=True)
            logger.info(f"建立照片存儲目錄: {photos_dir}")
            
            # 嘗試使用多種選擇器找到履歷卡片
            card_selectors = [
                '.resume-card',
                '.candidate-card',
                '.search-result-item',
                '.list-item',
                '[role="listitem"]',
                '.card',
                'article',
                '.resumeList',
                '.BaseCard'  # 104常用的卡片容器
            ]
            
            resume_cards = []
            
            for selector in card_selectors:
                try:
                    cards = await self.page.query_selector_all(selector)
                    if cards and len(cards) > 0:
                        logger.info(f"找到 {len(cards)} 個履歷卡片，使用選擇器: {selector}")
                        
                        # 從每個卡片中提取信息
                        for i, card in enumerate(cards):
                            try:
                                # 獲取卡片的HTML以便分析
                                card_html = await self.page.evaluate('(element) => element.outerHTML', card)
                                
                                # 提取求職者資訊
                                # 1. 姓名
                                name_selectors = ['.name', 'h2', '.title', '[data-qa-id="name"]']
                                name = await self.extract_text_from_element(card, name_selectors)
                                
                                # 2. 職稱/職位
                                title_selectors = ['.job-title', '.position', '[data-qa-id="title"]', '.position-name']
                                title = await self.extract_text_from_element(card, title_selectors)
                                
                                # 3. 工作經驗
                                exp_selectors = ['.experience', '.year', '[data-qa-id="experience"]', '.exp-year']
                                experience = await self.extract_text_from_element(card, exp_selectors)
                                
                                # 4. 學歷
                                edu_selectors = ['.education', '.school', '[data-qa-id="education"]', '.edu']
                                education = await self.extract_text_from_element(card, edu_selectors)
                                
                                # 5. 技能
                                skill_selectors = ['.skills', '.tags', '[data-qa-id="skills"]', '.skill-tags']
                                skills = await self.extract_text_from_element(card, skill_selectors)
                                
                                # 6. 要求待遇
                                salary_selectors = ['.salary', '.expected-salary', '[data-qa-id="salary"]']
                                salary = await self.extract_text_from_element(card, salary_selectors)
                                
                                # 7. 大頭照URL
                                photo_url = await self.extract_photo_url(card)
                                
                                # 下載大頭照
                                if photo_url:
                                    try:
                                        # 使用姓名(或索引)和時間戳作為文件名
                                        safe_name = name.replace(' ', '_') if name else f'person_{i}'
                                        filename = f"{safe_name}_{int(time.time())}.gif"  # 使用gif作為預設擴展名
                                        filename = self.sanitize_filename(filename)  # 確保文件名有效
                                        photo_path = os.path.join(photos_dir, filename)
                                        
                                        # 下載照片，增加等待時間
                                        logger.info(f"準備下載大頭照: {safe_name}")
                                        download_success = await self.download_photo(photo_url, photo_path)
                                        
                                        if download_success:
                                            logger.info(f"已成功下載大頭照: {photo_path}")
                                        else:
                                            logger.warning(f"下載大頭照失敗: {photo_url}")
                                            photo_path = None
                                    except Exception as photo_error:
                                        logger.error(f"下載大頭照過程中發生錯誤: {photo_error}")
                                        photo_path = None
                                else:
                                    logger.info(f"未找到第 {i+1} 個履歷的大頭照URL")
                                    photo_path = None
                                
                                # 8. 履歷詳情鏈接
                                profile_url = await self.extract_profile_url(card)
                                
                                # 組合所有資訊
                                resume_info = {
                                    'name': name,
                                    'title': title,
                                    'experience': experience,
                                    'education': education,
                                    'skills': skills,
                                    'salary': salary,
                                    'photo_url': photo_url,
                                    'photo_path': photo_path,
                                    'profile_url': profile_url,
                                    'card_html': card_html
                                }
                                
                                resume_cards.append(resume_info)
                                logger.info(f"已提取第 {i+1} 個履歷卡片的資訊: {name or '未知姓名'}")
                                
                            except Exception as e:
                                logger.error(f"提取第 {i+1} 個履歷卡片時發生錯誤: {e}")
                        
                        break  # 找到並處理卡片後退出循環
                    
                except Exception as e:
                    logger.debug(f"使用選擇器 '{selector}' 查找卡片時發生錯誤: {e}")
                    continue
            
            # 保存結果
            if resume_cards:
                # 保存至Excel
                df = pd.DataFrame(resume_cards)
                # 移除HTML欄位以避免Excel檔案過大
                if 'card_html' in df.columns:
                    df_excel = df.drop(columns=['card_html'])
                else:
                    df_excel = df
                excel_path = os.path.join(self.config.output_dir, f"履歷資料_{int(time.time())}.xlsx")
                df_excel.to_excel(excel_path, index=False)
                logger.info(f"已保存履歷資料至Excel: {excel_path}")
                
                # 保存至JSON
                json_path = os.path.join(self.config.output_dir, f"履歷資料_{int(time.time())}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    # 將DataFrame轉換為dict，以便JSON序列化
                    resume_dict = df.to_dict(orient='records')
                    json.dump(resume_dict, f, ensure_ascii=False, indent=2)
                logger.info(f"已保存履歷資料至JSON: {json_path}")
                
                return resume_cards
            else:
                logger.warning("未找到任何履歷卡片")
                return []
            
        except Exception as e:
            logger.error(f"提取履歷卡片時發生異常: {e}")
            return []
    
    async def extract_text_from_element(self, parent, selectors):
        """從父元素中提取文本"""
        for selector in selectors:
            try:
                element = await parent.query_selector(selector)
                if element:
                    text = await element.text_content()
                    return text.strip()
            except Exception:
                continue
        return None
    
    async def extract_photo_url(self, card):
        """從卡片中提取大頭照URL"""
        # 首先嘗試提取104特定格式的頭像
        try:
            # 直接尋找104 VIP網站特定格式的頭像圖片
            img = await card.query_selector('img[src*="webHeadShot"]')
            if img:
                src = await img.get_attribute('src')
                if src:
                    logger.info(f"找到104特定格式頭像: {src}")
                    return src
        except Exception as e:
            logger.debug(f"提取104特定頭像時出錯: {e}")
        
        # 如果找不到特定格式，嘗試其他選擇器
        photo_selectors = [
            'img[src*="headShot"]', 
            'img[src*="photo"]', 
            'img.avatar', 
            'img.profile-photo', 
            '.photo img', 
            '.avatar img',
            'img[title]',  # 104經常在title屬性放人名
            '.BaseAvatar img',
            'img[alt*="照片"]'
        ]
        
        for selector in photo_selectors:
            try:
                imgs = await card.query_selector_all(selector)
                for img in imgs:
                    src = await img.get_attribute('src')
                    if src and ('webHeadShot' in src or 'headShot' in src or 'photo' in src or 'avatar' in src):
                        # 如果是相對URL，轉換為絕對URL
                        if src.startswith('/'):
                            src = f"https://vip.104.com.tw{src}"
                        logger.info(f"找到候選頭像: {src}")
                        return src
            except Exception as e:
                logger.debug(f"使用選擇器 '{selector}' 提取頭像URL失敗: {e}")
        
        return None
    
    async def extract_profile_url(self, card):
        """提取履歷詳情鏈接"""
        link_selectors = [
            'a[href*="profile"]', 
            'a[href*="resume"]', 
            'a[href*="detail"]',
            '.card a',
            'a.card-link'
        ]
        
        for selector in link_selectors:
            try:
                link = await card.query_selector(selector)
                if link:
                    href = await link.get_attribute('href')
                    if href:
                        # 如果是相對URL，轉換為絕對URL
                        if href.startswith('/'):
                            href = f"https://vip.104.com.tw{href}"
                        return href
            except Exception:
                continue
        return None
    
    async def download_photo(self, url, save_path):
        """改進版104大頭照下載函數 - 多重嘗試策略"""
        try:
            logger.info(f"開始下載大頭照: {url}")
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # 方法1: 使用playwright的fetch API
            try:
                logger.info("方法1: 使用playwright的fetch API")
                
                # 執行JavaScript在瀏覽器環境中下載圖片
                result = await self.page.evaluate(f"""
                async function() {{
                    try {{
                        const response = await fetch("{url}", {{
                            method: 'GET',
                            headers: {{
                                'Referer': 'https://vip.104.com.tw/',
                                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                            }},
                            credentials: 'include'
                        }});
                        
                        if (!response.ok) throw new Error(`HTTP error: ${{response.status}}`);
                        
                        const buffer = await response.arrayBuffer();
                        const bytes = new Uint8Array(buffer);
                        return Array.from(bytes);
                    }} catch (e) {{
                        console.error('下載錯誤:', e);
                        return null;
                    }}
                }}
                """)
                
                if result:
                    with open(save_path, 'wb') as f:
                        f.write(bytes(result))
                    
                    file_size = os.path.getsize(save_path)
                    if file_size > 100:
                        logger.info(f"方法1成功: 檔案大小 {file_size} bytes")
                        return True
                    else:
                        logger.warning(f"方法1下載的檔案太小: {file_size} bytes")
                        os.unlink(save_path)
            except Exception as e:
                logger.warning(f"方法1失敗: {str(e)}")
            
            # 方法2: 調用系統curl命令
            try:
                logger.info("方法2: 使用系統curl命令")
                import subprocess
                
                # 獲取所有cookie
                cookies = await self.context.cookies()
                cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies 
                                       if 'vip.104.com.tw' in c.get('domain', '') or 
                                          'asset.vip.104.com.tw' in c.get('domain', '')])
                
                # 臨時文件以避免路徑問題
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp:
                    temp_path = temp.name
                
                # 構建curl命令 - 關閉SSL驗證
                curl_cmd = [
                    'curl', '-k', '--retry', '3', '--retry-delay', '2',
                    '-L', url,
                    '-H', f'Cookie: {cookie_str}',
                    '-H', 'Referer: https://vip.104.com.tw/',
                    '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                    '-o', temp_path
                ]
                
                # 執行命令
                proc = await asyncio.create_subprocess_exec(
                    *curl_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # 等待完成
                _, stderr = await proc.communicate()
                
                if proc.returncode == 0 and os.path.exists(temp_path):
                    file_size = os.path.getsize(temp_path)
                    if file_size > 100:
                        shutil.move(temp_path, save_path)
                        logger.info(f"方法2成功: 檔案大小 {file_size} bytes")
                        return True
                    else:
                        logger.warning(f"方法2下載的檔案太小: {file_size} bytes")
                        os.unlink(temp_path)
                else:
                    error = stderr.decode('utf-8', errors='ignore') if stderr else "未知錯誤"
                    logger.warning(f"方法2失敗: {error}")
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"方法2失敗: {str(e)}")
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    os.unlink(temp_path)
            
            # 方法3: 直接使用新頁面訪問並截圖
            try:
                logger.info("方法3: 直接訪問URL擷取圖片")
                page = await self.context.new_page()
                try:
                    # 直接訪問URL並等待圖片加載
                    await page.goto(url, timeout=30000, wait_until="networkidle")
                    
                    # 截圖並保存
                    await page.screenshot(path=save_path)
                    
                    file_size = os.path.getsize(save_path)
                    if file_size > 100:
                        logger.info(f"方法3成功: 檔案大小 {file_size} bytes")
                        return True
                    else:
                        logger.warning(f"方法3下載的檔案太小: {file_size} bytes")
                        if os.path.exists(save_path):
                            os.unlink(save_path)
                finally:
                    await page.close()
            except Exception as e:
                logger.warning(f"方法3失敗: {str(e)}")
            
            # 最後, 如果都失敗了，生成一個空白頭像
            logger.info("所有方法都失敗，使用空白頭像")
            import base64
            # 一個1x1透明GIF
            blank_image = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
            with open(save_path, 'wb') as f:
                f.write(blank_image)
            
            logger.info(f"已使用空白頭像: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"下載照片總體失敗: {str(e)}")
            return False
    
    def sanitize_filename(self, filename):
        """確保文件名有效（移除不允許的字符）"""
        # 替換不允許用作文件名的字符
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename
    
    async def run(self):
        """執行完整爬蟲流程"""
        try:
            # 初始化瀏覽器
            await self.initialize()
            
            # 登入
            login_success = await self.login()
            if not login_success:
                logger.error("登入失敗，無法繼續爬蟲")
                return False
            
            # 搜尋
            if self.config.search_keyword:
                search_success = await self.search()
                if not search_success:
                    logger.error("搜尋失敗，無法提取結果")
                    return False
                
                # 提取結果
                results = await self.extract_results()
                return results
            else:
                logger.info("未設定搜尋關鍵字，跳過搜尋步驟")
                return True
            
        except Exception as e:
            logger.error(f"爬蟲執行過程發生異常: {e}")
            return False
        finally:
            # 截圖最終頁面狀態
            final_screenshot = os.path.join(self.config.output_dir, f"final_state_{int(time.time())}.png")
            await self.page.screenshot(path=final_screenshot)
            logger.info(f"最終頁面截圖已保存至: {final_screenshot}")
    
    async def close(self):
        """關閉瀏覽器"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        logger.info("瀏覽器已關閉")

async def main():
    """主程序"""
    print("=== 104人力銀行求職者爬蟲 ===")
    print("注意：使用本工具需遵守104相關使用條款及個人資料保護法")
    print("      僅供學習研究使用，請勿用於商業或非法用途\n")
    
    username = input("請輸入104企業會員帳號: ")
    password = input("請輸入104企業會員密碼: ")
    keyword = input("請輸入搜索關鍵詞 (直接按Enter搜索全部): ")
    
    # 創建設定
    config = ResumeScraperConfig(
        username=username,
        password=password,
        search_keyword=keyword
    )
    
    # 創建爬蟲實例
    scraper = ResumeScraper(config)
    
    try:
        # 執行爬蟲
        results = await scraper.run()
        
        if results and isinstance(results, list):
            print(f"爬蟲完成，共獲取 {len(results)} 份履歷")
            print(f"結果已保存至目錄: {config.output_dir}")
        elif results is True:
            print("爬蟲流程已完成")
        else:
            print("爬蟲未能獲取有效結果")
    
    except Exception as e:
        logger.error(f"程序執行時出錯: {e}")
        print(f"程序執行時出錯: {e}")
    
    finally:
        # 關閉瀏覽器
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main()) 