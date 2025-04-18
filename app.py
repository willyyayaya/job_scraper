import streamlit as st
import asyncio
import os
import json
import time
import pandas as pd
import io
from company_resume_scraper import ResumeScraper, ResumeScraperConfig
# 導入104職缺和公司搜尋功能
from job_scraper_final import scrape_104_jobs, scrape_104_companies, save_to_excel, clean_text_for_excel

# 初始化session_state用於保存爬蟲結果
if 'scrape_results' not in st.session_state:
    st.session_state.scrape_results = None
if 'has_results' not in st.session_state:
    st.session_state.has_results = False
if 'output_dir' not in st.session_state:
    st.session_state.output_dir = None
if 'scrape_type' not in st.session_state:
    st.session_state.scrape_type = "resume"  # 默認為履歷爬蟲

# 函數：爬蟲完成時保存結果到session_state
def save_results_to_session(results, output_dir=None):
    st.session_state.scrape_results = results
    st.session_state.has_results = True
    if output_dir:
        st.session_state.output_dir = output_dir

# 設置頁面配置
st.set_page_config(page_title="104爬蟲工具", layout="wide")

# 標題與介紹
st.title("104人力銀行爬蟲工具")
st.markdown("此工具僅供學習研究使用，請勿用於商業或非法用途，並遵守104相關使用條款及個人資料保護法")

# 側邊欄配置檔案管理
with st.sidebar:
    st.header("設定管理")
    
    # 選擇爬蟲類型
    scrape_type = st.radio(
        "選擇爬蟲類型:",
        ["履歷爬蟲", "職缺爬蟲", "公司爬蟲"],
        index=0,
        help="選擇要進行的爬蟲類型"
    )
    
    # 更新session state
    st.session_state.scrape_type = "resume" if scrape_type == "履歷爬蟲" else "job" if scrape_type == "職缺爬蟲" else "company"
    
    # 瀏覽器設定
    st.subheader("瀏覽器設定")
    show_browser = st.checkbox("顯示瀏覽器視窗", value=True, help="勾選此項可查看爬蟲運行過程，建議保持勾選")
    if not show_browser:
        st.warning("不顯示瀏覽器視窗可能會導致部分網站驗證失敗")
    
    # 儲存瀏覽器設定到session_state
    st.session_state.show_browser = show_browser
    
    # 檢查是否有已儲存的使用者資訊
    config_file = "user_config.json"
    saved_config = {}
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                saved_config = json.load(f)
            st.success("找到已儲存的帳號資訊")
        except:
            st.warning("讀取儲存的帳號資訊時出錯")
    
    use_saved = False
    if saved_config.get("username"):
        use_saved = st.checkbox(f"使用已儲存的帳號 ({saved_config.get('username')})", value=True)

# 建立履歷爬蟲表單
if st.session_state.scrape_type == "resume":
    st.header("104履歷爬蟲")
    
    with st.form("resume_scraper_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            if use_saved and saved_config.get("username") and saved_config.get("password"):
                username = st.text_input("104企業會員帳號", value=saved_config.get("username"))
                password = st.text_input("104企業會員密碼", value=saved_config.get("password"), type="password")
            else:
                username = st.text_input("104企業會員帳號")
                password = st.text_input("104企業會員密碼", type="password")
        
        with col2:
            keyword = st.text_input("搜索關鍵詞 (直接留空搜索全部)")
            page_limit = st.number_input("要爬取的頁數", min_value=1, value=1)
            
        save_account = st.checkbox("記住帳號密碼")
        
        col3, col4 = st.columns([1, 3])
        with col3:
            submitted = st.form_submit_button("開始爬取")
    
    # 處理履歷爬蟲表單提交
    if submitted:
        # 儲存帳號密碼（如選擇）
        if save_account:
            try:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump({"username": username, "password": password}, f)
                st.success("已儲存帳號資訊")
            except Exception as e:
                st.error(f"儲存帳號資訊失敗: {str(e)}")
        
        # 建立進度顯示區域
        progress_bar = st.progress(0)
        status_text = st.empty()
        result_area = st.empty()
        
        # 建立爬蟲配置
        status_text.info("正在初始化爬蟲設定...")
        
        config = ResumeScraperConfig(
            username=username,
            password=password,
            search_keyword=keyword,
            page_limit=int(page_limit)
        )
        
        # 定義用於更新進度的回調
        class ScraperCallback:
            def __init__(self, status_text, progress_bar):
                self.status_text = status_text
                self.progress_bar = progress_bar
                self.last_progress = 0
            
            def update(self, message, progress=None):
                self.status_text.info(message)
                if progress is not None:
                    self.progress_bar.progress(progress)
                    self.last_progress = progress
        
        # 建立回調物件
        callback = ScraperCallback(status_text, progress_bar)
        
        # 定義運行爬蟲的異步函數
        async def run_scraping():
            scraper = ResumeScraper(config)
            try:
                # 初始化瀏覽器
                callback.update("正在初始化瀏覽器...", 5)
                await scraper.initialize()
                
                # 登入
                callback.update("正在登入104網站...", 15)
                login_success = await scraper.login()
                if not login_success:
                    callback.update("登入失敗，請檢查您的帳號和密碼", 0)
                    return False
                
                callback.update("登入成功！", 30)
                
                # 搜尋
                if config.search_keyword:
                    callback.update(f"正在搜尋關鍵字: {config.search_keyword}...", 40)
                    search_success = await scraper.search()
                    if not search_success:
                        callback.update("搜尋失敗", 0)
                        return False
                    
                    callback.update("搜尋成功，開始提取履歷資料...", 50)
                    
                    # 提取結果
                    results = await scraper.extract_results()
                    
                    if results and len(results) > 0:
                        callback.update(f"爬蟲完成，共獲取 {len(results)} 份履歷！", 100)
                        return results
                    else:
                        callback.update("未找到符合條件的履歷", 100)
                        return []
                else:
                    callback.update("未設定搜尋關鍵字，搜尋全部結果", 40)
                    search_success = await scraper.search()
                    if not search_success:
                        callback.update("搜尋失敗", 0)
                        return False
                    
                    callback.update("搜尋成功，開始提取履歷資料...", 50)
                    
                    # 提取結果
                    results = await scraper.extract_results()
                    
                    if results and len(results) > 0:
                        callback.update(f"爬蟲完成，共獲取 {len(results)} 份履歷！", 100)
                        return results
                    else:
                        callback.update("未找到符合條件的履歷", 100)
                        return []
            except Exception as e:
                callback.update(f"爬蟲過程發生錯誤: {str(e)}", 0)
                return False
            finally:
                # 關閉瀏覽器
                await scraper.close()
        
        # 執行爬蟲
        with result_area:
            with st.spinner('爬蟲正在執行中，請耐心等待...'):
                results = asyncio.run(run_scraping())
                
                if results and isinstance(results, list):
                    # 保存結果到session_state以確保下載按鈕可用
                    save_results_to_session(results, config.output_dir if hasattr(config, 'output_dir') else None)
                    
                    st.success(f"爬蟲完成，共獲取 {len(results)} 份履歷")
                    
                    if hasattr(config, 'output_dir'):
                        st.info(f"結果已保存至目錄: {config.output_dir}")
                    
                    # 顯示履歷資料預覽
                    if len(results) > 0:
                        st.subheader("履歷資料預覽")
                        
                        # 轉換為DataFrame
                        try:
                            df = pd.DataFrame(results)
                            st.dataframe(df)
                        except Exception as e:
                            st.error(f"顯示數據預覽時出錯: {str(e)}")
                            st.write("原始數據:", results[:3])
                elif results is True:
                    st.success("爬蟲流程已完成")
                    # 設置標記以便顯示下載按鈕
                    st.session_state.has_results = True
                else:
                    st.error("爬蟲未能獲取有效結果")

# 職缺爬蟲表單
elif st.session_state.scrape_type == "job":
    st.header("104職缺爬蟲")
    
    with st.form("job_scraper_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            job_title = st.text_input("請輸入要搜尋的職位名稱", help="例如：軟體工程師、產品經理、UI設計師")
        
        with col2:
            page_limit = st.number_input("要爬取的頁數", min_value=1, value=3, help="設定要爬取的頁數（0表示不限制頁數）")
            unlimited_pages = st.checkbox("不限制頁數", help="勾選此項將爬取所有可找到的頁面，可能需要較長時間")
        
        submitted = st.form_submit_button("開始爬取職缺")
    
    # 處理職缺爬蟲表單提交
    if submitted:
        if not job_title:
            st.error("請輸入要搜尋的職位名稱")
        else:
            # 設置進度顯示
            progress_placeholder = st.empty()
            status_text = st.empty()
            result_area = st.empty()
            
            status_text.info("正在準備爬取職缺資訊...")
            
            # 設置頁數限制
            if unlimited_pages:
                actual_page_limit = float('inf')
                status_text.warning("您選擇了不限制頁數，爬蟲可能需要較長時間...")
            else:
                actual_page_limit = page_limit
            
            # 執行爬蟲
            with result_area:
                with st.spinner(f'正在爬取「{job_title}」的職缺資訊，請耐心等待...'):
                    start_time = time.time()
                    
                    # 執行爬蟲函數
                    try:
                        # 檢查瀏覽器設置
                        browser_visible = "show_browser" in st.session_state and st.session_state.show_browser
                        # 將瀏覽器設置傳遞給爬蟲函數
                        df = asyncio.run(scrape_104_jobs(job_title, actual_page_limit, headless=(not browser_visible)))
                        end_time = time.time()
                        
                        if not df.empty:
                            # 保存結果到session_state
                            st.session_state.scrape_results = df
                            st.session_state.has_results = True
                            st.session_state.scrape_type = "job"
                            
                            # 更新狀態訊息
                            status_text.success(f"爬蟲完成！共獲取 {len(df)} 筆職缺資訊")
                            
                            # 顯示結果摘要
                            st.success(f"爬取完成！共獲取 {len(df)} 筆職缺資訊")
                            st.info(f"耗時：{end_time - start_time:.2f} 秒")
                            
                            # 顯示數據預覽
                            st.subheader("職缺資料預覽")
                            st.dataframe(df.head(10))
                            
                            # 保存Excel文件
                            timestamp = time.strftime('%Y%m%d_%H%M%S')
                            filename = f"104_{job_title}職缺_{timestamp}.xlsx"
                            
                            # 清理數據以防止Excel錯誤
                            for column in df.columns:
                                if df[column].dtype == 'object':  # 只處理字符串類型的列
                                    df[column] = df[column].apply(lambda x: clean_text_for_excel(x) if isinstance(x, str) else x)
                            
                            df.to_excel(filename, index=False)
                            st.info(f"資料已保存至檔案：{filename}")
                            
                            # 提供下載按鈕
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                df.to_excel(writer, index=False)
                            buffer.seek(0)
                            
                            st.download_button(
                                label="📊 下載職缺Excel檔案",
                                data=buffer,
                                file_name=filename,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        else:
                            status_text.warning("未爬取到任何職缺資訊")
                            st.warning("未爬取到任何職缺資訊，請檢查搜尋關鍵字或嘗試其他關鍵字")
                    except Exception as e:
                        status_text.error(f"爬蟲過程中發生錯誤")
                        st.error(f"爬蟲過程中發生錯誤：{str(e)}")

# 公司爬蟲表單
elif st.session_state.scrape_type == "company":
    st.header("104公司爬蟲")
    
    with st.form("company_scraper_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            company_name = st.text_input("請輸入要搜尋的公司名稱", help="例如：台積電、鴻海、國泰人壽")
        
        with col2:
            page_limit = st.number_input("要爬取的頁數", min_value=1, value=3, help="設定要爬取的頁數（0表示不限制頁數）")
            unlimited_pages = st.checkbox("不限制頁數", help="勾選此項將爬取所有可找到的頁面，可能需要較長時間")
        
        submitted = st.form_submit_button("開始爬取公司")
    
    # 處理公司爬蟲表單提交
    if submitted:
        if not company_name:
            st.error("請輸入要搜尋的公司名稱")
        else:
            # 設置進度顯示
            progress_placeholder = st.empty()
            status_text = st.empty()
            result_area = st.empty()
            
            status_text.info("正在準備爬取公司資訊...")
            
            # 設置頁數限制
            if unlimited_pages:
                actual_page_limit = float('inf')
                status_text.warning("您選擇了不限制頁數，爬蟲可能需要較長時間...")
            else:
                actual_page_limit = page_limit
            
            # 執行爬蟲
            with result_area:
                with st.spinner(f'正在爬取「{company_name}」的公司資訊，請耐心等待...'):
                    start_time = time.time()
                    
                    # 執行爬蟲函數
                    try:
                        # 檢查瀏覽器設置
                        browser_visible = "show_browser" in st.session_state and st.session_state.show_browser
                        # 將瀏覽器設置傳遞給爬蟲函數
                        df = asyncio.run(scrape_104_companies(company_name, actual_page_limit, headless=(not browser_visible)))
                        end_time = time.time()
                        
                        if not df.empty:
                            # 保存結果到session_state
                            st.session_state.scrape_results = df
                            st.session_state.has_results = True
                            st.session_state.scrape_type = "company"
                            
                            # 更新狀態訊息
                            status_text.success(f"爬蟲完成！共獲取 {len(df)} 筆公司資訊")
                            
                            # 顯示結果摘要
                            st.success(f"爬取完成！共獲取 {len(df)} 筆公司資訊")
                            st.info(f"耗時：{end_time - start_time:.2f} 秒")
                            
                            # 顯示數據預覽
                            st.subheader("公司資料預覽")
                            st.dataframe(df.head(10))
                            
                            # 保存Excel文件
                            timestamp = time.strftime('%Y%m%d_%H%M%S')
                            filename = f"104_{company_name}公司_{timestamp}.xlsx"
                            
                            # 清理數據以防止Excel錯誤
                            for column in df.columns:
                                if df[column].dtype == 'object':  # 只處理字符串類型的列
                                    df[column] = df[column].apply(lambda x: clean_text_for_excel(x) if isinstance(x, str) else x)
                            
                            df.to_excel(filename, index=False)
                            st.info(f"資料已保存至檔案：{filename}")
                            
                            # 提供下載按鈕
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                df.to_excel(writer, index=False)
                            buffer.seek(0)
                            
                            st.download_button(
                                label="📊 下載公司Excel檔案",
                                data=buffer,
                                file_name=filename,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        else:
                            status_text.warning("未爬取到任何公司資訊")
                            st.warning("未爬取到任何公司資訊，請檢查搜尋關鍵字或嘗試其他關鍵字")
                    except Exception as e:
                        status_text.error(f"爬蟲過程中發生錯誤")
                        st.error(f"爬蟲過程中發生錯誤：{str(e)}")

# 獨立的下載區塊 - 只顯示履歷爬蟲的結果下載選項
if st.session_state.has_results and st.session_state.scrape_results is not None and st.session_state.scrape_type == "resume":
    results = st.session_state.scrape_results
    
    st.header("📥 下載履歷資料")
    st.info(f"您有 {len(results)} 份履歷資料可供下載")
    
    # 創建兩列以並排顯示下載選項
    download_col1, download_col2 = st.columns(2)
    
    with download_col1:
        # 選項1: 簡單Excel (無照片)
        st.markdown("### 基本Excel檔案 (無照片)")
        # 最簡單明確的方式 - 直接從記憶體生成Excel
        buffer = io.BytesIO()
        try:
            df = pd.DataFrame(results)
            
            # 清理數據以防止Excel錯誤
            for column in df.columns:
                if df[column].dtype == 'object':  # 只處理字符串類型的列
                    df[column] = df[column].apply(lambda x: clean_text_for_excel(x) if isinstance(x, str) else x)
            
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            buffer.seek(0)
            
            # 簡單Excel下載按鈕
            download_button = st.download_button(
                label="📊 下載基本Excel檔案",
                data=buffer,
                file_name=f"104履歷資料_{len(results)}筆_無照片.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_excel_direct",
                help="點擊此按鈕下載不含照片的基本Excel檔案",
                on_click=None,
                args=None
            )
            
            if download_button:
                st.success("下載已開始！")
        except Exception as e:
            st.error(f"生成Excel檔案失敗: {str(e)}")
        
        # 提供JSON格式下載選項
        try:
            json_str = json.dumps(results, ensure_ascii=False, indent=2)
            st.download_button(
                label="📄 下載JSON格式資料",
                data=json_str.encode('utf-8'),
                file_name=f"104履歷資料_{len(results)}筆.json",
                mime="application/json",
                key="download_json_direct",
                help="以JSON格式下載原始資料"
            )
        except Exception as json_e:
            st.error(f"生成JSON檔案失敗: {str(json_e)}")
    
    with download_col2:
        # 選項2: 完整Excel (含照片) - 如果可用
        st.markdown("### 包含大頭照的Excel檔案")
        
        if st.session_state.output_dir and os.path.exists(st.session_state.output_dir):
            try:
                # 尋找Excel檔案
                excel_files = [f for f in os.listdir(st.session_state.output_dir) if f.endswith('.xlsx')]
                
                if excel_files:
                    # 找出最新的Excel檔案
                    latest_excel = max(excel_files, key=lambda x: os.path.getmtime(os.path.join(st.session_state.output_dir, x)))
                    excel_path = os.path.join(st.session_state.output_dir, latest_excel)
                    
                    # 檢查文件是否存在和可讀
                    if os.path.exists(excel_path) and os.access(excel_path, os.R_OK):
                        with open(excel_path, "rb") as f:
                            file_data = f.read()
                        
                        # 提供下載按鈕
                        st.download_button(
                            label="🖼️ 下載帶大頭照的Excel檔案",
                            data=file_data,
                            file_name=latest_excel,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="download_photo_excel",
                            help="下載包含求職者大頭照的完整Excel檔案"
                        )
                        st.success("這個檔案包含求職者大頭照！")
                        
                        # 顯示照片文件夾資訊
                        photos_dir = os.path.join(st.session_state.output_dir, "profile_photos")
                        if os.path.exists(photos_dir):
                            photo_count = len([f for f in os.listdir(photos_dir) if f.endswith(('.jpg', '.jpeg', '.png'))])
                            if photo_count > 0:
                                st.info(f"已下載 {photo_count} 張求職者大頭照")
                    else:
                        st.warning("系統無法讀取包含照片的Excel檔案")
                else:
                    st.warning("未找到包含照片的Excel檔案")
            except Exception as ex:
                st.error(f"讀取Excel檔案失敗: {str(ex)}")
        else:
            st.warning("無法找到包含照片的Excel檔案。請使用左側的基本Excel下載選項。")

# 顯示使用說明
with st.expander("使用說明"):
    st.markdown("""
    ### 如何使用此工具
    
    #### 爬蟲類型
    本工具提供三種爬蟲功能：
    1. **履歷爬蟲** - 爬取符合條件的求職者履歷（需要104企業會員帳號）
    2. **職缺爬蟲** - 爬取符合職位名稱的工作職缺
    3. **公司爬蟲** - 爬取符合公司名稱的公司資訊
    
    #### 履歷爬蟲使用方法
    1. 輸入您的104企業會員帳號和密碼
    2. 輸入您想搜尋的關鍵詞（可選）
    3. 設定要爬取的頁數
    4. 點擊「開始爬取」按鈕
    5. 下載選項：
       - 「下載基本Excel檔案」- 快速下載但不包含大頭照
       - 「下載帶大頭照的Excel檔案」- 包含求職者大頭照
    
    #### 職缺爬蟲使用方法
    1. 輸入您想搜尋的職位名稱（例如：軟體工程師）
    2. 設定要爬取的頁數，或選擇不限制頁數
    3. 點擊「開始爬取職缺」按鈕
    4. 爬蟲完成後可預覽和下載結果
    
    #### 公司爬蟲使用方法
    1. 輸入您想搜尋的公司名稱（例如：台積電）
    2. 設定要爬取的頁數，或選擇不限制頁數
    3. 點擊「開始爬取公司」按鈕
    4. 爬蟲完成後可預覽和下載結果
    
    ### 注意事項
    - 爬蟲過程中瀏覽器視窗會自動打開，請勿關閉
    - 過程中可能需要輸入郵箱驗證碼，請留意終端機視窗提示
    - 結果會同時保存為Excel和JSON格式
    - 所有資料僅供研究學習使用
    - 下載按鈕會將檔案直接下載到您的電腦上
    - 包含大頭照的Excel檔案只有在爬蟲成功下載照片時才可用
    """)
