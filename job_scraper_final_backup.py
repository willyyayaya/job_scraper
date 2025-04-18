import asyncio
import time
import pandas as pd
import re
import os
import logging
import random
from playwright.async_api import async_playwright, TimeoutError

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

async def scrape_104_jobs(job_title, page_limit=3):
    """
    爬取 104 人力銀行網站上的職缺資訊
    
    Args:
        job_title: 要搜尋的職位名稱
        page_limit: 要爬取的頁數限制，設為 float('inf') 則不限制頁數
    
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
        browser = await p.chromium.launch(headless=False)  # 設為 True 可以隱藏瀏覽器視窗
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
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

async def save_to_excel(df, filename="104_jobs.xlsx"):
    """將爬取的數據保存為 Excel 文件"""
    try:
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
                                                                                    
    104人力銀行職缺爬蟲程式 v1.1
    使用說明：
    1. 輸入職位名稱（例如：前端工程師、行銷企劃等）
    2. 輸入要爬取的頁數，建議1-5頁（輸入0則不限制頁數，會爬取所有可找到的頁面）
    3. 程式會自動爬取職缺資訊並保存為Excel文件

    注意：爬取頁數過多可能會耗時較長，且有被網站限制的風險，請謹慎使用
    """
    print(banner)

async def main():
    """主程序"""
    print_banner()
    
    try:
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
    except Exception as e:
        logger.error(f"程序執行過程中發生錯誤: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 