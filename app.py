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

def run_scraper(incremental: bool = False):
    st.session_state.scraping = True
    st.session_state.log_messages = []
    
    # Reset or keep works based on incremental
    if not incremental:
        st.session_state.works = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_area = st.empty()
    
    try:
        scraper = AaajiaoScraper()
        
        # 1. Get Links
        status_text.text("Fetching sitemap.xml...")
        links = scraper.get_all_work_links(incremental=incremental)
        total_links = len(links)
        
        if total_links == 0 and incremental:
             st.session_state.log_messages.append("No changes detected. / 没有检测到更新。")
             st.info("✅ No new artworks found / 没有发现新作品")
             status_text.text("Done.")
             st.session_state.scraping = False
             return

        st.session_state.log_messages.append(f"Found {total_links} new/updated links / 找到 {total_links} 个需更新链接")
        
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
                    
                    # Auto-save every 5 items
                    if completed_count % 5 == 0:
                        scraper.works = st.session_state.works
                        scraper.save_to_json()
                        st.session_state.log_messages.append(f"💾 Auto-saved {len(st.session_state.works)} items")

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
        
        # Parse URLs if list of strings, or keep if already list
        url_list = urls
        if isinstance(urls, str) and urls.strip():
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
        
        # Enhanced prompt for images
        enhanced_prompt = prompt
        if download_images and "image" not in prompt.lower():
            enhanced_prompt = f"{prompt}. IMPORTANT: For images, extract the 'src_o' attribute which contains the high-resolution URL. Do not mistakenly extract thumbnails from the sidebar gallery."
        
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

tab1, tab2, tab3 = st.tabs(["🏗️ Basic Scraper / 基础爬虫", "⚡️ Quick Extract / 快速提取", "🚀 Batch Discovery / 批量发现"])

# ============ Tab 1: Basic Scraper (Original) ============
with tab1:
    col_u1, col_u2 = st.columns([1, 1])
    with col_u1:
        st.markdown("Click button below to scrape all artworks defined in `sitemap.xml` / 点击下方按钮抓取所有作品")
    
    with col_u2:
        incremental = st.checkbox("Incremental Update / 增量更新 (只抓取新页面)", value=False, help="Based on sitemap 'lastmod' / 基于 sitemap 的 lastmod 检测")
    
    if st.button("🚀 Start Scraping / 开始抓取", disabled=st.session_state.scraping, type="primary", key="scrape_btn"):
        run_scraper(incremental=incremental)

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


# ============ Tab 2: Quick Extract / AI Search (The Agent) ============
with tab2:
    st.markdown("""
    **两种模式 / Two Modes**:
    - **🎯 单页提取**: 填写 URL → 使用 `Extract API` (~50 credits) → 快速提取指定页面
    - **🤖 开放搜索**: 不填 URL → 使用 `Agent API` (高成本) → AI 自主浏览和搜索
    
    > 💡 **提示**: 如果你知道要提取哪个页面，请填写 URL，这样更便宜、更快！
    """)
    
    # Standardized Prompt
    default_prompt = "Extract all text content from the page (title, description, metadata, full text). Also extract the URL of the first visible image (or main artwork image) and map it to the field 'image'. IMPORTANT: If the image has a 'src_o' attribute, extract that URL for high resolution."

    # Input Area
    prompt = st.text_area(
        "Prompt / 提取指令",
        value=default_prompt,
        height=120,
        help="描述你想要提取的内容"
    )
    
    urls = st.text_input(
        "Specific URL (Optional) / 指定 URL (可选)",
        placeholder="https://eventstructure.com/Absurd-Reality-Check",
        help="Paste a single URL here in Quick Mode. / 在此粘贴单个 URL。",
        key="quick_url_input"
    )
    
    # Determine mode based on input
    has_url = bool(urls and urls.strip())
    
    col1, col2 = st.columns(2)
    with col1:
        if has_url:
            st.info("🎯 **Mode: Single Page Extraction**\n(Cost: ~50-80 credits per page)")
            # In URL mode, slider sets the COUNT of pages (if multiple comma-separated)
            max_credits = st.slider("Limit (Pages) / 数量限制 (页数)", min_value=1, max_value=10, value=1, help="Number of URLs to process.")
        else:
            st.info("🤖 **Mode: Open AI Research**\n(Cost: Variable)")
            # In Agent mode, slider sets the Credit Budget
            max_credits = st.slider("Max Budget (Credits) / 预算上限 (积分)", min_value=10, max_value=200, value=50, help="Max credits the agent can spend.")
            
    with col2:
        download_images = st.checkbox("📥 Download Images & Report / 下载图片并生成报告", value=True)
    
    if st.button("🔍 Start / 开始执行", type="primary", key="agent_btn", disabled=not prompt.strip()):
        # Handle single URL as list
        url_list = urls.split(",") if urls else None
        if url_list:
             url_list = [u.strip() for u in url_list if u.strip()]
             
        # Debug feedback
        if has_url:
            st.toast(f"Processing {len(url_list)} URL(s)...", icon="🚀")
        else:
            st.toast("Starting Open Agent Search...", icon="🤖")
            
        run_agent(prompt, url_list, max_credits, download_images)

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


# ============ Tab 3: Batch Discovery (The Factory) ============
with tab3:
    st.markdown("""
    **Solve Infinite/Horizontal Scroll Issues / 解决滚动加载问题**:
    1. **Scan / 扫描**: Auto-scroll page to discover links.
    2. **Filter / 筛选**: Select artworks to extract.
    3. **Extract / 提取**: Batch process with selected mode.
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
            "Scroll Strategy", 
            ["auto", "horizontal", "vertical"],
            index=0,
            help="Auto: Hybrid\nHorizontal: Gallery\nVertical: Standard"
        )
    
    if st.button("🔭 Start Scanning / 开始扫描", type="primary"):
        with st.spinner(f"Scanning ({scroll_mode} mode)..."):
            scraper = AaajiaoScraper()
            found = scraper.discover_urls_with_scroll(discovery_url, scroll_mode=scroll_mode)
            st.session_state.discovery_urls = found
            
            if found:
                st.success(f"✅ Found {len(found)} links / 发现 {len(found)} 个链接")
            else:
                st.error("❌ No links found / 未发现链接")

    # --- Step 2 & 3: Select & Extract (显示在扫描结果之后) ---
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
        
        # --- 提取模式选择（放在选择链接之后）---
        st.markdown("---")
        st.markdown("**Extraction Mode / 提取模式**")
        
        mode_col, config_col = st.columns([1, 1])
        with mode_col:
            extraction_level = st.radio(
                "Select Mode",
                ["quick", "full", "images_only", "custom"],
                format_func=lambda x: {
                    "quick": "⚡ Quick (~20 credits)",
                    "full": "📋 Full (~50 credits)",
                    "images_only": "🖼️ Images (~30 credits)",
                    "custom": "🔧 Custom"
                }[x],
                horizontal=True,
                key="disc_level"
            )
            
            if extraction_level == "custom":
                disc_prompt = st.text_area("Custom Prompt", value="Extract all text content and high-res images (src_o attribute).", height=80, key="disc_custom_prompt")
            else:
                disc_prompt = ""
                mode_info = {"quick": "标题、年份、类型", "full": "完整描述+高清图", "images_only": "仅图片URL", "custom": ""}
                st.caption(f"📌 {mode_info.get(extraction_level, '')}")
        
        with config_col:
            # 缓存统计
            scraper_check = AaajiaoScraper()
            prompt_for_cache = disc_prompt if extraction_level == "custom" else scraper_check.PROMPT_TEMPLATES.get(extraction_level, "")
            cached_count = sum(1 for url in selected_urls if scraper_check._load_extract_cache(url, prompt_for_cache))
            uncached_count = len(selected_urls) - cached_count
            
            if cached_count > 0:
                st.success(f"💾 缓存命中: {cached_count}/{len(selected_urls)}")
            
            cost_per_url = {"quick": 20, "full": 50, "images_only": 30, "custom": 50}.get(extraction_level, 50)
            est_cost = uncached_count * cost_per_url
            st.markdown(f"**预计消耗:** `{est_cost} credits`")
            
            disc_credits = st.slider("Batch Limit", 1, max(50, len(selected_urls)), len(selected_urls), key="disc_slider")
            disc_download = st.checkbox("Download Images / 下载图片", value=True, key="disc_img")
            
        if st.button("🤖 Batch Extract / 开始批量提取", disabled=len(selected_urls)==0, type="primary"):
            status_box = st.empty()
            with status_box.container():
                st.info("🚀 Submitting Agent Task... / 正在提交 Agent 任务...")
                
                final_prompt = disc_prompt
                # 对于非 custom 模式，使用模板
                if extraction_level != "custom":
                    final_prompt = ""  # agent_search 会自动使用模板
                elif disc_download and "image" not in disc_prompt.lower():
                    final_prompt += ". Also extract all image URLs."
                
                scraper = AaajiaoScraper()
                result = scraper.agent_search(
                    final_prompt, 
                    urls=selected_urls, 
                    max_credits=disc_credits,
                    extraction_level=extraction_level
                )
                
                if result:
                    # 显示缓存统计
                    cached = result.get("cached_count", 0)
                    new = result.get("new_count", len(result.get("data", [])) - cached)
                    if result.get("from_cache"):
                        st.success(f"✅ 全部从缓存获取！节省 API 调用")
                    else:
                        st.success(f"✅ 提取完成！(缓存: {cached}, 新增: {new})")
                    
                    # === 组合视图 ===
                    data_list = result.get("data", [])
                    if data_list:
                        # 1. 表格概览
                        st.subheader("📊 结果概览")
                        table_data = []
                        for item in data_list:
                            table_data.append({
                                "标题": item.get("title", "N/A"),
                                "年份": item.get("year", "N/A"),
                                "类型": item.get("type", "N/A"),
                                "图片数": len(item.get("high_res_images", item.get("images", [])) or [])
                            })
                        st.dataframe(table_data, use_container_width=True)
                        
                        # 2. 详细预览（可展开）
                        st.subheader("🖼️ 详细信息")
                        for i, item in enumerate(data_list):
                            title = item.get("title", f"Item {i+1}")
                            year = item.get("year", "")
                            with st.expander(f"**{title}** ({year})" if year else f"**{title}**"):
                                # 描述
                                desc = item.get("description_cn") or item.get("description_en") or item.get("description", "")
                                if desc:
                                    st.markdown(desc[:500] + ("..." if len(desc) > 500 else ""))
                                
                                # 图片缩略图
                                images = item.get("high_res_images") or item.get("images") or []
                                if images:
                                    img_cols = st.columns(min(4, len(images)))
                                    for j, img_url in enumerate(images[:4]):
                                        try:
                                            img_cols[j].image(img_url, width=120)
                                        except:
                                            img_cols[j].markdown(f"[图片{j+1}]({img_url})")
                                
                                # 视频链接
                                video = item.get("video_link")
                                if video:
                                    st.markdown(f"🎬 **视频:** [{video}]({video})")
                        
                        # 3. JSON 下载（折叠）
                        with st.expander("📥 查看原始 JSON"):
                            st.json(result)
                    
                    if disc_download:
                        scraper.generate_agent_report(result, "agent_discovery_output", prompt=final_prompt, extraction_level=extraction_level)
                        st.info("📄 Report generated at: `agent_discovery_output/`")
                else:
                    st.error("❌ Task Failed / 任务失败")


# Sidebar
with st.sidebar:
    st.markdown("### Console / 控制台")
    st.markdown("---")
    st.markdown("**Modes / 模式说明：**")
    st.markdown("- **Basic**: Scrape Sitemap / 抓取站点地图")
    st.markdown("- **Quick**: Single URL or AI / 快速提取")
    st.markdown("- **Batch**: Discovery -> Extract / 批量发现")
    st.markdown("---")
    if st.button("❌ Exit App / 退出程序"):
        st.warning("Exiting... / 程序退出...")
        time.sleep(1)
        os._exit(0)
