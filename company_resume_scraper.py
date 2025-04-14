import asyncio
import time
import pandas as pd
import os
import logging
import random
import json
import aiofiles
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError

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
    def __init__(self, username="", password="", headless=False, 
                 download_photos=True, max_pages=5, delay_range=(1, 3)):
        self.username = username  # 104企業會員帳號
        self.password = password  # 104企業會員密碼
        self.headless = headless  # 是否隱藏瀏覽器
        self.download_photos = download_photos  # 是否下載照片
        self.max_pages = max_pages  # 最大爬取頁數
        self.delay_range = delay_range  # 請求延遲範圍(秒)
        
        # 建立輸出目錄
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_dir = f"resume_data_{self.timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        if self.download_photos:
            self.photos_dir = os.path.join(self.output_dir, "photos")
            os.makedirs(self.photos_dir, exist_ok=True)

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
        self.browser = await playwright.chromium.launch(headless=self.config.headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self.context.new_page()
        logger.info("瀏覽器初始化成功")
    
    async def login(self):
        """登入104企業會員"""
        if not self.page:
            await self.initialize()
        
        logger.info("開始登入104企業會員")
        await self.page.goto('https://employers.104.com.tw/cust/login', timeout=60000)
        
        # 等待登入頁面加載
        try:
            await self.page.wait_for_selector('input[name="username"]', timeout=20000)
            
            # 輸入帳號密碼
            await self.page.fill('input[name="username"]', self.config.username)
            await self.page.fill('input[name="password"]', self.config.password)
            logger.info("已輸入帳號密碼")
            
            # 點擊登入按鈕
            login_button = await self.page.query_selector('button[type="submit"]')
            if login_button:
                await login_button.click()
                logger.info("已點擊登入按鈕")
            else:
                logger.error("找不到登入按鈕")
                return False
            
            # 等待登入完成
            try:
                # 檢查是否有驗證碼
                captcha_selector = await self.page.query_selector('.captcha-img', timeout=5000)
                if captcha_selector:
                    logger.warning("需要輸入驗證碼，請手動完成驗證")
                    # 等待用戶手動處理驗證碼
                    input("請在瀏覽器中完成驗證碼，然後按Enter繼續...")
            except:
                pass  # 無驗證碼，繼續執行
            
            # 等待登入後的頁面
            await self.page.wait_for_load_state('networkidle', timeout=30000)
            
            # 檢查是否登入成功
            current_url = self.page.url
            if "employers.104.com.tw" in current_url and "/cust/login" not in current_url:
                logger.info("登入成功")
                return True
            else:
                logger.error(f"登入失敗，當前URL: {current_url}")
                return False
            
        except Exception as e:
            logger.error(f"登入過程中出錯: {str(e)}")
            return False
    
    async def search_resumes(self, keyword=""):
        """搜索求職者履歷"""
        if not self.page:
            logger.error("尚未初始化瀏覽器")
            return False
        
        try:
            # 前往人才搜尋頁面
            logger.info("前往人才搜尋頁面")
            await self.page.goto('https://employers.104.com.tw/resume/search', timeout=60000)
            await self.page.wait_for_load_state('networkidle')
            
            # 檢查是否有彈窗，如有則關閉
            try:
                close_button = await self.page.query_selector('button.closeButton', timeout=5000)
                if close_button:
                    await close_button.click()
                    logger.info("已關閉彈窗")
            except:
                pass  # 無彈窗，繼續執行
            
            # 如果有關鍵詞，則輸入搜索條件
            if keyword:
                logger.info(f"搜索關鍵詞: {keyword}")
                
                # 等待搜索框加載
                await self.page.wait_for_selector('input[placeholder*="關鍵字"]', timeout=20000)
                await self.page.fill('input[placeholder*="關鍵字"]', keyword)
                
                # 點擊搜索按鈕
                search_button = await self.page.query_selector('button.btn-primary')
                if search_button:
                    await search_button.click()
                    logger.info("已點擊搜索按鈕")
                else:
                    logger.warning("找不到搜索按鈕，嘗試使用Enter鍵搜索")
                    await self.page.press('input[placeholder*="關鍵字"]', 'Enter')
            
            # 等待搜索結果加載
            await self.page.wait_for_load_state('networkidle', timeout=30000)
            logger.info("搜索結果已加載")
            return True
            
        except Exception as e:
            logger.error(f"搜索履歷時出錯: {str(e)}")
            return False
    
    async def extract_resume_cards(self):
        """提取當前頁面中的履歷卡片數據"""
        resumes = []
        
        try:
            # 等待履歷卡片加載
            await self.page.wait_for_selector('.resume-list-item, .resume-card', timeout=20000)
            
            # 獲取所有履歷卡片
            cards = await self.page.query_selector_all('.resume-list-item, .resume-card')
            logger.info(f"找到 {len(cards)} 個履歷卡片")
            
            for idx, card in enumerate(cards):
                try:
                    # 提取基本資訊
                    name_element = await card.query_selector('.name, .user-name')
                    name = await name_element.inner_text() if name_element else "未提供姓名"
                    
                    # 提取照片URL
                    photo_element = await card.query_selector('.photo img, .avatar img')
                    photo_url = ""
                    if photo_element:
                        photo_url = await photo_element.get_attribute('src')
                        if photo_url and photo_url.startswith('//'):
                            photo_url = 'https:' + photo_url
                    
                    # 提取其他資訊
                    job_element = await card.query_selector('.job, .title')
                    job = await job_element.inner_text() if job_element else ""
                    
                    exp_element = await card.query_selector('.exp, .experience')
                    exp = await exp_element.inner_text() if exp_element else ""
                    
                    edu_element = await card.query_selector('.edu, .education')
                    edu = await edu_element.inner_text() if edu_element else ""
                    
                    # 提取履歷詳情連結
                    link = ""
                    link_element = await card.query_selector('a.resume-link, a[href*="resume"]')
                    if link_element:
                        link = await link_element.get_attribute('href')
                        if link and link.startswith('/'):
                            link = 'https://employers.104.com.tw' + link
                    
                    # 整合資料
                    resume_data = {
                        '姓名': name,
                        '職稱': job,
                        '工作經驗': exp,
                        '學歷': edu,
                        '照片URL': photo_url,
                        '履歷連結': link,
                        '爬取時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    # 下載照片（如果設置了下載照片）
                    if self.config.download_photos and photo_url:
                        photo_filename = f"{name}_{idx}_{self.config.timestamp}.jpg"
                        photo_path = os.path.join(self.config.photos_dir, photo_filename)
                        try:
                            # 創建新頁面來下載圖片，避免干擾主頁面
                            img_page = await self.context.new_page()
                            await img_page.goto(photo_url)
                            # 等待圖片加載
                            await img_page.wait_for_load_state('domcontentloaded')
                            # 截圖並保存
                            await img_page.screenshot(path=photo_path)
                            await img_page.close()
                            resume_data['照片本地路徑'] = photo_path
                            logger.info(f"已下載照片: {name}")
                        except Exception as e:
                            logger.error(f"下載照片時出錯: {str(e)}")
                    
                    resumes.append(resume_data)
                    logger.info(f"已提取 {name} 的資料")
                    
                except Exception as e:
                    logger.error(f"提取履歷卡片數據時出錯: {str(e)}")
            
            return resumes
            
        except Exception as e:
            logger.error(f"提取履歷卡片時出錯: {str(e)}")
            return []
    
    async def has_next_page(self):
        """檢查是否有下一頁"""
        try:
            # 尋找下一頁按鈕
            next_btn = await self.page.query_selector('a.next-page:not(.disabled), li.next:not(.disabled) a')
            return next_btn is not None
        except:
            return False
    
    async def go_to_next_page(self):
        """前往下一頁"""
        try:
            # 點擊下一頁按鈕
            next_btn = await self.page.query_selector('a.next-page:not(.disabled), li.next:not(.disabled) a')
            if next_btn:
                await next_btn.click()
                # 隨機延遲以避免被封
                delay = random.uniform(*self.config.delay_range)
                logger.info(f"等待 {delay:.2f} 秒後加載下一頁")
                await asyncio.sleep(delay)
                await self.page.wait_for_load_state('networkidle')
                return True
            return False
        except Exception as e:
            logger.error(f"前往下一頁時出錯: {str(e)}")
            return False
    
    async def get_resume_details(self, link):
        """獲取求職者詳細資料"""
        if not link:
            return {}
        
        try:
            # 創建新頁面查看詳情，避免干擾主流程
            detail_page = await self.context.new_page()
            await detail_page.goto(link, timeout=60000)
            await detail_page.wait_for_load_state('networkidle')
            
            # 提取詳細資訊
            details = {}
            
            # 基本資料區塊
            basic_info = {}
            basic_section = await detail_page.query_selector('.basic-section, .profile-section')
            if basic_section:
                # 姓名
                name_element = await basic_section.query_selector('.name, .candidate-name')
                if name_element:
                    basic_info['姓名'] = await name_element.inner_text()
                
                # 年齡/性別
                age_gender_element = await basic_section.query_selector('.age-gender, .profile-meta')
                if age_gender_element:
                    basic_info['年齡性別'] = await age_gender_element.inner_text()
                
                # 其他基本資訊
                info_items = await basic_section.query_selector_all('.info-item, .profile-item')
                for item in info_items:
                    label_element = await item.query_selector('.label, .item-label')
                    value_element = await item.query_selector('.value, .item-value')
                    
                    if label_element and value_element:
                        label = await label_element.inner_text()
                        value = await value_element.inner_text()
                        basic_info[label.replace('：', '').strip()] = value.strip()
            
            details['基本資料'] = basic_info
            
            # 工作經驗
            experiences = []
            exp_section = await detail_page.query_selector('.experience-section, .work-experience')
            if exp_section:
                exp_items = await exp_section.query_selector_all('.experience-item, .work-item')
                for item in exp_items:
                    exp = {}
                    
                    company_element = await item.query_selector('.company, .company-name')
                    if company_element:
                        exp['公司'] = await company_element.inner_text()
                    
                    title_element = await item.query_selector('.title, .job-title')
                    if title_element:
                        exp['職稱'] = await title_element.inner_text()
                    
                    period_element = await item.query_selector('.period, .job-period')
                    if period_element:
                        exp['時間'] = await period_element.inner_text()
                    
                    desc_element = await item.query_selector('.description, .job-description')
                    if desc_element:
                        exp['描述'] = await desc_element.inner_text()
                    
                    experiences.append(exp)
            
            details['工作經驗'] = experiences
            
            # 教育背景
            educations = []
            edu_section = await detail_page.query_selector('.education-section, .education')
            if edu_section:
                edu_items = await edu_section.query_selector_all('.education-item, .education-entry')
                for item in edu_items:
                    edu = {}
                    
                    school_element = await item.query_selector('.school, .school-name')
                    if school_element:
                        edu['學校'] = await school_element.inner_text()
                    
                    major_element = await item.query_selector('.major, .department')
                    if major_element:
                        edu['科系'] = await major_element.inner_text()
                    
                    degree_element = await item.query_selector('.degree, .degree-name')
                    if degree_element:
                        edu['學位'] = await degree_element.inner_text()
                    
                    period_element = await item.query_selector('.period, .education-period')
                    if period_element:
                        edu['時間'] = await period_element.inner_text()
                    
                    educations.append(edu)
            
            details['教育背景'] = educations
            
            # 技能專長
            skills = []
            skill_section = await detail_page.query_selector('.skill-section, .skills')
            if skill_section:
                skill_items = await skill_section.query_selector_all('.skill-item, .skill')
                for item in skill_items:
                    skill_text = await item.inner_text()
                    skills.append(skill_text.strip())
            
            details['技能專長'] = skills
            
            # 關閉詳情頁面
            await detail_page.close()
            
            return details
            
        except Exception as e:
            logger.error(f"獲取履歷詳情時出錯: {str(e)}")
            return {}
    
    async def scrape_all_resumes(self, keyword="", get_details=False):
        """爬取所有符合條件的求職者資料"""
        all_resumes = []
        
        # 搜索求職者
        search_success = await self.search_resumes(keyword)
        if not search_success:
            logger.error("搜索失敗，無法繼續爬取")
            return all_resumes
        
        # 儲存搜索結果頁面
        html_path = os.path.join(self.config.output_dir, "search_result.html")
        html_content = await self.page.content()
        async with aiofiles.open(html_path, 'w', encoding='utf-8') as f:
            await f.write(html_content)
        logger.info(f"已保存搜索結果頁面: {html_path}")
        
        # 爬取所有頁面
        current_page = 1
        while current_page <= self.config.max_pages:
            logger.info(f"正在處理第 {current_page} 頁")
            
            # 提取當前頁面的履歷資料
            page_resumes = await self.extract_resume_cards()
            
            # 是否獲取詳細資料
            if get_details and page_resumes:
                for idx, resume in enumerate(page_resumes):
                    if '履歷連結' in resume and resume['履歷連結']:
                        logger.info(f"獲取 {resume['姓名']} 的詳細資料 ({idx+1}/{len(page_resumes)})")
                        details = await self.get_resume_details(resume['履歷連結'])
                        resume['詳細資料'] = details
                        # 隨機延遲，避免頻繁請求
                        await asyncio.sleep(random.uniform(1, 2))
            
            all_resumes.extend(page_resumes)
            
            # 儲存當前進度
            self.save_progress(all_resumes, current_page)
            
            # 檢查是否有下一頁並跳轉
            has_next = await self.has_next_page()
            if has_next and current_page < self.config.max_pages:
                next_success = await self.go_to_next_page()
                if next_success:
                    current_page += 1
                else:
                    logger.warning("無法前往下一頁，爬取結束")
                    break
            else:
                logger.info("已到達最後一頁或達到頁數限制")
                break
        
        logger.info(f"爬取完成，共獲取 {len(all_resumes)} 份履歷")
        return all_resumes
    
    def save_progress(self, resumes, page_num):
        """保存當前進度"""
        try:
            # 保存至Excel
            df = pd.DataFrame(resumes)
            excel_path = os.path.join(self.config.output_dir, f"履歷資料_第{page_num}頁.xlsx")
            df.to_excel(excel_path, index=False)
            logger.info(f"已保存進度至Excel: {excel_path}")
            
            # 保存至JSON
            json_path = os.path.join(self.config.output_dir, f"履歷資料_第{page_num}頁.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(resumes, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存進度至JSON: {json_path}")
            
        except Exception as e:
            logger.error(f"保存進度時出錯: {str(e)}")
    
    async def save_final_results(self, resumes, keyword=""):
        """保存最終結果"""
        try:
            # 創建檔名
            filename_base = f"104履歷_{keyword}_{self.config.timestamp}" if keyword else f"104履歷_{self.config.timestamp}"
            
            # 保存至Excel
            df = pd.DataFrame(resumes)
            excel_path = os.path.join(self.config.output_dir, f"{filename_base}.xlsx")
            df.to_excel(excel_path, index=False)
            logger.info(f"已保存最終結果至Excel: {excel_path}")
            
            # 保存至JSON
            json_path = os.path.join(self.config.output_dir, f"{filename_base}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(resumes, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存最終結果至JSON: {json_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"保存最終結果時出錯: {str(e)}")
            return False
    
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
    
    # 取得設定
    username = input("請輸入104企業會員帳號: ")
    password = input("請輸入104企業會員密碼: ")
    keyword = input("請輸入搜索關鍵詞 (直接按Enter搜索全部): ")
    
    try:
        max_pages = int(input("請輸入要爬取的頁數 (預設5頁): ") or "5")
    except:
        max_pages = 5
    
    get_details = input("是否獲取詳細履歷資料? (y/n，預設n): ").lower() == 'y'
    download_photos = input("是否下載求職者照片? (y/n，預設y): ").lower() != 'n'
    headless = input("是否隱藏瀏覽器? (y/n，預設n): ").lower() == 'y'
    
    # 創建設定
    config = ResumeScraperConfig(
        username=username,
        password=password,
        headless=headless,
        download_photos=download_photos,
        max_pages=max_pages
    )
    
    # 創建爬蟲實例
    scraper = ResumeScraper(config)
    
    try:
        # 初始化瀏覽器
        await scraper.initialize()
        
        # 登入
        login_success = await scraper.login()
        if not login_success:
            print("登入失敗，程序結束")
            return
        
        # 爬取履歷
        print(f"開始爬取{'「'+keyword+'」的' if keyword else ''}求職者資料...")
        resumes = await scraper.scrape_all_resumes(keyword, get_details)
        
        # 保存結果
        if resumes:
            await scraper.save_final_results(resumes, keyword)
            print(f"爬取完成，共獲取 {len(resumes)} 份履歷")
            print(f"結果已保存至目錄: {config.output_dir}")
        else:
            print("未找到任何符合條件的履歷")
    
    except Exception as e:
        logger.error(f"程序執行時出錯: {str(e)}")
        print(f"程序執行時出錯: {str(e)}")
    
    finally:
        # 關閉瀏覽器
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main()) 