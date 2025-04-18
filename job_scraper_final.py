import asyncio
import time
import pandas as pd
import re
import os
import logging
import random
from playwright.async_api import async_playwright, TimeoutError
import traceback
from urllib.parse import quote

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("104_scraper")

async def retry_async(coro_func, max_retries=3, retry_delay=2, *args, **kwargs):
    """重試機制，用於網絡請求等容易失敗的操作"""
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"嘗試 {attempt+1}/{max_retries} 失敗: {str(e)}")
            if attempt < max_retries - 1:
                delay = retry_delay * (1 + random.random())
                logger.info(f"等待 {delay:.2f} 秒後重試...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"已達最大重試次數，操作失敗: {str(e)}")
                raise

async def scrape_104_jobs(job_title, page_limit=3, headless=False):
    """
    爬取 104 人力銀行網站上的職缺資訊
    
    Args:
        job_title: 要搜尋的職位名稱
        page_limit: 要爬取的頁數限制，設為 float('inf') 則不限制頁數
        headless: 是否隱藏瀏覽器視窗，預設顯示視窗
    
    Returns:
        包含職缺詳細資訊的 DataFrame
    """
    # 顯示爬蟲模式
    if page_limit == float('inf'):
        logger.info(f"開始不限頁數爬取「{job_title}」職缺")
    else:
        logger.info(f"開始爬取「{job_title}」職缺，頁數限制: {page_limit} 頁")
    
    # 創建目錄保存日誌和臨時數據
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    temp_dir = f"temp_{timestamp}"
    os.makedirs(temp_dir, exist_ok=True)
    
    job_data = []
    
    async with async_playwright() as p:
        # 強制顯示瀏覽器視窗的設定
        browser_args = ['--start-maximized']
        browser = await p.chromium.launch(
            headless=headless,  # 強制非無頭模式
            args=browser_args
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # 強制啟用顯示視窗功能
        page = await context.new_page()

        # 顯示瀏覽器已啟動信息
        logger.info("瀏覽器已啟動，視窗已顯示")
        
        try:
            # 前往 104 人力銀行首頁
            logger.info("正在訪問 104 人力銀行主頁...")
            await page.goto('https://www.104.com.tw/', timeout=60000)
            logger.info("已載入 104 首頁")
            
            # 等待搜尋框加載並輸入職位名稱
            await page.wait_for_selector('input[placeholder*="關鍵字"]', timeout=20000)
            await page.fill('input[placeholder*="關鍵字"]', job_title)
            logger.info(f"已輸入搜尋關鍵字: {job_title}")
            
            # 點擊搜尋按鈕
            search_button_selectors = [
                'button.btn.btn-primary.js-formCheck',
                'button:has-text("找工作")',
                'button.btn-primary:visible',
                '.btn-primary.js-formCheck',
                'button[type="submit"]'
            ]
            
            search_button = None
            for selector in search_button_selectors:
                try:
                    search_button = await page.query_selector(selector)
                    if search_button:
                        logger.info(f"找到搜尋按鈕，使用選擇器: {selector}")
                        break
                except Exception as e:
                    logger.warning(f"尋找選擇器 {selector} 時出錯: {str(e)}")
            
            if search_button:
                await search_button.click()
                logger.info("已點擊搜尋按鈕")
            else:
                # 如果找不到按鈕，嘗試直接訪問搜尋結果頁面
                logger.warning("無法找到搜尋按鈕，嘗試直接訪問搜尋結果頁面")
                encoded_keyword = job_title.replace(" ", "%20")
                search_url = f"https://www.104.com.tw/jobs/search/?keyword={encoded_keyword}"
                await page.goto(search_url, timeout=60000)
                logger.info(f"已直接訪問搜尋結果頁面: {search_url}")
            
            # 等待搜尋結果加載
            await page.wait_for_load_state('networkidle', timeout=60000)
            logger.info("搜尋結果已加載")
            
            # 等待職缺列表出現
            try:
                await page.wait_for_selector('.job-list-container, article.job-list-item, .job-summary, .job-list-item', timeout=30000)
                logger.info("職缺列表已加載")
            except TimeoutError:
                logger.warning("等待職缺列表超時，但將繼續嘗試")
            
            # 儲存搜尋結果頁面 HTML，便於分析
            html_content = await page.content()
            with open(f"{temp_dir}/search_result.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"已保存搜尋結果頁面 HTML 至 {temp_dir}/search_result.html")
            
            current_page = 1
            has_next_page = True  # 用於判斷是否還有下一頁
            
            while current_page <= page_limit and has_next_page:
                if page_limit == float('inf'):
                    logger.info(f"正在處理第 {current_page} 頁 (不限頁數模式)")
                else:
                    logger.info(f"正在處理第 {current_page}/{page_limit} 頁")
                
                # 提取當前頁面的職缺資訊
                selectors = [
                    '.job-list-item',
                    'article.job-list-item',
                    '[data-v-98e2e189] .job-summary',
                    '.container-fluid.job-list-container',
                    'div.job-list-container',
                    '.vue-recycle-scroller__item-view'
                ]
                
                job_items = []
                for selector in selectors:
                    items = await page.query_selector_all(selector)
                    if items and len(items) > 0:
                        logger.info(f"使用選擇器 '{selector}' 找到 {len(items)} 個職缺項目")
                        job_items = items
                        break
                    
                if not job_items:
                    # 如果常規選擇器都無效，嘗試以更寬鬆的方式查找
                    logger.warning("無法使用常規選擇器找到職缺項目，嘗試備用選擇器")
                    job_items = await page.query_selector_all('div.position-relative.bg-white')
                    if not job_items:
                        logger.warning("使用備選選擇器仍找不到職缺，最後嘗試查找任何可能的職缺元素")
                        job_items = await page.query_selector_all('div:has(a:has-text("應徵"))')
                
                # 如果找不到任何職缺，可能已到達最後一頁
                if not job_items or len(job_items) == 0:
                    logger.info("未找到任何職缺項目，可能已到達最後一頁")
                    has_next_page = False
                    break
                
                # 處理職缺項目
                for idx, item in enumerate(job_items):
                    try:
                        # 提取職缺標題
                        title_element = await item.query_selector('.info-job__text, h2 a, .job-name, .job-title')
                        title = await title_element.inner_text() if title_element else "無職缺名稱"
                        title = title.strip()
                        
                        # 提取公司名稱
                        company_element = await item.query_selector('.info-company__text, .job-company, .company-name')
                        company = await company_element.inner_text() if company_element else "無公司名稱"
                        company = company.strip()
                        
                        # 提取地區、經驗、學歷和薪資
                        tags = await item.query_selector_all('.info-tags__text, .job-requirement__location, .job-requirement__edu, .job-requirement__exp, .job-requirement__salary')
                        
                        location = ""
                        experience = ""
                        education = ""
                        salary = ""
                        
                        for i, tag in enumerate(tags):
                            tag_text = await tag.inner_text()
                            tag_text = tag_text.strip()
                            
                            # 根據內容判斷標籤類型
                            if re.search(r'市|縣|區|鄉|鎮', tag_text):
                                location = tag_text
                            elif re.search(r'年|經歷', tag_text):
                                experience = tag_text
                            elif re.search(r'大學|專科|學歷|高中', tag_text):
                                education = tag_text
                            elif re.search(r'月薪|年薪|待遇', tag_text):
                                salary = tag_text
                        
                        # 提取職缺連結
                        link = ""
                        if title_element:
                            link = await title_element.get_attribute('href')
                            if not link and await title_element.query_selector('a'):
                                # 如果標題本身沒有 href 屬性，嘗試從子元素獲取
                                child = await title_element.query_selector('a')
                                link = await child.get_attribute('href')
                            elif not link:
                                # 嘗試從父元素獲取
                                parent_a = await page.evaluate("""(element) => {
                                    let parent = element;
                                    while (parent && parent.tagName !== 'A') {
                                        parent = parent.parentElement;
                                    }
                                    return parent ? parent.href : null;
                                }""", title_element)
                                if parent_a:
                                    link = parent_a
                        
                        # 如果連結是相對路徑，添加 domain
                        if link and not link.startswith('http'):
                            link = f"https://www.104.com.tw{link}"
                        
                        # 提取職缺描述
                        description_element = await item.query_selector('.info-description, .job-description, .job-detail__content')
                        description = await description_element.inner_text() if description_element else ""
                        description = description.strip()
                        
                        # 提取職缺標籤
                        tags_element = await item.query_selector_all('.info-othertags__text, .tag, .job-tag')
                        job_tags = []
                        for tag_element in tags_element:
                            tag_text = await tag_element.inner_text()
                            job_tags.append(tag_text.strip())
                        
                        job_tags_str = ", ".join(job_tags) if job_tags else ""
                        
                        # 將數據添加到列表
                        job_data.append({
                            '職缺名稱': title,
                            '公司名稱': company,
                            '工作地點': location,
                            '經驗要求': experience,
                            '學歷要求': education,
                            '薪資待遇': salary,
                            '職缺描述': description,
                            '職缺標籤': job_tags_str,
                            '連結': link
                        })
                        
                        logger.info(f"已爬取 {current_page}-{idx+1}: {title} - {company}")
                    
                    except Exception as e:
                        logger.error(f"處理職缺時發生錯誤: {str(e)}")
                        continue  # 跳過這個項目，繼續下一個
                
                # 每頁處理完後，儲存一次數據，防止中途中斷丟失
                temp_df = pd.DataFrame(job_data)
                temp_filename = f"{temp_dir}/104_{job_title}_temp_page{current_page}.xlsx"
                await save_to_excel(temp_df, temp_filename)
                logger.info(f"已保存當前進度至 {temp_filename}")
                
                # 檢查是否需要繼續爬取下一頁
                need_next_page = (current_page < page_limit) or (page_limit == float('inf'))
                if need_next_page:
                    try:
                        # 先保存當前頁面URL，作為備用方案
                        current_url = page.url
                        
                        # 保存當前職缺數量，用於驗證是否成功翻頁
                        current_job_count = len(job_data)
                        
                        # 嘗試直接構造下一頁URL
                        next_page_succeeded = False
                        try:
                            # 104網站通常使用頁數參數，嘗試直接修改URL
                            next_page_number = current_page + 1
                            
                            # 解析URL參數
                            if "page=" in current_url:
                                next_url = re.sub(r'page=\d+', f'page={next_page_number}', current_url)
                            else:
                                separator = "&" if "?" in current_url else "?"
                                next_url = f"{current_url}{separator}page={next_page_number}"
                            
                            logger.info(f"嘗試直接跳轉到第 {next_page_number} 頁，URL: {next_url}")
                            
                            # 導航到下一頁
                            await page.goto(next_url, timeout=60000)
                            
                            # 使用多重方式等待頁面加載
                            try:
                                # 等待DOM內容穩定
                                await page.wait_for_load_state('domcontentloaded', timeout=30000)
                                logger.info("下一頁DOM內容已加載")
                                
                                # 等待職缺列表出現
                                await page.wait_for_selector('.job-list-item, article.job-list-item, .container-fluid.job-list-container', timeout=30000)
                                logger.info("下一頁職缺列表已找到")
                                
                                # 暫停一下確保頁面渲染完成
                                await asyncio.sleep(3)
                                
                                # 檢查是否有新職缺
                                check_items = await page.query_selector_all('.job-list-item, article.job-list-item, .container-fluid.job-list-container')
                                if check_items and len(check_items) > 0:
                                    logger.info(f"成功跳轉到第 {next_page_number} 頁，找到 {len(check_items)} 個新職缺項目")
                                    current_page = next_page_number
                                    next_page_succeeded = True
                                else:
                                    logger.warning("跳轉後未找到職缺，嘗試其他方法")
                            except Exception as load_e:
                                logger.warning(f"等待頁面加載時出錯: {str(load_e)}")
                        
                        except Exception as url_e:
                            logger.warning(f"直接修改URL失敗: {str(url_e)}")
                        
                        # 如果URL方法失敗，嘗試點擊下一頁按鈕
                        if not next_page_succeeded:
                            logger.info("使用URL跳轉失敗，嘗試點擊下一頁按鈕")
                            
                            # 如果URL方法失敗，回到原頁面
                            try:
                                if page.url != current_url:
                                    await page.goto(current_url, timeout=60000)
                                    await page.wait_for_load_state('domcontentloaded', timeout=30000)
                                    await asyncio.sleep(2)  # 給頁面一些加載時間
                            except Exception as recover_e:
                                logger.warning(f"恢復原頁面失敗: {str(recover_e)}")
                            
                            # 嘗試不同的下一頁按鈕選擇器
                            next_page_selectors = [
                                'a.page-next',
                                '.pagination li:last-child a',
                                'button:has-text("下一頁")',
                                'button.js-more-page',
                                'button.btn-primary.js-more-page',
                                '.pagination-next button',
                                'button:has-text("更多職缺")',
                                'button.btn.js-more-jobs',
                                'button.btn.btn-primary.js-more-page',
                                'button.btn.btn-primary.btn-lg.btn-block.js-more-page',
                                'button[data-v-77b1d360]',
                                'button.btn.btn-primary.js-more-jobs'
                            ]
                            
                            # 將顯示更多職缺的方法優先於分頁
                            next_button = None
                            for selector in next_page_selectors:
                                try:
                                    logger.info(f"嘗試尋找下一頁按鈕: {selector}")
                                    next_button = await page.query_selector(selector)
                                    if next_button:
                                        is_visible = await next_button.is_visible()
                                        is_enabled = await next_button.is_enabled()
                                        logger.info(f"找到按鈕 {selector}, 可見: {is_visible}, 可點擊: {is_enabled}")
                                        
                                        if is_visible and is_enabled:
                                            break
                                        else:
                                            next_button = None  # 重置為None繼續尋找
                                except Exception as e:
                                    logger.warning(f"檢查選擇器 {selector} 時出錯: {str(e)}")
                            
                            if next_button:
                                logger.info(f"找到下一頁按鈕，準備點擊")
                                
                                # 嘗試常規點擊
                                try:
                                    # 先滾動到按鈕可見處
                                    await next_button.scroll_into_view_if_needed()
                                    await asyncio.sleep(1)  # 等待滾動完成
                                    
                                    # 拍照保存當前頁面狀態
                                    await page.screenshot(path=f"{temp_dir}/before_click_page{current_page}.png")
                                    
                                    # 點擊並等待加載
                                    await next_button.click()
                                    logger.info(f"已點擊第 {current_page} 頁的下一頁按鈕")
                                    
                                    # 等待頁面變化的多個指標
                                    load_successful = False
                                    
                                    # 等待DOM準備好
                                    try:
                                        await page.wait_for_load_state('domcontentloaded', timeout=15000)
                                        logger.info("DOM內容已加載")
                                        
                                        # 等待一些可見元素加載
                                        await page.wait_for_selector('.job-list-item, article.job-list-item, .container-fluid.job-list-container', timeout=15000)
                                        logger.info("頁面內容似乎已加載")
                                        
                                        # 確保頁面已經渲染
                                        await asyncio.sleep(2)
                                        
                                        # 拍照記錄頁面變化
                                        await page.screenshot(path=f"{temp_dir}/after_click_page{current_page}.png")
                                        
                                        # 檢查頁面是否有新內容
                                        new_items = await page.query_selector_all('.job-list-item, article.job-list-item')
                                        if new_items and len(new_items) > 0:
                                            logger.info(f"點擊後發現 {len(new_items)} 個職缺，換頁成功")
                                            current_page += 1
                                            load_successful = True
                                    except Exception as wait_e:
                                        logger.warning(f"等待頁面加載元素時出錯: {str(wait_e)}")
                                    
                                    # 檢查URL是否變化來確認換頁
                                    if not load_successful and page.url != current_url:
                                        logger.info(f"檢測到URL變化，舊URL: {current_url}, 新URL: {page.url}")
                                        # 給頁面額外時間加載
                                        await asyncio.sleep(5)
                                        current_page += 1
                                        load_successful = True
                                    
                                    if not load_successful:
                                        logger.warning("點擊後頁面似乎沒有變化，嘗試使用JavaScript點擊")
                                        try:
                                            # 使用JavaScript點擊
                                            await page.evaluate("button => button.click()", next_button)
                                            logger.info("已使用JavaScript點擊下一頁按鈕")
                                            
                                            # 等待一段時間，然後檢查頁面內容
                                            await asyncio.sleep(7)  # 給更長時間等待
                                            
                                            # 檢查是否有新內容
                                            js_new_items = await page.query_selector_all('.job-list-item, article.job-list-item')
                                            if js_new_items and len(js_new_items) > 0:
                                                logger.info(f"JavaScript點擊後發現 {len(js_new_items)} 個職缺，換頁成功")
                                                current_page += 1
                                                load_successful = True
                                        except Exception as js_e:
                                            logger.error(f"JavaScript點擊失敗: {str(js_e)}")
                                    
                                    if not load_successful:
                                        logger.warning("多種換頁方式均失敗，可能已到達最後一頁")
                                        has_next_page = False
                                
                                except Exception as click_e:
                                    logger.error(f"點擊換頁按鈕失敗: {str(click_e)}")
                                    has_next_page = False
                            else:
                                logger.warning("未找到有效的下一頁按鈕，爬蟲結束")
                                has_next_page = False
                        
                    except Exception as page_e:
                        logger.error(f"嘗試換頁時發生錯誤: {str(page_e)}")
                        # 記錄頁面狀態以便調試
                        try:
                            await page.screenshot(path=f"{temp_dir}/error_page{current_page}.png")
                            logger.info(f"已保存錯誤頁面截圖至 {temp_dir}/error_page{current_page}.png")
                        except:
                            pass
                        has_next_page = False
                else:
                    logger.info(f"已達到目標頁數限制 ({page_limit} 頁)，爬蟲結束")
                    break
                
        except Exception as e:
            logger.error(f"爬取過程中發生錯誤: {str(e)}")
            # 記錄頁面狀態以便調試
            try:
                await page.screenshot(path=f"{temp_dir}/crash_error.png")
                logger.info(f"已保存崩潰頁面截圖至 {temp_dir}/crash_error.png")
            except:
                pass
        finally:
            # 關閉瀏覽器
            await browser.close()
    
    # 創建 DataFrame 並返回結果
    df = pd.DataFrame(job_data)
    logger.info(f"爬取完成，共獲取 {len(df)} 筆職缺資訊")
    return df

def clean_text_for_excel(text):
    """清理文本，移除或替換可能導致Excel存儲問題的字符"""
    if not text or not isinstance(text, str):
        return ""
    
    # 替換不可見字符和特殊控制字符
    cleaned = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    
    # 處理可能被Excel誤認為公式的內容
    # 如果文本以 =, +, -, @, 或 ( 開頭，在前面加上單引號防止被解析為公式
    if cleaned and cleaned[0] in ['=', '+', '-', '@', '(']:
        cleaned = "'" + cleaned
    
    # 替換其他可能導致問題的Unicode字符
    problematic_chars = [
        '\u2028', '\u2029', '\uFEFF', '\u0000',  # 基本問題字符
        '\u001B', '\u001C', '\u001D', '\u001E', '\u001F',  # 控制字符
        '\u000B', '\u000C'  # 垂直制表符和分頁符
    ]
    for char in problematic_chars:
        cleaned = cleaned.replace(char, '')
    
    # 替換長破折號、特殊引號和其他可能有問題的標點符號
    cleaned = cleaned.replace('\u2013', '-').replace('\u2014', '-')  # 替換長破折號
    cleaned = cleaned.replace('\u2018', "'").replace('\u2019', "'")  # 替換智能引號
    cleaned = cleaned.replace('\u201C', '"').replace('\u201D', '"')  # 替換智能雙引號
    
    # 替換可能導致Excel格式化問題的字符
    cleaned = re.sub(r'[\[\]\{\}]', '', cleaned)  # 移除方括號和花括號
    
    # 處理括號中的文本，確保不會被誤認為公式
    # 修改: 更嚴格地處理括號內容，以防止Excel格式問題
    def replace_parentheses(match):
        content = match.group(1)
        # 如果內容包含大學或學校名稱，特別處理
        if re.search(r'(?:大學|學院|University|College)', content, re.IGNORECASE):
            return "(" + content.replace('(', '［').replace(')', '］') + ")"
        return "('" + content + "')"
    
    cleaned = re.sub(r'\(([^)]*)\)', replace_parentheses, cleaned)
    
    # 處理教育信息中可能出現的問題（例如"大學畢業Rutgers University 視頻製作(美國)"）
    if re.search(r'(?:大學|學院|University|College)', cleaned, re.IGNORECASE):
        # 將教育信息中的括號替換為全形括號，以防止Excel誤解
        cleaned = re.sub(r'\(([^)]*)\)', lambda m: "（" + m.group(1) + "）", cleaned)
        # 將美國等國家名稱前的括號特別處理
        cleaned = cleaned.replace('(美國)', '（美國）').replace('(台灣)', '（台灣）')
        # 如果文本中有多個大學名稱，用分號分隔
        cleaned = re.sub(r'(University|College|大學|學院)([^\s,;，；])', r'\1; \2', cleaned, flags=re.IGNORECASE)
    
    # 嚴格檢查是否有可能導致Excel公式問題的字符組合
    formula_patterns = [r'=\w+\(', r'=\w+[+-/*]', r'@\w+\(']
    for pattern in formula_patterns:
        if re.search(pattern, cleaned):
            # 在整個字符串前加上單引號
            cleaned = "'" + cleaned
            break
    
    # 限制字符串長度以防止Excel問題
    max_length = 32000  # Excel單元格最大字符數限制
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    
    return cleaned

async def save_to_excel(df, filename="104_jobs.xlsx"):
    """將爬取的數據保存為 Excel 文件"""
    try:
        # 清理所有文本列中的數據
        for column in df.columns:
            if df[column].dtype == 'object':  # 只處理字符串類型的列
                df[column] = df[column].apply(lambda x: clean_text_for_excel(x) if isinstance(x, str) else x)
        
        df.to_excel(filename, index=False, engine='openpyxl')
        logger.info(f"資料已保存至 {filename}")
        return True
    except Exception as e:
        logger.error(f"保存 Excel 文件時發生錯誤: {str(e)}")
        return False

def print_banner():
    """打印程序橫幅"""
    banner = """
    ██╗ ██████╗ ██╗  ██╗    ███████╗ ██████╗██████╗  █████╗ ██████╗ ███████╗██████╗ 
    ██║██╔═████╗██║  ██║    ██╔════╝██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
    ██║██║██╔██║███████║    ███████╗██║     ██████╔╝███████║██████╔╝█████╗  ██████╔╝
    ██║████╔╝██║╚════██║    ╚════██║██║     ██╔══██╗██╔══██║██╔═══╝ ██╔══╝  ██╔══██╗
    ██║╚██████╔╝     ██║    ███████║╚██████╗██║  ██║██║  ██║██║     ███████╗██║  ██║
    ╚═╝ ╚═════╝      ╚═╝    ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝
                                                                                    
    104人力銀行爬蟲程式 v2.0
    使用說明：
    1. 選擇搜尋類型：工作職缺或公司資訊
    2. 輸入關鍵字（工作職位或公司名稱）
    3. 輸入要爬取的頁數，建議1-5頁（輸入0則不限制頁數，會爬取所有可找到的頁面）
    4. 程式會自動爬取資訊並保存為Excel文件

    注意：爬取頁數過多可能會耗時較長，且有被網站限制的風險，請謹慎使用
    """
    print(banner)

async def main():
    """主程序"""
    print_banner()
    
    try:
        # 新增：選擇搜尋類型 - 工作還是公司
        print("\n請選擇要搜尋的類型：")
        print("1. 搜尋工作職缺")
        print("2. 搜尋公司資訊")
        
        search_type = input("請輸入選項 (1 或 2): ")
        while search_type not in ['1', '2']:
            search_type = input("輸入有誤，請重新輸入 (1 或 2): ")
        
        if search_type == '1':
            # 原本的工作搜尋功能
            job_title = input("請輸入要搜尋的職位名稱: ")
            if not job_title:
                logger.error("職位名稱不能為空")
                return
            
            page_limit_input = input("請輸入要爬取的頁數 (輸入0則不限制頁數，會爬取所有頁面): ")
            
            try:
                page_limit = int(page_limit_input) if page_limit_input else 3
            except ValueError:
                logger.error("請輸入有效的數字")
                return
            
            if page_limit < 0:
                logger.error("頁數必須大於或等於 0")
                return
            
            # 轉換 page_limit 為實際限制值
            if page_limit == 0:
                page_limit = float('inf')  # 使用無限大表示不限頁數
                logger.info(f"開始爬取「{job_title}」，不限制頁數")
                print("您選擇了不限制頁數爬取，程式會爬取所有可找到的頁面，這可能需要較長時間...")
            else:
                logger.info(f"開始爬取「{job_title}」，共 {page_limit} 頁")
            
            start_time = time.time()
            df = await scrape_104_jobs(job_title, page_limit)
            end_time = time.time()
            
            if not df.empty:
                # 將結果保存為 Excel 文件
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                filename = f"104_{job_title}職缺_{timestamp}.xlsx"
                await save_to_excel(df, filename)
                
                # 顯示摘要
                print("\n" + "="*50)
                print("爬取結果摘要:")
                print("="*50)
                print(f"搜尋關鍵字：{job_title}")
                
                # 顯示實際爬取頁數
                actual_pages = 0
                if page_limit == float('inf'):
                    # 計算實際爬取的頁數
                    job_count = len(df)
                    avg_per_page = 20  # 假設每頁平均20個職缺
                    actual_pages = max(1, job_count // avg_per_page)
                    print(f"爬取頁數：不限制 (實際約爬取了 {actual_pages} 頁)")
                else:
                    print(f"爬取頁數：{page_limit}")
                    
                print(f"共爬取到 {len(df)} 筆職缺資訊")
                print(f"耗時：{end_time - start_time:.2f} 秒")
                print(f"資料已保存至：{filename}")
                print("="*50)
            else:
                logger.warning("未爬取到任何職缺資訊")
        
        elif search_type == '2':
            # 新增：公司搜尋功能
            company_name = input("請輸入要搜尋的公司名稱: ")
            if not company_name:
                logger.error("公司名稱不能為空")
                return
            
            page_limit_input = input("請輸入要爬取的頁數 (輸入0則不限制頁數，會爬取所有頁面): ")
            
            try:
                page_limit = int(page_limit_input) if page_limit_input else 3
            except ValueError:
                logger.error("請輸入有效的數字")
                return
            
            if page_limit < 0:
                logger.error("頁數必須大於或等於 0")
                return
            
            # 轉換 page_limit 為實際限制值
            if page_limit == 0:
                page_limit = float('inf')  # 使用無限大表示不限頁數
                logger.info(f"開始爬取「{company_name}」公司資訊，不限制頁數")
                print("您選擇了不限制頁數爬取，程式會爬取所有可找到的頁面，這可能需要較長時間...")
            else:
                logger.info(f"開始爬取「{company_name}」公司資訊，共 {page_limit} 頁")
            
            start_time = time.time()
            df = await scrape_104_companies(company_name, page_limit)
            end_time = time.time()
            
            if not df.empty:
                # 將結果保存為 Excel 文件
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                filename = f"104_{company_name}公司_{timestamp}.xlsx"
                await save_to_excel(df, filename)
                
                # 顯示摘要
                print("\n" + "="*50)
                print("爬取結果摘要:")
                print("="*50)
                print(f"搜尋關鍵字：{company_name}")
                
                if page_limit == float('inf'):
                    print(f"爬取頁數：不限制")
                else:
                    print(f"爬取頁數：{page_limit}")
                
                print(f"共爬取到 {len(df)} 筆公司資訊")
                print(f"耗時：{end_time - start_time:.2f} 秒")
                print(f"資料已保存至：{filename}")
                print("="*50)
            else:
                logger.warning("未爬取到任何公司資訊")
            
    except Exception as e:
        logger.error(f"程序執行過程中發生錯誤: {str(e)}")

async def scrape_104_companies(company_name, page_limit=3, headless=False):
    """
    爬取104人力銀行的公司資訊
    :param company_name: 要搜尋的公司名稱
    :param page_limit: 限制爬取的頁數
    :param headless: 是否隱藏瀏覽器視窗，預設顯示視窗
    :return: 包含公司資訊的DataFrame
    """
    # 顯示爬蟲模式
    if page_limit == float('inf'):
        logger.info(f"開始不限頁數爬取「{company_name}」公司資訊")
    else:
        logger.info(f"開始爬取「{company_name}」公司資訊，頁數限制: {page_limit} 頁")
    
    # 創建目錄保存日誌和臨時數據
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    temp_dir = f"temp_{timestamp}"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 初始化空列表存儲公司數據
    company_data = []
    # 用於追蹤已處理的公司名稱，避免重複
    processed_companies = set()
    
    async with async_playwright() as p:
        # 強制顯示瀏覽器視窗的設定
        browser_args = ['--start-maximized']
        browser = await p.chromium.launch(
            headless=headless,  # 強制非無頭模式
            args=browser_args
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # 強制啟用顯示視窗功能
        page = await context.new_page()

        # 顯示瀏覽器已啟動信息
        logger.info("瀏覽器已啟動，視窗已顯示")
        
        try:
            # 前往104人力銀行的公司搜尋頁面
            logger.info("正在訪問 104 人力銀行公司搜尋頁面...")
            
            # 搜尋URL
            encoded_company_name = quote(company_name)
            search_url = f"https://www.104.com.tw/company/search/?keyword={encoded_company_name}"
            
            # 訪問搜尋頁面
            logger.info(f"正在訪問 URL: {search_url}")
            await page.goto(search_url, timeout=60000)
            await page.wait_for_load_state('networkidle', timeout=60000)
            
            # 儲存搜尋結果頁面 HTML，便於分析
            html_content = await page.content()
            with open(f"{temp_dir}/company_search_result.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"已保存搜尋結果頁面 HTML 至 {temp_dir}/company_search_result.html")
            
            # 保存搜尋結果頁面截圖
            await page.screenshot(path=f"{temp_dir}/company_search_result.png")
            logger.info(f"已保存搜尋結果頁面截圖至 {temp_dir}/company_search_result.png")
            
            # 檢查是否有公司結果 - 多種可能的提示
            no_result_selectors = [
                '.no-result',
                '.empty-result',
                '.search-no-result',
                'div.container:has-text("查無符合條件的公司")',
                'div:has-text("沒有找到相關公司")'
            ]
            
            no_result = False
            for selector in no_result_selectors:
                try:
                    no_result_elem = await page.query_selector(selector)
                    if no_result_elem:
                        no_result = True
                        logger.warning(f"使用選擇器 '{selector}' 檢測到無結果")
                        break
                except:
                    continue
            
            # 使用JavaScript進一步檢查是否有結果
            if not no_result:
                no_result = await page.evaluate('''() => {
                    // 檢查頁面文字
                    const pageText = document.body.innerText;
                    return pageText.includes("查無符合條件的公司") || 
                           pageText.includes("沒有找到相關公司") ||
                           pageText.includes("查無資料");
                }''')
            
            if no_result:
                logger.warning("未找到任何公司")
                await page.screenshot(path=f"{temp_dir}/no_result.png")
                return pd.DataFrame()  # 返回空DataFrame
            
            # 從第1頁開始爬取，直到達到頁面限制或沒有更多頁面
            current_page = 1
            
            while current_page <= page_limit:
                logger.info(f"正在處理第 {current_page} 頁")
                
                # 等待頁面加載
                await asyncio.sleep(3)  # 給予更充分的時間讓頁面渲染
                
                # 獲取完整頁面並截圖便於分析
                await page.screenshot(path=f"{temp_dir}/page_{current_page}.png")
                
                # 首先直接檢查當前頁面的HTML結構
                page_html = await page.content()
                with open(f"{temp_dir}/page_{current_page}_full.html", "w", encoding="utf-8") as f:
                    f.write(page_html)
                
                # 找公司項目 - 處理Vue.js組件和標準元素
                # 根據用戶提供的HTML，我們需要找出".company-list__info"類的元素
                selectors = [
                    '.company-list__info',  # 新的Vue.js結構
                    '.company-item',  # 舊版結構
                    'div[class*="company-list"]', # 通用選擇器
                    'div:has(.company-name-link)' # 基於公司名稱鏈接的選擇器
                ]
                
                company_items = []
                for selector in selectors:
                    company_items = await page.query_selector_all(selector)
                    if company_items and len(company_items) > 0:
                        logger.info(f"使用選擇器 '{selector}' 找到 {len(company_items)} 個公司項目")
                        break
                
                if not company_items or len(company_items) == 0:
                    logger.warning(f"第 {current_page} 頁未找到公司項目")
                    break
                
                logger.info(f"在第 {current_page} 頁找到 {len(company_items)} 個潛在公司項目")
                
                # 遍歷每個公司項目
                for i, item in enumerate(company_items):
                    try:
                        # 獲取公司項目的HTML以便分析
                        item_html = await item.evaluate("el => el.outerHTML")
                        with open(f"{temp_dir}/company_item_{current_page}_{i+1}.html", "w", encoding="utf-8") as f:
                            f.write(item_html)
                        
                        # 獲取公司名稱 - 新的選擇器組合
                        company_name_selectors = [
                            '.company-name-link a',  # 新版Vue結構
                            'a.company-name-link--pc',  # 桌面版名稱鏈接
                            'a.company-name-link--mobile',  # 移動版名稱鏈接
                            'h2 a, h3 a, a.n-link',  # 舊版選擇器
                            'a[data-gtm-cmps="瀏覽公司"]',  # 基於GTM屬性
                            'a[title]:not([title=""]):not([title*="工作機會"])'  # 基於標題屬性的通用選擇器
                        ]
                        
                        company_name_element = None
                        for selector in company_name_selectors:
                            company_name_element = await item.query_selector(selector)
                            if company_name_element:
                                break
                        
                        if not company_name_element:
                            logger.warning(f"項目 {i+1} 沒有找到公司名稱元素，跳過")
                            continue
                        
                        company_name = await company_name_element.inner_text()
                        company_name = company_name.strip()
                        
                        # 獲取公司URL
                        company_url = await company_name_element.get_attribute("href")
                        if company_url and not company_url.startswith("http"):
                            company_url = f"https://www.104.com.tw{company_url}" if not company_url.startswith("//") else f"https:{company_url}"
                        
                        # 檢查公司名稱是否有效
                        if not company_name or len(company_name) <= 1 or company_name.lower() == "null":
                            logger.warning(f"項目 {i+1} 公司名稱無效: '{company_name}'，跳過")
                            continue
                        
                        # 跳過已處理的公司名稱
                        if company_name in processed_companies:
                            logger.info(f"公司 '{company_name}' 已經處理過，跳過")
                            continue
                        
                        processed_companies.add(company_name)
                        
                        # 獲取公司標籤（如"上市公司"、"新鮮人請進"等）
                        tag_selectors = [
                            'span.badge',
                            'span.rounded-pill',
                            '.company-list__tags span'
                        ]
                        
                        company_tags = []
                        for tag_selector in tag_selectors:
                            tag_elements = await item.query_selector_all(tag_selector)
                            for tag_element in tag_elements:
                                tag_text = await tag_element.inner_text()
                                tag_text = tag_text.strip()
                                if tag_text and not any(text in tag_text.lower() for text in ['查看', '關注', '評論']):
                                    company_tags.append(tag_text)
                        
                        company_tags_text = ", ".join(company_tags) if company_tags else "無標籤"
                        
                        # 獲取地點和產業 - 新的選擇器組合
                        location_industry_selectors = [
                            '.company-list__infoTags span',  # 新版Vue結構
                            'p.mb-0.text-truncate, p.text-truncate',  # 舊版結構
                            'span[data-v-e3fvojuuftu="company-list-company-summary-info-tags-items"]',  # 基於Vue屬性
                            '.h4:not(:has(a))'  # 不包含鏈接的h4元素
                        ]
                        
                        # 提取地點和產業
                        location = ""
                        industry = ""
                        capital = "未提供"
                        employee_count = "未提供"
                        review = "未提供"
                        
                        # 從公司卡片中提取各種標籤
                        for selector in location_industry_selectors:
                            info_tags = await item.query_selector_all(selector)
                            for tag in info_tags:
                                tag_text = await tag.inner_text()
                                tag_text = tag_text.strip()
                                
                                # 根據內容判斷標籤類型
                                if "市" in tag_text or "縣" in tag_text or "區" in tag_text:
                                    location = tag_text
                                elif "業" in tag_text and "公司" not in tag_text:
                                    industry = tag_text
                                elif "資本額" in tag_text:
                                    capital = tag_text
                                elif "員工數" in tag_text:
                                    employee_count = tag_text
                                elif "公司評論" in tag_text:
                                    review_parts = tag_text.split()
                                    if len(review_parts) > 1:
                                        review = review_parts[-1]
                        
                        # 如果找不到位置和產業，嘗試備用方法
                        if not location and not industry:
                            # 獲取所有文本
                            all_text = await item.evaluate("el => el.innerText")
                            
                            # 尋找地點
                            location_match = re.search(r'(?:台|臺|新|桃|苗|彰|雲|嘉|高|屏|宜|花|南|澎|金|連)[^,，、]{1,10}(?:市|縣|區)', all_text)
                            if location_match:
                                location = location_match.group(0)
                            
                            # 尋找產業
                            industry_match = re.search(r'[^\s,，、]{2,10}(?:製造|服務|銷售|科技|資訊|電子|金融|保險|營造|貿易|百貨|餐飲|物流|運輸|航空|教育|顧問|設計|傳播|媒體|娛樂|零售|批發|醫療|生技|農業|木業)', all_text)
                            if industry_match:
                                industry = industry_match.group(0)
                        
                        # 獲取公司簡介
                        description_selectors = [
                            '.company-list__description',  # 新版Vue結構
                            'p.mb-6.body-3.text-truncate-2, p.text-truncate-2'  # 舊版結構
                        ]
                        
                        description = ""
                        for selector in description_selectors:
                            description_element = await item.query_selector(selector)
                            if description_element:
                                description = await description_element.inner_text()
                                description = description.strip()
                                break
                        
                        # 將公司信息添加到列表
                        company_data.append({
                            '公司名稱': company_name,
                            '公司標籤': company_tags_text,
                            '地點': location,
                            '產業類別': industry,
                            '公司簡介': description,
                            '資本額': capital,
                            '員工數': employee_count,
                            '公司評論': review,
                            '公司網址': company_url
                        })
                        
                        logger.info(f"已成功爬取公司：{company_name}")
                        
                    except Exception as e:
                        logger.error(f"處理第 {current_page} 頁第 {i+1} 項時出錯: {str(e)}")
                        traceback.print_exc()
                        continue
                
                # 每頁處理完後，儲存一次數據，防止中途中斷丟失
                temp_df = pd.DataFrame(company_data)
                temp_filename = f"{temp_dir}/104_{company_name}_temp_page{current_page}.xlsx"
                await save_to_excel(temp_df, temp_filename)
                logger.info(f"已保存當前進度至 {temp_filename}")
                
                # 檢查是否需要繼續爬取下一頁
                if current_page >= page_limit:
                    logger.info(f"已達到目標頁數限制 ({page_limit} 頁)，爬蟲結束")
                    break
                
                # 檢查是否有下一頁按鈕
                next_page_selectors = [
                    '.pagination li:last-child a',  # 主要選擇器
                    'a[data-gtm-promotion="下一頁"]',  # 可能的GTM標籤
                    'a.page-link[aria-label="Next"]',  # Bootstrap分頁樣式
                    'a:has-text("下一頁")',
                    'button:has-text("下一頁")',
                    '.n-pagination .n-pagination-item:last-child',  # 新版104分頁
                    '.n-pagination .n-pagination-item--next'  # 另一種新版分頁
                ]
                
                next_page_button = None
                for selector in next_page_selectors:
                    next_page_button = await page.query_selector(selector)
                    if next_page_button:
                        # 檢查是否被禁用
                        is_disabled = await next_page_button.evaluate("""(element) => {
                            return element.classList.contains('disabled') || 
                                   element.hasAttribute('disabled') || 
                                   element.parentElement.classList.contains('disabled') ||
                                   element.getAttribute('aria-disabled') === 'true';
                        }""")
                        
                        if not is_disabled:
                            logger.info(f"找到可用的下一頁按鈕: {selector}")
                            break
                        else:
                            next_page_button = None
                
                if not next_page_button:
                    logger.info("找不到下一頁按鈕，可能已到達最後一頁")
                    break
                
                # 點擊下一頁按鈕
                try:
                    logger.info(f"正在切換到第 {current_page + 1} 頁")
                    
                    # 確保按鈕在視野內
                    await next_page_button.scroll_into_view_if_needed()
                    await asyncio.sleep(1)
                    
                    # 嘗試點擊
                    await next_page_button.click()
                    logger.info("已點擊下一頁按鈕")
                    
                    # 等待頁面加載
                    await page.wait_for_load_state('networkidle', timeout=30000)
                    await asyncio.sleep(3)  # 等待內容加載
                    
                    # 確認頁面已經變更
                    current_page += 1
                except Exception as e:
                    logger.error(f"點擊下一頁按鈕時出錯: {str(e)}")
                    
                    # 嘗試使用JavaScript點擊
                    try:
                        await page.evaluate("""(element) => {
                            element.click();
                        }""", next_page_button)
                        logger.info("已使用JavaScript點擊下一頁按鈕")
                        
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        await asyncio.sleep(3)
                        
                        current_page += 1
                    except Exception as js_e:
                        logger.error(f"JavaScript點擊下一頁按鈕失敗: {str(js_e)}")
                        break
            
        except Exception as e:
            logger.error(f"爬取公司信息時發生錯誤: {str(e)}")
            traceback.print_exc()
            # 嘗試保存當前頁面以便分析問題
            try:
                await page.screenshot(path=f"{temp_dir}/error_page.png")
                logger.info(f"已保存錯誤頁面至 {temp_dir}/error_page.png")
            except:
                pass
        finally:
            # 關閉瀏覽器
            await browser.close()
    
    # 創建 DataFrame 並返回結果
    df = pd.DataFrame(company_data)
    logger.info(f"爬取完成，共獲取 {len(df)} 筆公司資訊")
    return df

if __name__ == "__main__":
    asyncio.run(main()) 