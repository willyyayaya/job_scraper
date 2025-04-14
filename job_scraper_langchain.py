import asyncio
import time
import pandas as pd
import re
import os
import logging
import random
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError

# 導入 dotenv 處理環境變數
from dotenv import load_dotenv

# 載入 .env 檔案中的環境變數
load_dotenv()

# LangChain 相關導入
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough, RunnableLambda
from langchain.output_parsers import PydanticOutputParser
from langchain.pydantic_v1 import BaseModel, Field
from langchain.memory import ConversationBufferMemory
from langchain.chains import SequentialChain, TransformChain, LLMChain

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("104_langchain_scraper")

# OpenAI API 配置
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DEFAULT_MODEL = "gpt-3.5-turbo-16k"  # 使用具有更大上下文的模型

# 全域變數用於存儲 API 金鑰
_global_api_key = None

def check_api_key():
    """檢查並設置 OpenAI API 金鑰"""
    global _global_api_key, OPENAI_API_KEY
    
    # 如果已經有全域 API 金鑰，直接使用
    if _global_api_key:
        return _global_api_key
    
    # 嘗試從環境變數獲取
    api_key = OPENAI_API_KEY
    
    if not api_key:
        # 提示用戶如何設置環境變數
        print("\n未在環境變數中找到 OpenAI API 金鑰。")
        print("您可以通過以下方式設置環境變數：")
        print("  - 在終端執行: export OPENAI_API_KEY=\"您的金鑰\"")
        print("  - 或在程式中設置: os.environ[\"OPENAI_API_KEY\"] = \"您的金鑰\"")
        print("\n或者您也可以直接輸入金鑰：")
        
        user_key = input("請輸入 OpenAI API 金鑰 (如要退出請按Ctrl+C): ").strip()
        if user_key:
            api_key = user_key
            os.environ["OPENAI_API_KEY"] = api_key
        else:
            logger.error("未提供 OpenAI API 金鑰，無法繼續")
            raise ValueError("未提供 OpenAI API 金鑰")
    
    # 將 API 金鑰存儲在全域變數中
    _global_api_key = api_key
    return api_key

# 創建一個目錄保存臨時數據
temp_dir = f"temp_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
os.makedirs(temp_dir, exist_ok=True)

# 定義 Pydantic 模型用於結構化輸出
class JobSkillsAnalysis(BaseModel):
    """職缺技能分析結果"""
    key_skills: List[str] = Field(description="關鍵技能列表")
    salary_evaluation: str = Field(description="薪資評估")
    highlights: str = Field(description="該職缺的特別亮點")
    
class JobAnalysisResult(BaseModel):
    """職缺分析結果集合"""
    jobs: List[JobSkillsAnalysis] = Field(description="每個職缺的分析結果")
    trends: str = Field(description="整體趨勢分析")


# ===== LangChain 組件定義 =====

def init_llm(temperature=0.2):
    """初始化 LLM 模型"""
    try:
        # 獲取 API 金鑰 (只會在第一次運行時請求輸入)
        api_key = check_api_key()
        
        llm = ChatOpenAI(
            model=DEFAULT_MODEL,
            temperature=temperature,
            openai_api_key=api_key
        )
        logger.info("LLM 初始化成功")
        return llm
    except Exception as e:
        logger.error(f"LLM 初始化失敗: {str(e)}")
        raise


def create_job_search_optimizer_chain():
    """創建優化搜索關鍵詞的 Chain"""
    prompt_template = ChatPromptTemplate.from_template(
        """你是一位求職專家，擅長優化職缺搜索關鍵詞以獲得更好的搜索結果。
        
        我想在104人力銀行搜索這樣的工作: {job_query}
        
        請幫我優化搜索關鍵詞，給出一個簡潔且有效的關鍵詞組合。
        直接返回優化後的關鍵詞，不要有任何解釋或前綴。
        """
    )
    
    llm = init_llm(temperature=0.3)
    
    chain = (
        {"job_query": RunnablePassthrough()}
        | prompt_template
        | llm
        | StrOutputParser()
    )
    
    return chain


def create_html_extraction_chain():
    """創建從HTML提取職缺信息的 Chain"""
    prompt_template = ChatPromptTemplate.from_template(
        """你是一位網頁分析專家，擅長從HTML中提取結構化信息。
        
        從以下HTML中提取職缺信息。請提取以下信息:
        1. 職缺標題
        2. 公司名稱
        3. 工作地點
        4. 薪資範圍
        5. 連結 (href 屬性)
        
        以JSON格式返回結果。格式如下:
        {{
            "jobs": [
                {{
                    "title": "職缺標題",
                    "company": "公司名稱",
                    "location": "工作地點",
                    "salary": "薪資範圍",
                    "link": "職缺連結"
                }},
                // 更多職缺...
            ]
        }}
        
        HTML: {html_content}
        """
    )
    
    llm = init_llm(temperature=0.1)
    
    # 定義一個函數來處理過長的HTML
    def truncate_html(html):
        # 截斷HTML以避免超過token限制
        return html[:30000]  # 取前30K字符
    
    chain = (
        {"html_content": RunnableLambda(truncate_html)}
        | prompt_template
        | llm
        | StrOutputParser()
        | RunnableLambda(lambda x: json.loads(x))  # 將字符串轉為JSON
    )
    
    return chain


def create_job_analysis_chain():
    """創建職缺分析 Chain"""
    prompt_template = ChatPromptTemplate.from_template(
        """你是一位專業的職缺分析專家，擅長從職缺描述中提取關鍵資訊並進行分析。
        
        分析以下職缺資訊，提取關鍵技能、要求和職缺亮點：
        
        {job_data}
        
        請提供以下分析：
        1. 對每個職缺提取3-5個關鍵技能或要求
        2. 評估每個職缺的薪資是否合理
        3. 指出特別有價值或特殊的職缺機會
        4. 總結這批職缺的共同趨勢或特點
        
        以JSON格式回覆，格式如下：
        {{
          "jobs": [
            {{
              "key_skills": ["技能1", "技能2", "技能3"],
              "salary_evaluation": "合理/偏低/偏高，原因...",
              "highlights": "該職缺的特別亮點..."
            }},
            ...
          ],
          "trends": "總體趨勢分析..."
        }}
        """
    )
    
    llm = init_llm(temperature=0.2)
    
    # 準備職缺數據的函數
    def prepare_job_data(jobs):
        if not jobs:
            return "沒有提供職缺數據進行分析。"
        
        batch_size = min(5, len(jobs))  # 每批最多處理5個職缺
        batch = jobs[:batch_size]
        
        text = ""
        for idx, job in enumerate(batch):
            text += f"職缺 {idx+1}:\n"
            text += f"標題: {job.get('職缺名稱', '')}\n"
            text += f"公司: {job.get('公司名稱', '')}\n"
            text += f"地點: {job.get('工作地點', '')}\n"
            text += f"薪資: {job.get('薪資待遇', '')}\n"
            text += f"描述: {job.get('職缺描述', '')[:300]}...\n\n"  # 只取描述的前300字元
        
        return text
    
    chain = (
        {"job_data": RunnableLambda(prepare_job_data)}
        | prompt_template
        | llm
        | StrOutputParser()
        | RunnableLambda(lambda x: json.loads(x))  # 將字符串轉為JSON
    )
    
    return chain


def create_job_report_chain():
    """創建職缺報告生成 Chain"""
    prompt_template = ChatPromptTemplate.from_template(
        """你是一位專業的職缺分析師，擅長分析就業市場趨勢並提供洞察。
        
        請基於以下職缺數據，生成一份詳細的職缺分析報告。
        
        搜索關鍵詞: {search_keyword}
        總職缺數: {total_jobs}
        薪資資訊: {salary_info}
        熱門技能: {top_skills}
        
        職缺摘要:
        {job_summary}
        
        請生成一份結構化的HTML報告，包含以下內容:
        1. 執行摘要: 簡短概述市場情況與找到的職缺概況
        2. 薪資分析: 分析薪資水平，識別高薪與低薪行業或公司
        3. 技能需求: 分析最常見的技能要求和資格
        4. 地區分布: 分析職缺在不同地區的分布
        5. 推薦機會: 推薦3-5個特別值得關注的優質職缺，並解釋原因
        6. 求職建議: 基於分析提供適合搜索者的建議
        
        以HTML格式回應，包含標題、圖表描述和格式化內容，使用繁體中文。
        """
    )
    
    llm = init_llm(temperature=0.7)
    
    # 準備報告數據的函數
    def prepare_report_data(input_data):
        jobs = input_data["jobs"]
        search_keyword = input_data["search_keyword"]
        
        # 提取薪資信息
        salary_mentions = []
        for job in jobs:
            salary = job.get("薪資待遇", "")
            if salary and "面議" not in salary:
                salary_mentions.append(salary)
        
        # 提取技能信息
        all_skills = []
        for job in jobs:
            skills = job.get("AI分析_關鍵技能", "")
            if skills:
                all_skills.extend([s.strip() for s in skills.split(',')])
        
        from collections import Counter
        top_skills = Counter(all_skills).most_common(10)
        
        # 準備職缺摘要
        job_summary = []
        for i, job in enumerate(jobs[:10]):  # 只取前10個職缺做摘要
            job_summary.append({
                "標題": job.get("職缺名稱", "未知"),
                "公司": job.get("公司名稱", "未知"),
                "地點": job.get("工作地點", ""),
                "薪資": job.get("薪資待遇", ""),
                "關鍵技能": job.get("AI分析_關鍵技能", "")
            })
        
        return {
            "search_keyword": search_keyword,
            "total_jobs": len(jobs),
            "salary_info": ", ".join(salary_mentions[:5]),
            "top_skills": ", ".join([f"{s[0]}: {s[1]}" for s in top_skills]),
            "job_summary": json.dumps(job_summary, ensure_ascii=False, indent=2)
        }
    
    chain = (
        RunnableLambda(prepare_report_data)
        | prompt_template
        | llm
        | StrOutputParser()
    )
    
    return chain


# ===== 爬蟲功能 =====

async def scrape_104_with_playwright(job_title, page_limit=3):
    """使用 Playwright 爬取 104 人力銀行職缺信息"""
    logger.info(f"開始爬取「{job_title}」的職缺資訊，頁數限制：{page_limit}")
    
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
            
            # 儲存搜尋結果頁面 HTML，便於分析
            html_content = await page.content()
            with open(f"{temp_dir}/search_result.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"已保存搜尋結果頁面 HTML 至 {temp_dir}/search_result.html")
            
            current_page = 1
            
            while current_page <= page_limit:
                logger.info(f"正在處理第 {current_page}/{page_limit} 頁...")
                
                # 提取當前頁面的職缺資訊
                job_selectors = [
                    '.job-list-item',
                    'article.job-list-item',
                    '[data-v-98e2e189] .job-summary',
                    '.container-fluid.job-list-container',
                    'div.job-list-container',
                    '.vue-recycle-scroller__item-view'
                ]
                
                job_items = []
                for selector in job_selectors:
                    items = await page.query_selector_all(selector)
                    if items and len(items) > 0:
                        logger.info(f"使用選擇器 '{selector}' 找到 {len(items)} 個職缺項目")
                        job_items = items
                        break
                
                if not job_items:
                    logger.warning("無法找到職缺項目，嘗試備用選擇器")
                    job_items = await page.query_selector_all('div.position-relative.bg-white')
                    if not job_items:
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
                        
                        for tag in tags:
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
                                child = await title_element.query_selector('a')
                                link = await child.get_attribute('href')
                        
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
                        continue
                
                # 每頁處理完後，儲存一次數據
                temp_df = pd.DataFrame(job_data)
                temp_filename = f"{temp_dir}/104_{job_title}_temp_page{current_page}.xlsx"
                temp_df.to_excel(temp_filename, index=False, engine='openpyxl')
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
                            'button.btn.js-more-jobs'
                        ]
                        
                        next_button = None
                        for selector in next_page_selectors:
                            try:
                                next_button = await page.query_selector(selector)
                                if next_button and await next_button.is_visible() and await next_button.is_enabled():
                                    break
                                else:
                                    next_button = None
                            except Exception as e:
                                logger.warning(f"檢查選擇器 {selector} 時出錯: {str(e)}")
                        
                        if next_button:
                            await next_button.scroll_into_view_if_needed()
                            await asyncio.sleep(1)
                            await next_button.click()
                            logger.info(f"已點擊第 {current_page} 頁的下一頁按鈕")
                            
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            await asyncio.sleep(3)
                            current_page += 1
                        else:
                            # 嘗試透過URL參數直接跳到下一頁
                            try:
                                current_url = page.url
                                next_page_number = current_page + 1
                                
                                if "page=" in current_url:
                                    next_url = re.sub(r'page=\d+', f'page={next_page_number}', current_url)
                                else:
                                    separator = "&" if "?" in current_url else "?"
                                    next_url = f"{current_url}{separator}page={next_page_number}"
                                
                                logger.info(f"直接跳轉到下一頁，URL: {next_url}")
                                await page.goto(next_url, timeout=60000)
                                await page.wait_for_load_state('networkidle', timeout=30000)
                                await asyncio.sleep(3)
                                current_page += 1
                            except Exception as e:
                                logger.error(f"嘗試透過URL跳轉時失敗: {str(e)}")
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
            await browser.close()
    
    return job_data


# ===== 主流程 Chain =====

class JobScraperChain:
    """整合爬蟲和分析的完整工作流"""
    
    def __init__(self):
        self.job_search_optimizer = create_job_search_optimizer_chain()
        self.html_extraction = create_html_extraction_chain()
        self.job_analysis = create_job_analysis_chain()
        self.report_generation = create_job_report_chain()
    
    async def run(self, job_title: str, page_limit: int = 3):
        """執行完整的工作流程"""
        results = {}
        
        try:
            # 步驟 1: 優化搜索關鍵詞
            logger.info("步驟 1: 優化搜索關鍵詞")
            optimized_query = await self.job_search_optimizer.ainvoke(job_title)
            logger.info(f"原始關鍵詞: '{job_title}' -> 優化關鍵詞: '{optimized_query}'")
            
            # 步驟 2: 使用 Playwright 爬取職缺數據
            logger.info(f"步驟 2: 爬取職缺數據，關鍵詞: '{optimized_query}'")
            job_data = await scrape_104_with_playwright(optimized_query, page_limit)
            logger.info(f"爬取完成，獲取 {len(job_data)} 筆職缺資訊")
            
            if not job_data:
                logger.warning("未爬取到任何職缺數據")
                return {"error": "未爬取到任何職缺數據"}
            
            # 步驟 3: 使用 LLM 分析職缺數據
            logger.info("步驟 3: 分析職缺數據")
            # 分批處理職缺數據以避免超過 token 限制
            analysis_results = []
            batch_size = 5
            
            for i in range(0, len(job_data), batch_size):
                batch = job_data[i:i+batch_size]
                logger.info(f"分析第 {i+1} 至 {i+len(batch)} 筆職缺")
                batch_result = await self.job_analysis.ainvoke(batch)
                
                # 將分析結果添加到職缺數據中
                for j, job_analysis in enumerate(batch_result.get("jobs", [])):
                    if i + j < len(job_data):
                        job_data[i+j]["AI分析_關鍵技能"] = ", ".join(job_analysis.get("key_skills", []))
                        job_data[i+j]["AI分析_薪資評估"] = job_analysis.get("salary_evaluation", "")
                        job_data[i+j]["AI分析_亮點"] = job_analysis.get("highlights", "")
                
                analysis_results.append(batch_result)
            
            logger.info("職缺分析完成")
            
            # 步驟 4: 生成分析報告
            logger.info("步驟 4: 生成分析報告")
            report_data = {
                "jobs": job_data,
                "search_keyword": optimized_query
            }
            
            report_html = await self.report_generation.ainvoke(report_data)
            
            # 保存報告到文件
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            report_file = f"104_{optimized_query}_報告_{timestamp}.html"
            
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report_html)
            
            logger.info(f"報告已生成並保存至 {report_file}")
            
            # 保存完整數據到 Excel
            df = pd.DataFrame(job_data)
            excel_file = f"104_{optimized_query}_職缺_{timestamp}.xlsx"
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"職缺數據已保存至 {excel_file}")
            
            # 整合結果
            results = {
                "optimized_query": optimized_query,
                "job_count": len(job_data),
                "report_file": report_file,
                "excel_file": excel_file,
                "analysis_summary": analysis_results[0].get("trends", "") if analysis_results else ""
            }
            
        except Exception as e:
            logger.error(f"執行工作流程時出錯: {str(e)}")
            results = {"error": str(e)}
        
        return results


def print_banner():
    """打印程序橫幅"""
    banner = """
    ██╗ ██████╗ ██╗  ██╗    ██╗      █████╗ ███╗   ██╗ ██████╗  ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗
    ██║██╔═████╗██║  ██║    ██║     ██╔══██╗████╗  ██║██╔════╝ ██╔════╝██║  ██║██╔══██╗██║████╗  ██║
    ██║██║██╔██║███████║    ██║     ███████║██╔██╗ ██║██║  ███╗██║     ███████║███████║██║██╔██╗ ██║
    ██║████╔╝██║╚════██║    ██║     ██╔══██║██║╚██╗██║██║   ██║██║     ██╔══██║██╔══██║██║██║╚██╗██║
    ██║╚██████╔╝     ██║    ███████╗██║  ██║██║ ╚████║╚██████╔╝╚██████╗██║  ██║██║  ██║██║██║ ╚████║
    ╚═╝ ╚═════╝      ╚═╝    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
                                                                                                   
    104人力銀行職缺爬蟲 LangChain + OpenAI 增強版
    
    工作流程:
    1. 優化搜索關鍵詞 → 2. 爬取職缺數據 → 3. 分析職缺數據 → 4. 生成分析報告
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
        
        page_limit_input = input("請輸入要爬取的頁數 (建議 1-5 頁): ")
        page_limit = int(page_limit_input) if page_limit_input else 3
        
        if page_limit <= 0:
            logger.error("頁數必須大於 0")
            return
        
        logger.info(f"開始執行工作流程，搜尋關鍵詞: {job_title}，頁數: {page_limit}")
        
        start_time = time.time()
        
        # 執行完整工作流程
        scraper_chain = JobScraperChain()
        results = await scraper_chain.run(job_title, page_limit)
        
        end_time = time.time()
        
        # 顯示結果摘要
        print("\n" + "="*50)
        print("執行結果摘要:")
        print("="*50)
        
        if "error" in results:
            print(f"執行過程中發生錯誤: {results['error']}")
        else:
            print(f"搜尋關鍵詞: {job_title} → 優化關鍵詞: {results['optimized_query']}")
            print(f"共爬取到 {results['job_count']} 筆職缺資訊")
            print(f"職缺數據已保存至: {results['excel_file']}")
            print(f"分析報告已生成: {results['report_file']}")
            
            if results.get('analysis_summary'):
                print("\n市場趨勢分析:")
                print(results['analysis_summary'])
        
        print(f"\n執行時間: {end_time - start_time:.2f} 秒")
        print("="*50)
        
    except Exception as e:
        logger.error(f"程序執行過程中發生錯誤: {str(e)}")
        print(f"程序執行過程中發生錯誤: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 