import asyncio
import time
import pandas as pd
import re
import os
import logging
import random
import json
from playwright.async_api import async_playwright, TimeoutError
from openai import AsyncOpenAI  # 導入 OpenAI 的異步客戶端

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

# OpenAI API 配置
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # 從環境變數中獲取API金鑰
DEFAULT_MODEL = "gpt-3.5-turbo-16k"  # 使用具有更大上下文的模型

# 初始化 OpenAI 客戶端
openai_client = None
use_ai = False  # 是否使用 AI 功能的標誌

def init_openai():
    """初始化 OpenAI 客戶端"""
    global openai_client, use_ai
    
    api_key = OPENAI_API_KEY
    
    # 如果環境變數中沒有API金鑰，嘗試從用戶輸入獲取
    if not api_key:
        user_key = input("請輸入OpenAI API金鑰 (如不使用AI功能請直接按Enter): ").strip()
        if user_key:
            api_key = user_key
    
    if api_key:
        try:
            openai_client = AsyncOpenAI(api_key=api_key)
            use_ai = True
            logger.info("OpenAI 客戶端初始化成功")
            return True
        except Exception as e:
            logger.error(f"OpenAI 客戶端初始化失敗: {str(e)}")
            print(f"初始化OpenAI失敗: {str(e)}")
            print("將使用普通爬蟲模式繼續運行")
            use_ai = False
    else:
        logger.warning("未設置 OpenAI API 金鑰，將以離線模式運行")
        use_ai = False
    
    return False

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

async def analyze_job_descriptions(job_data):
    """
    使用 OpenAI 分析職缺資訊，提取關鍵技能和見解
    
    Args:
        job_data: 包含職缺資訊的列表
    
    Returns:
        添加了 AI 分析結果的數據
    """
    if not use_ai or not openai_client:
        logger.warning("OpenAI 分析功能不可用，跳過分析步驟")
        return job_data
    
    logger.info("開始使用 OpenAI 分析職缺資訊...")
    
    analyzed_data = []
    batch_size = 5  # 每批處理的職缺數
    
    # 將數據分批處理，避免超過 API 請求限制
    for i in range(0, len(job_data), batch_size):
        batch = job_data[i:i+batch_size]
        logger.info(f"分析第 {i+1} 至 {i+len(batch)} 筆職缺 (共 {len(job_data)} 筆)")
        
        try:
            # 準備批次分析的提示文本
            prompt = "分析以下職缺資訊，提取關鍵技能、要求和職缺亮點：\n\n"
            
            for idx, job in enumerate(batch):
                prompt += f"職缺 {idx+1}:\n"
                prompt += f"標題: {job.get('職缺名稱', '')}\n"
                prompt += f"公司: {job.get('公司名稱', '')}\n"
                prompt += f"描述: {job.get('職缺描述', '')[:500]}...\n\n"  # 只取描述的前500字元
            
            prompt += """請提供以下分析：
1. 對每個職缺提取3-5個關鍵技能或要求
2. 評估每個職缺的薪資是否合理
3. 指出特別有價值或特殊的職缺機會
4. 總結這批職缺的共同趨勢或特點

以JSON格式回覆，格式如下：
{
  "jobs": [
    {
      "job_index": 1,
      "key_skills": ["技能1", "技能2", "技能3"],
      "salary_evaluation": "合理/偏低/偏高，原因...",
      "highlights": "該職缺的特別亮點..."
    },
    ...
  ],
  "trends": "總體趨勢分析..."
}"""
            
            # 調用 OpenAI API 獲取分析結果
            response = await openai_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": "你是一位專業的職缺分析專家，擅長從職缺描述中提取關鍵資訊並進行分析。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,  # 較低的溫度以獲得更一致的回應
                max_tokens=4000,
                response_format={"type": "json_object"}
            )
            
            # 解析回應
            analysis_text = response.choices[0].message.content
            analysis = json.loads(analysis_text)
            
            # 將分析結果添加到職缺數據中
            for job_index, job_analysis in enumerate(analysis.get("jobs", [])):
                if i + job_index < len(job_data):
                    job = batch[job_index]
                    job["AI分析_關鍵技能"] = ", ".join(job_analysis.get("key_skills", []))
                    job["AI分析_薪資評估"] = job_analysis.get("salary_evaluation", "")
                    job["AI分析_亮點"] = job_analysis.get("highlights", "")
                    analyzed_data.append(job)
            
            # 將整體趨勢分析添加到日誌
            logger.info(f"職缺趨勢分析: {analysis.get('trends', '無趨勢分析')}")
            
        except Exception as e:
            logger.error(f"使用 OpenAI 分析職缺時出錯: {str(e)}")
            # 如果分析失敗，仍然返回原始數據
            analyzed_data.extend(batch)
    
    return analyzed_data

async def generate_job_search_query(user_input):
    """
    使用 OpenAI 生成更優化的職缺搜索關鍵詞
    
    Args:
        user_input: 用戶輸入的工作搜索內容
    
    Returns:
        優化後的搜索關鍵詞
    """
    if not use_ai or not openai_client:
        logger.info("OpenAI 不可用，使用原始搜索詞")
        return user_input
    
    try:
        logger.info(f"正在優化搜索關鍵詞: '{user_input}'")
        
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一位求職專家，擅長優化職缺搜索關鍵詞以獲得更好的搜索結果。"},
                {"role": "user", "content": f"我想在104人力銀行搜索這樣的工作: {user_input}。請幫我優化搜索關鍵詞，給出一個簡潔且有效的關鍵詞組合。直接返回優化後的關鍵詞，不要有任何解釋或前綴。"}
            ],
            temperature=0.3,
            max_tokens=50
        )
        
        optimized_query = response.choices[0].message.content.strip()
        logger.info(f"原始關鍵詞: '{user_input}' -> 優化關鍵詞: '{optimized_query}'")
        
        return optimized_query
    except Exception as e:
        logger.error(f"生成優化搜索關鍵詞時出錯: {str(e)}")
        return user_input  # 出錯時返回原始輸入

async def extract_structured_job_info(html_content, job_title_selector):
    """
    使用 OpenAI 從HTML中提取結構化的職缺信息
    
    Args:
        html_content: 網頁HTML內容
        job_title_selector: 職缺標題的選擇器
    
    Returns:
        結構化的職缺信息列表
    """
    if not use_ai or not openai_client:
        logger.warning("OpenAI 不可用，無法提取結構化職缺信息")
        return []
    
    try:
        # 截取HTML的一部分來分析，避免超過token限制
        html_sample = html_content[:30000]  # 取前30K字符
        
        response = await openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "你是一位網頁分析專家，擅長從HTML中提取結構化信息。"},
                {"role": "user", "content": f"""從以下HTML中提取職缺信息。職缺標題通常位於選擇器 '{job_title_selector}' 中。
                請提取以下信息:
                1. 職缺標題
                2. 公司名稱
                3. 工作地點
                4. 薪資範圍
                5. 連結 (href 屬性)
                
                以JSON格式返回結果。
                
                HTML: {html_sample}
                """}
            ],
            temperature=0.2,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get("jobs", [])
    
    except Exception as e:
        logger.error(f"使用 OpenAI 提取職缺信息時出錯: {str(e)}")
        return []

async def generate_job_report(job_data, search_keyword):
    """
    生成詳細的職缺分析報告
    
    Args:
        job_data: 職缺數據
        search_keyword: 搜索關鍵詞
    
    Returns:
        HTML格式的報告文本
    """
    if not use_ai or not openai_client or not job_data:
        logger.warning("無法生成報告：OpenAI不可用或無職缺數據")
        return None
    
    try:
        logger.info("開始生成職缺分析報告...")
        
        # 準備報告數據
        job_summary = []
        for i, job in enumerate(job_data[:20]):  # 限制為前20個職缺
            job_summary.append({
                "標題": job.get("職缺名稱", "未知"),
                "公司": job.get("公司名稱", "未知"),
                "地點": job.get("工作地點", ""),
                "薪資": job.get("薪資待遇", ""),
                "關鍵技能": job.get("AI分析_關鍵技能", ""),
                "薪資評估": job.get("AI分析_薪資評估", ""),
                "亮點": job.get("AI分析_亮點", "")
            })
        
        # 計算平均薪資和常見技能
        salary_mentions = []
        all_skills = []
        for job in job_data:
            salary = job.get("薪資待遇", "")
            if salary and "面議" not in salary:
                # 嘗試提取薪資數字
                salary_numbers = re.findall(r'\d+,\d+|\d+萬|\d+', salary)
                if salary_numbers:
                    salary_mentions.append(salary)
            
            skills = job.get("AI分析_關鍵技能", "")
            if skills:
                all_skills.extend([s.strip() for s in skills.split(',')])
        
        from collections import Counter
        top_skills = Counter(all_skills).most_common(10)
        
        # 構建提示
        report_prompt = f"""
        請基於以下職缺數據，生成一份詳細的職缺分析報告。
        
        搜索關鍵詞: {search_keyword}
        總職缺數: {len(job_data)}
        薪資資訊範例: {', '.join(salary_mentions[:5])}
        熱門技能 (技能: 提及次數): {', '.join([f"{s[0]}: {s[1]}" for s in top_skills])}
        
        職缺摘要:
        {json.dumps(job_summary, ensure_ascii=False, indent=2)}
        
        請生成一份結構化的HTML報告，包含以下內容:
        1. 執行摘要: 簡短概述市場情況與找到的職缺概況
        2. 薪資分析: 分析薪資水平，識別高薪與低薪行業或公司
        3. 技能需求: 分析最常見的技能要求和資格
        4. 地區分布: 分析職缺在不同地區的分布
        5. 推薦機會: 推薦3-5個特別值得關注的優質職缺，並解釋原因
        6. 求職建議: 基於分析提供適合搜索者的建議
        
        以HTML格式回應，包含標題、圖表描述和格式化內容，使用繁體中文。
        """
        
        # 調用 OpenAI API 生成報告
        response = await openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "你是一位專業的職缺分析師，擅長分析就業市場趨勢並提供洞察。"},
                {"role": "user", "content": report_prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        report_html = response.choices[0].message.content
        
        # 保存報告到文件
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        report_file = f"104_{search_keyword}_報告_{timestamp}.html"
        
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_html)
        
        logger.info(f"報告已生成並保存至 {report_file}")
        return report_file
    
    except Exception as e:
        logger.error(f"生成職缺報告時出錯: {str(e)}")
        return None

async def scrape_104_jobs(job_title, page_limit=3):
    """
    爬取 104 人力銀行網站上的職缺資訊
    
    Args:
        job_title: 要搜尋的職位名稱
        page_limit: 要爬取的頁數限制
    
    Returns:
        包含職缺詳細資訊的 DataFrame
    """
    # 使用 OpenAI 優化搜索關鍵詞
    if use_ai:
        optimized_job_title = await generate_job_search_query(job_title)
        if optimized_job_title != job_title:
            logger.info(f"搜索關鍵詞已優化: '{job_title}' -> '{optimized_job_title}'")
            job_title = optimized_job_title
    
    logger.info(f"開始爬取「{job_title}」的職缺資訊...")
    
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
            
            # 如果啟用了 AI，嘗試使用 OpenAI 分析 HTML 提取職缺
            if use_ai:
                logger.info("嘗試使用 OpenAI 分析 HTML 提取職缺")
                ai_extracted_jobs = await extract_structured_job_info(html_content, '.job-list-item .job-name')
                if ai_extracted_jobs:
                    logger.info(f"OpenAI 成功提取 {len(ai_extracted_jobs)} 個職缺")
                    
                    # 將 OpenAI 提取的結果添加到數據中
                    for ai_job in ai_extracted_jobs:
                        job_data.append({
                            '職缺名稱': ai_job.get('title', ''),
                            '公司名稱': ai_job.get('company', ''),
                            '工作地點': ai_job.get('location', ''),
                            '薪資待遇': ai_job.get('salary', ''),
                            '連結': ai_job.get('link', ''),
                            '經驗要求': '',
                            '學歷要求': '',
                            '職缺描述': '',
                            '職缺標籤': 'AI提取'
                        })
            
            current_page = 1
            
            while current_page <= page_limit:
                logger.info(f"正在處理第 {current_page}/{page_limit} 頁...")
                
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
                
                # 判斷是否還有下一頁
                if current_page < page_limit:
                    try:
                        # 嘗試不同的下一頁按鈕選擇器
                        next_page_selectors = [
                            'button.js-more-page',
                            'button.btn-primary.js-more-page',
                            'button:has-text("下一頁")',
                            'a.page-next',
                            '.pagination-next button',
                            '.pagination li:last-child a',
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
                                # 檢查按鈕是否在視圖中，如果不在，則滾動到按鈕位置
                                await next_button.scroll_into_view_if_needed()
                                await asyncio.sleep(1)  # 等待滾動完成
                                
                                # 點擊下一頁按鈕
                                await next_button.click()
                                logger.info(f"已點擊第 {current_page} 頁的下一頁按鈕")
                            except Exception as e:
                                logger.warning(f"常規點擊失敗: {str(e)}, 嘗試使用 JavaScript 點擊")
                                await page.evaluate("button => button.click()", next_button)
                                logger.info("已使用 JavaScript 點擊下一頁按鈕")
                            
                            # 等待頁面加載
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            await asyncio.sleep(4 + random.random() * 2)  # 增加等待時間確保頁面完全加載
                            current_page += 1
                            
                        else:
                            # 如果找不到下一頁按鈕，嘗試透過URL參數直接跳到下一頁
                            try:
                                logger.warning("未找到下一頁按鈕，嘗試透過URL參數直接跳到下一頁")
                                current_url = page.url
                                next_page_number = current_page + 1
                                
                                # 檢查當前URL格式
                                if "page=" in current_url:
                                    # 如果URL中有page參數，直接替換
                                    next_url = re.sub(r'page=\d+', f'page={next_page_number}', current_url)
                                else:
                                    # 否則添加page參數
                                    separator = "&" if "?" in current_url else "?"
                                    next_url = f"{current_url}{separator}page={next_page_number}"
                                
                                logger.info(f"直接跳轉到下一頁，URL: {next_url}")
                                await page.goto(next_url, timeout=60000)
                                await page.wait_for_load_state('networkidle', timeout=30000)
                                await asyncio.sleep(3)
                                current_page += 1
                            except Exception as e:
                                logger.error(f"嘗試透過URL跳轉時失敗: {str(e)}")
                                logger.warning("無法找到下一頁按鈕或透過URL跳轉，爬蟲結束")
                                break
                    except Exception as e:
                        logger.error(f"切換頁面時發生錯誤: {str(e)}")
                        break
                else:
                    logger.info(f"已達到目標頁數限制 ({page_limit} 頁)，爬蟲結束")
                    break
                
        except Exception as e:
            logger.error(f"爬取過程中發生錯誤: {str(e)}")
        finally:
            # 關閉瀏覽器
            await browser.close()
    
    # 如果啟用了 AI 功能，分析職缺數據
    if use_ai and job_data:
        try:
            job_data = await analyze_job_descriptions(job_data)
            logger.info("職缺分析完成")
        except Exception as e:
            logger.error(f"分析職缺時出錯: {str(e)}")
    
    # 創建 DataFrame 並返回結果
    df = pd.DataFrame(job_data)
    logger.info(f"爬取完成，共獲取 {len(df)} 筆職缺資訊")
    return df, job_data, job_title

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
                                                                                    
    104人力銀行職缺爬蟲程式 v2.0 (AI增強版)
    使用說明：輸入職位名稱和要爬取的頁數，程式將自動爬取相關職缺信息並保存為Excel文件。
    使用 OpenAI API 增強分析功能，生成職缺分析報告。
    """
    print(banner)

async def main():
    """主程序"""
    print_banner()
    
    # 初始化 OpenAI 客戶端
    init_openai()
    
    if use_ai:
        print("AI 功能已啟用，將使用 OpenAI 增強爬蟲功能")
    else:
        print("AI 功能未啟用，將使用普通爬蟲模式")
    
    try:
        job_title = input("請輸入要搜尋的職位名稱: ")
        if not job_title:
            logger.error("職位名稱不能為空")
            return
        
        page_limit_input = input("請輸入要爬取的頁數 (建議 1-5 頁): ")
        page_limit = int(page_limit_input) if page_limit_input else 3
        
        if page_limit <= 0:
            logger.error("頁數必須大於 0")
            return
        
        logger.info(f"開始爬取「{job_title}」，共 {page_limit} 頁")
        
        start_time = time.time()
        df, job_data, actual_keyword = await scrape_104_jobs(job_title, page_limit)
        end_time = time.time()
        
        if not df.empty:
            # 將結果保存為 Excel 文件
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            filename = f"104_{actual_keyword}職缺_{timestamp}.xlsx"
            await save_to_excel(df, filename)
            
            # 顯示摘要
            print("\n" + "="*50)
            print("爬取結果摘要:")
            print("="*50)
            print(f"搜尋關鍵字：{actual_keyword}")
            print(f"爬取頁數：{page_limit}")
            print(f"共爬取到 {len(df)} 筆職缺資訊")
            
            # 如果啟用了 AI 分析，顯示趨勢分析
            if use_ai and 'AI分析_關鍵技能' in df.columns:
                print("\nAI 分析結果:")
                # 統計最常見的技能
                all_skills = []
                for skills in df['AI分析_關鍵技能'].dropna():
                    all_skills.extend([s.strip() for s in skills.split(',')])
                
                from collections import Counter
                top_skills = Counter(all_skills).most_common(5)
                
                print("熱門技能需求:")
                for skill, count in top_skills:
                    print(f"- {skill}: {count} 次提及")
                
                # 詢問用戶是否需要生成詳細報告
                generate_report = input("\n是否要生成詳細的職缺分析報告？(y/n): ").lower().strip() == 'y'
                if generate_report:
                    print("開始生成職缺分析報告，請稍候...")
                    report_file = await generate_job_report(job_data, actual_keyword)
                    if report_file:
                        print(f"\n分析報告已生成: {report_file}")
                        print("請使用瀏覽器打開該 HTML 文件查看詳細分析")
                    else:
                        print("無法生成分析報告")
            
            print(f"\n耗時：{end_time - start_time:.2f} 秒")
            print(f"資料已保存至：{filename}")
            print("="*50)
        else:
            logger.warning("未爬取到任何職缺資訊")
    except Exception as e:
        logger.error(f"程序執行過程中發生錯誤: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 