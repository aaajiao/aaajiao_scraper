import streamlit as st
import time
import pandas as pd
import json
import os
from aaajiao_scraper import AaajiaoScraper
import concurrent.futures

# Page Config
st.set_page_config(
    page_title="aaajiao Scraper",
    page_icon="🎨",
    layout="wide"
)

# Title
st.title("🎨 aaajiao Portfolio Scraper / 作品集抓取工具")
st.markdown("Automated tool to scrape artwork details from eventstructure.com / 自动抓取并生成文档工具")

# Initialize session state
if 'works' not in st.session_state:
    st.session_state.works = []
if 'scraping' not in st.session_state:
    st.session_state.scraping = False
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'agent_result' not in st.session_state:
    st.session_state.agent_result = None
if 'discovery_found_urls' not in st.session_state:
    st.session_state.discovery_found_urls = []
if 'discovery_urls' not in st.session_state:
    st.session_state.discovery_urls = []

def run_scraper():
    st.session_state.scraping = True
    st.session_state.works = []
    st.session_state.log_messages = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_area = st.empty()
    
    try:
        scraper = AaajiaoScraper()
        
        # 1. Get Links
        status_text.text("Scanning homepage for links... / 正在获取作品列表...")
        st.session_state.log_messages.append("Scanning homepage... / 正在扫描主页...")
        links = scraper.get_all_work_links()
        total_links = len(links)
        st.session_state.log_messages.append(f"Found {total_links} artwork links / 找到 {total_links} 个作品链接")
        
        # 2. Concurrent Scrape
        if total_links > 0:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_url = {executor.submit(scraper.extract_work_details, url): url for url in links}
                
                completed_count = 0
                for future in concurrent.futures.as_completed(future_to_url):
                    url = future_to_url[future]
                    completed_count += 1
                    
                    try:
                        data = future.result()
                        if data:
                            st.session_state.works.append(data)
                            msg = f"[{completed_count}/{total_links}] Success: {data.get('title', 'Unknown')}"
                        else:
                            msg = f"[{completed_count}/{total_links}] Failed: {url}"
                            
                        st.session_state.log_messages.append(msg)
                        
                        # Update UI
                        progress = completed_count / total_links
                        progress_bar.progress(progress)
                        status_text.text(f"Scraping: {completed_count}/{total_links} / 正在抓取...")
                        
                        # Show logs
                        log_area.code("\n".join(st.session_state.log_messages[-5:]))
                        
                    except Exception as e:
                        st.session_state.log_messages.append(f"Error: {e}")

        # 3. Save Files
        status_text.text("Saving files... / 正在保存文件...")
        scraper.works = st.session_state.works
        
        scraper.save_to_json()
        scraper.generate_markdown()
        
        st.success(f"Completed! Scraped {len(st.session_state.works)} artworks. / 抓取完成！共获取 {len(st.session_state.works)} 个作品。")
        st.balloons()
        
    except Exception as e:
        st.error(f"Error occurred: {str(e)} / 发生错误")
    finally:
        st.session_state.scraping = False


def run_agent(prompt: str, urls: str, max_credits: int, download_images: bool = False):
    """Run Agent Search"""
    st.session_state.agent_result = None
    
    status_area = st.empty()
    result_area = st.empty()
    
    try:
        scraper = AaajiaoScraper()
        
        status_area.info("🤖 Starting Agent Task... / 启动 Agent 任务...")
        
        # Parse URLs
        url_list = None
        if urls.strip():
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
        
        # Enhanced prompt
        enhanced_prompt = prompt
        if download_images and "image" not in prompt.lower():
            enhanced_prompt = f"{prompt}. Also extract all image URLs from the page."
        
        # Call Agent
        result = scraper.agent_search(enhanced_prompt, urls=url_list, max_credits=max_credits)
        
        if result:
            st.session_state.agent_result = result
            status_area.success("✅ Agent Task Completed! / Agent 查询完成!")
            result_area.json(result)
            
            # Generate Report
            if download_images:
                status_area.info("📥 Downloading images & generating report... / 正在下载图片并生成报告...")
                scraper.generate_agent_report(result, "agent_output", prompt=enhanced_prompt)
                status_area.success("✅ Report Generated! / 报告生成完成!")
        else:
            status_area.error("❌ Agent Task Failed / Agent 查询失败")
            
    except Exception as e:
        status_area.error(f"Error: {str(e)}")


# ============ Main Interface with Tabs ============

tab1, tab2, tab3 = st.tabs(["📋 Batch Scrape / 批量抓取", "🤖 Agent Query / Agent 查询", "🚀 Smart Discovery / 智能发现"])

# ============ Tab 1: Batch Scrape ============
with tab1:
    st.markdown("Scrape all artwork details from Sitemap links. / 从 Sitemap 获取所有作品链接并抓取。")
    
    if st.button("🚀 Start Scraping / 开始抓取", disabled=st.session_state.scraping, type="primary", key="scrape_btn"):
        run_scraper()

    # Results Area
    if st.session_state.works:
        st.divider()
        st.subheader("📊 Preview / 结果预览")
        
        df = pd.DataFrame(st.session_state.works)
        display_cols = ['title', 'title_cn', 'year', 'type', 'url']
        cols_to_show = [c for c in display_cols if c in df.columns]
        st.dataframe(df[cols_to_show], use_container_width=True)
        
        st.divider()
        st.subheader("📥 Download / 下载文件")
        
        c1, c2 = st.columns(2)
        with c1:
            try:
                with open("aaajiao_works.json", "rb") as f:
                    st.download_button(
                        label="Download JSON / 下载 JSON 数据",
                        data=f,
                        file_name="aaajiao_works.json",
                        mime="application/json"
                    )
            except FileNotFoundError:
                st.warning("JSON file not found")
                
        with c2:
            try:
                with open("aaajiao_portfolio.md", "rb") as f:
                    st.download_button(
                        label="Download Markdown / 下载 Markdown 文档",
                        data=f,
                        file_name="aaajiao_portfolio.md",
                        mime="text/markdown"
                    )
            except FileNotFoundError:
                st.warning("Markdown file not found")

    elif not st.session_state.scraping:
        st.info("Click the button above to start. / 点击上方按钮开始运行。")


# ============ Tab 2: Agent Query ============
with tab2:
    st.markdown("""
    Use natural language to query Firecrawl Agent. / 使用自然语言描述你想要的信息。
    
    **Example / 示例:**
    - "Find all video installations by aaajiao"
    - "Get complete information including all images"
    """)
    
    # Input Area
    prompt = st.text_area(
        "Query Prompt / 查询描述",
        placeholder="e.g.: Get complete information about this artwork including all images",
        height=100
    )
    
    urls = st.text_input(
        "Specific URLs (Optional) / 指定 URL (可选)",
        placeholder="https://eventstructure.com/Absurd-Reality-Check"
    )
    
    col1, col2 = st.columns(2)
    with col1:
        max_credits = st.slider("Max Credits", min_value=10, max_value=100, value=50)
    with col2:
        download_images = st.checkbox("📥 Download Images & Report / 下载图片并生成报告", value=True)
    
    if st.button("🔍 Start Query / 开始查询", type="primary", key="agent_btn", disabled=not prompt.strip()):
        run_agent(prompt, urls, max_credits, download_images)
    
    # Show Results
    if st.session_state.agent_result:
        st.divider()
        st.subheader("📋 Results / 查询结果")
        
        c1, c2 = st.columns(2)
        with c1:
            result_json = json.dumps(st.session_state.agent_result, ensure_ascii=False, indent=2)
            st.download_button(
                label="Download JSON / 下载结果 JSON",
                data=result_json,
                file_name="agent_result.json",
                mime="application/json"
            )
        
        with c2:
            report_path = "agent_output/artwork_report.md"
            if os.path.exists(report_path):
                with open(report_path, "rb") as f:
                    st.download_button(
                        label="Download Report / 下载 Markdown 报告",
                        data=f,
                        file_name="artwork_report.md",
                        mime="text/markdown"
                    )
        
        # Show Images
        images_dir = "agent_output/images"
        if os.path.exists(images_dir):
            images = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
            if images:
                st.subheader("🖼️ Downloaded Images / 下载的图片")
                cols = st.columns(min(len(images), 3))
                for i, img in enumerate(sorted(images)[:6]):
                    with cols[i % 3]:
                        st.image(os.path.join(images_dir, img), caption=img, use_container_width=True)


# ============ Tab 3: Smart Discovery ============
with tab3:
    st.markdown("""
    **Solve Infinite/Horizontal Scroll Issues / 解决滚动加载问题**:
    1. **Scan / 扫描**: Auto-scroll page to discover links.
    2. **filter / 筛选**: Select artworks to extract.
    3. **Extract / 提取**: Batch process with Agent.
    """)
    
    # Session State Init
    if 'discovery_urls' not in st.session_state:
        st.session_state.discovery_urls = []
        
    # --- Step 1: Scan ---
    st.subheader("1. Scan Page / 扫描页面")
    
    col_url, col_mode = st.columns([3, 1])
    with col_url:
        discovery_url = st.text_input("Target URL / 目标网址", value="https://eventstructure.com")
    with col_mode:
        scroll_mode = st.selectbox(
            "Scroll Strategy / 滚动策略", 
            ["auto", "horizontal", "vertical"],
            index=0,
            help="Auto: Hybrid / 混合\nHorizontal: Gallery / 画廊\nVertical: Standard / 垂直"
        )
    
    if st.button("🔭 Start Scanning / 开始扫描发现链接", type="primary"):
        with st.spinner(f"Scanning ({scroll_mode} mode)... / 正在扫描..."):
            scraper = AaajiaoScraper()
            found = scraper.discover_urls_with_scroll(discovery_url, scroll_mode=scroll_mode)
            st.session_state.discovery_urls = found
            st.session_state.discovery_selected_urls = [] # Reset selection
            
            if found:
                st.success(f"✅ Scanning Complete! Found {len(found)} links / 扫描完成！发现 {len(found)} 个链接")
            else:
                st.error("❌ No links found / 未发现链接")

    # --- Step 2 & 3: Select & Extract ---
    if st.session_state.discovery_urls:
        st.divider()
        st.subheader("2. Filter & Extract / 筛选与提取")
        
        # Callback for Select All
        def toggle_all():
            new_state = st.session_state.select_all_chk
            for url in st.session_state.discovery_urls:
                st.session_state[f"chk_{url}"] = new_state

        # Select All Checkbox
        st.checkbox("Select All / 全选", value=False, key="select_all_chk", on_change=toggle_all)
        
        # Link List
        selected_urls = []
        with st.expander("View Links / 查看链接列表", expanded=True):
            for url in st.session_state.discovery_urls:
                key = f"chk_{url}"
                if key not in st.session_state:
                    st.session_state[key] = False
                
                if st.checkbox(url, key=key):
                    selected_urls.append(url)
        
        st.write(f"Selected / 已选择: **{len(selected_urls)}** items")
        
        # Agent Config
        c1, c2 = st.columns(2)
        with c1:
            disc_prompt = st.text_area("Agent Prompt", value="Extract title, year, materials and description", height=70)
        with c2:
            disc_credits = st.slider("Max Credits (Total / 总计)", 10, 500, 100, key="disc_slider")
            disc_download = st.checkbox("Download Images / 下载图片", value=True, key="disc_img")
            
        if st.button("🤖 Batch Extract / 开始批量提取", disabled=len(selected_urls)==0, type="primary"):
            status_box = st.empty()
            with status_box.container():
                st.info("🚀 Submitting Agent Task... / 正在提交 Agent 任务...")
                
                final_prompt = disc_prompt
                if disc_download and "image" not in disc_prompt.lower():
                    final_prompt += ". Also extract all image URLs."
                
                scraper = AaajiaoScraper()
                result = scraper.agent_search(final_prompt, urls=selected_urls, max_credits=disc_credits)
                
                if result:
                    st.success("✅ Extraction Completed! / 提取完成!")
                    st.json(result)
                    
                    if disc_download:
                        scraper.generate_agent_report(result, "agent_discovery_output", prompt=final_prompt)
                        st.info("Report generated at: `agent_discovery_output/` / 报告已生成")
                else:
                    st.error("❌ Task Failed / 任务失败")


# Sidebar
with st.sidebar:
    st.markdown("### Console / 控制台")
    st.markdown("---")
    st.markdown("**Modes / 模式说明：**")
    st.markdown("- **Batch / 批量**: Scrape all / 抓取所有")
    st.markdown("- **Agent**: AI Query / AI 查询")
    st.markdown("- **Discovery / 智能发现**: Smart Scroll / 智能滚动")
    st.markdown("---")
    if st.button("❌ Exit App / 退出程序"):
        st.warning("Exiting... / 程序退出...")
        time.sleep(1)
        os._exit(0)
