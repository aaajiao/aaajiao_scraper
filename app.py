import streamlit as st
import time
import pandas as pd
import json
import os
import re
import requests
from scraper import AaajiaoScraper
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
             
             # Load existing cached data into session state so UI can display it
             try:
                 with open("aaajiao_works.json", "r", encoding="utf-8") as f:
                     st.session_state.works = json.load(f)
                     st.session_state.log_messages.append(f"📦 Loaded {len(st.session_state.works)} cached works")
             except FileNotFoundError:
                 pass
             
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
                    
                    # Auto-save every 5 items (with deduplication)
                    if completed_count % 5 == 0:
                        # Deduplicate by URL before saving
                        seen_urls = set()
                        unique_works = []
                        for w in st.session_state.works:
                            url = w.get('url', '')
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                unique_works.append(w)
                        scraper.works = unique_works
                        scraper.save_to_json()
                        st.session_state.log_messages.append(f"💾 Auto-saved {len(unique_works)} items")

        # 3. Save Files (with final deduplication)
        status_text.text("Saving files... / 正在保存文件...")
        
        # Final deduplication by URL
        seen_urls = set()
        unique_works = []
        for w in st.session_state.works:
            url = w.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_works.append(w)
        
        st.session_state.works = unique_works  # Update session state with deduplicated list
        scraper.works = unique_works
        
        scraper.save_to_json()
        scraper.generate_markdown()
        
        st.success(f"Completed! Scraped {len(unique_works)} artworks. / 抓取完成！共获取 {len(unique_works)} 个作品。")
        st.balloons()
        
    except Exception as e:
        st.error(f"Error occurred: {str(e)} / 发生错误")
    finally:
        st.session_state.scraping = False


# ============ Main Interface with Tabs ============

tab1, tab2 = st.tabs([
    "🏗️ Basic Scraper / 基础爬虫", 
    "🔄 Batch Update / 批量更新"
])

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
        display_cols = ['title', 'title_cn', 'year', 'type', 'size', 'duration', 'url']
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
    
    # ============ Image Enrichment Section ============

    st.divider()
    
    # Load cached works count
    scraper_preview = AaajiaoScraper()
    cached_works = scraper_preview.get_all_cached_works()
    
    if cached_works:
        st.success(f"📦 Found {len(cached_works)} cached works / 发现 {len(cached_works)} 个已缓存作品")
        st.subheader("🖼️ Image Enrichment / 图片整合")
        
        st.markdown("""
        **从已缓存的作品数据中提取图片 (无需 API)**
        - 使用 HTML 解析提取每个作品的高清图片
        - 可选择下载到本地
        - 生成包含图片的完整报告
        """)
        
        # --- Feature 1: Image Enrichment (Download & Patch) ---
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            download_images_option = st.checkbox("📥 Download Images / 下载图片到本地", value=True, key="enrich_download")
        with col_opt2:
            limit_works = st.slider("处理数量限制", min_value=1, max_value=len(cached_works), value=min(50, len(cached_works)), key="enrich_limit")
        
        if st.button("🖼️ Start Image Enrichment (Local) / 开始图片整合", type="primary", key="enrich_btn"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            scraper = AaajiaoScraper()
            works_to_process = cached_works[:limit_works]
            enriched_works = []
            all_images = [] # Track for stats
            
            output_dir = "output/images" if download_images_option else "output"
            
            for i, work in enumerate(works_to_process):
                title = work.get("title", "Unknown")[:30]
                status_text.text(f"[{i+1}/{len(works_to_process)}] Processing: {title}...")
                
                try:
                    # Enrich works
                    enriched_work = scraper.enrich_work_with_images(
                        work, 
                        output_dir="output" 
                    )
                    enriched_works.append(enriched_work)
                    
                    if enriched_work.get("local_images"):
                         all_images.extend(enriched_work["local_images"])
                         
                except Exception as e:
                    st.warning(f"Failed: {title} - {e}")
                    enriched_works.append(work)
                
                progress_bar.progress((i + 1) / len(works_to_process))
            
            status_text.text("Generating report...")
            
            # Generate Markdown report
            report_lines = ["# aaajiao Portfolio with Images\n", f"*Generated: {time.strftime('%Y-%m-%d %H:%M')}*\n\n"]
            
            for work in enriched_works:
                title = work.get("title", "Untitled")
                title_cn = work.get("title_cn", "")
                year = work.get("year", "")
                url = work.get("url", "")
                desc_en = work.get("description_en", "")
                desc_cn = work.get("description_cn", "")
                images = work.get("images", [])
                local_images = work.get("local_images", [])
                
                report_lines.append(f"## {title}")
                if title_cn:
                    report_lines.append(f" / {title_cn}")
                report_lines.append(f"\n\n**Year:** {year}\n")
                report_lines.append(f"**URL:** [{url}]({url})\n\n")
                
                if desc_en:
                    report_lines.append(f"{desc_en}\n\n")
                if desc_cn:
                    report_lines.append(f"{desc_cn}\n\n")
                
                # Images section
                if images or local_images:
                    report_lines.append("### Images\n\n")
                    
                    imgs_to_show = images
                    use_local = bool(local_images)
                    
                    if use_local:
                        for img_path in local_images[:10]:
                             if "images/" in img_path:
                                rel_path = "images/" + img_path.split("images/", 1)[1]
                             else:
                                rel_path = os.path.basename(img_path)
                             report_lines.append(f"![Image]({rel_path})\n\n")     
                    else:
                        for img_url in images[:10]:
                            report_lines.append(f"![Image]({img_url})\n\n")
                
                report_lines.append("---\n\n")
            
            report_content = "".join(report_lines)
            
            # Save report
            os.makedirs("output", exist_ok=True)
            report_path = "output/portfolio_with_images.md"
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            
            st.success("✅ Image Enrichment Complete! / 图片整合完成!")
            
            if download_images_option and all_images:
                 st.info(f"📁 Images saved to: `output/images/`")

            st.download_button(
                label="📥 Download Enriched Portfolio (With Local Images) / 下载完整图文报告 (含本地图)",
                data=report_content,
                file_name="aaajiao_portfolio_images.md",
                mime="text/markdown"
            )

        # --- Feature 2: Web Image Report (Lightweight) ---
        st.divider()
        st.subheader("🌐 Web-Image Report / 网络图片报告")
        st.markdown("生成一份仅包含**在线图片链接**的轻量级报告，无需下载图片，便于分享。")
        
        if st.button("📄 Generate Web Report / 生成报告", key="gen_web_report"):
            # Use cached_works directly since we are inside the if block
            works = cached_works
            
            # Sort
            def get_sort_year(w):
                y = w.get("year", "0000")
                if "-" in y: return y.split("-")[-1]
                return y
            
            works.sort(key=get_sort_year, reverse=True)
            
            lines = [
                "# aaajiao Portfolio (Web Images)\n", 
                f"> Generated: {time.strftime('%Y-%m-%d %H:%M')}\n",
                "> **Note**: Images are direct links to eventstructure.com\n\n",
                "---\n\n"
            ]
            
            progress = st.progress(0)
            status = st.empty()
            
            for i, work in enumerate(works):
                status.text(f"Processing {i+1}/{len(works)}...")
                progress.progress((i+1)/len(works))
                
                title = work.get("title", "Untitled")
                lines.append(f"## {work.get('year', '')} - {title}")
                if work.get('title_cn'):
                    lines.append(f" / {work['title_cn']}")
                lines.append("\n\n")
                
                lines.append(f"**URL:** [{work.get('url')}]({work.get('url')})\n\n")
                
                if work.get("description_cn"):
                    lines.append(f"> {work['description_cn']}\n\n")
                if work.get("description_en"):
                    lines.append(f"{work['description_en']}\n\n")
                    
                # Images logic
                imgs = work.get("images", [])
                if not imgs: imgs = work.get("high_res_images", [])
                
                # Fetch if missing
                if not imgs and work.get("url"):
                    try:
                        scraper_temp = AaajiaoScraper() # Need instance for method
                        imgs = scraper_temp.extract_images_from_page(work['url'])
                    except:
                        pass
                
                if imgs:
                    lines.append("### Images\n\n")
                    for img in imgs:
                         lines.append(f"![]({img})\n\n")
                
                lines.append("---\n")
            
            st.success(f"✅ Generated report for {len(works)} works!")
            st.download_button(
                label="📥 Download Web Report / 下载网络版报告",
                data="".join(lines),
                file_name="aaajiao_web_images_report.md",
                mime="text/markdown"
            )

    else:
        st.warning("⚠️ No cached works found. Run 'Start Scraping' first to cache artwork data.")


# ============ Tab 2: Batch Update (Size & Duration) ============
with tab2:
    st.markdown("""
    **批量更新作品的尺寸和时长信息 / Batch Update Size & Duration**
    
    使用低成本的 Firecrawl scrape 模式（约 1 Credit/页）获取渲染后的页面内容，
    然后本地解析提取尺寸（size）和时长（duration）信息。
    
    > 💡 比 AI Extract 便宜 **50 倍**！（1 Credit vs 50 Credits）
    """)
    
    # Load current data
    try:
        with open("aaajiao_works.json", "r", encoding="utf-8") as f:
            all_works = json.load(f)
    except FileNotFoundError:
        all_works = []
    
    if not all_works:
        st.warning("⚠️ 没有找到作品数据，请先在 Tab 1 运行基础爬虫")
    else:
        # Stats
        total = len(all_works)
        has_size = sum(1 for w in all_works if w.get('size'))
        has_duration = sum(1 for w in all_works if w.get('duration'))
        missing_size = total - has_size
        missing_duration = total - has_duration
        
        # Video works
        video_types = ['video', 'Video', 'video installation', 'Video Installation']
        video_works = [w for w in all_works if any(vt.lower() in (w.get('type', '') or '').lower() for vt in video_types)]
        video_with_duration = sum(1 for w in video_works if w.get('duration'))
        
        st.subheader("📊 数据统计 / Data Statistics")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总作品数", total)
        with col2:
            st.metric("有尺寸信息", f"{has_size} ({has_size*100/total:.0f}%)", delta=f"-{missing_size} 缺失")
        with col3:
            st.metric("有时长信息", f"{has_duration}", delta=f"视频作品: {len(video_works)}")
        
        st.divider()
        
        # ---- Feature 1: Batch Update ----
        st.subheader("🔄 批量更新 / Batch Update")
        st.markdown("使用 Firecrawl scrape 获取渲染后的页面内容，提取尺寸和时长信息")
        
        # Options
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            update_limit = st.slider(
                "处理数量 / Limit", 
                min_value=1, 
                max_value=min(200, missing_size + missing_duration), 
                value=min(50, missing_size + missing_duration),
                help="每个作品消耗约 1 Credit"
            )
        with col_opt2:
            st.info(f"💰 预计消耗: ~{update_limit} Credits")
        
        # Helper functions
        def load_api_key():
            try:
                with open('.env', 'r') as f:
                    for line in f:
                        if line.startswith('FIRECRAWL_API_KEY'):
                            return line.split('=')[1].strip()
            except:
                pass
            return os.getenv("FIRECRAWL_API_KEY", "")
        
        def scrape_markdown(url, api_key):
            payload = {"url": url, "formats": ["markdown"]}
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            try:
                resp = requests.post("https://api.firecrawl.dev/v2/scrape", json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return resp.json().get("data", {}).get("markdown", "")
                elif resp.status_code == 429:
                    time.sleep(3)
                    return scrape_markdown(url, api_key)
            except:
                pass
            return None
        
        def parse_size_duration(md):
            result = {"size": "", "duration": ""}
            if not md:
                return result
            
            lines = md[:2000].split('\n')
            
            # Size patterns
            for line in lines:
                line = line.strip()
                if result["size"]:
                    break
                for pattern in [
                    r'size\s+(\d+\s*[×xX]\s*\d+(?:\s*[×xX]\s*\d+)?\s*(?:cm|mm|m)?)',
                    r'(Dimension[s]?\s+variable\s*/\s*尺寸可变)',
                    r'(Dimension[s]?\s+variable)',
                    r'^(尺寸可变)$',
                ]:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        result["size"] = match.group(1).strip()
                        break
            
            # Duration patterns
            for line in lines:
                line = line.strip()
                if result["duration"]:
                    break
                for pattern in [
                    r"^(\d+['′]\d+['′''\"]*)\s*$",
                    r"^(\d+['′''\"]+)\s*$",
                    r"video\s+(\d+['′''\"]+)",
                    r"^(\d+:\d+(?::\d+)?)\s*$",
                ]:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        result["duration"] = match.group(1).strip()
                        break
            
            return result
        
        if st.button("🚀 开始批量更新 / Start Batch Update", type="primary", key="batch_update_btn"):
            api_key = load_api_key()
            if not api_key:
                st.error("❌ 未找到 FIRECRAWL_API_KEY，请检查 .env 文件")
            else:
                # Filter works that need updating
                to_update = [w for w in all_works if not w.get('size') or not w.get('duration')][:update_limit]
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                log_area = st.empty()
                
                url_to_work = {w['url']: w for w in all_works}
                updated = 0
                logs = []
                
                for i, work in enumerate(to_update):
                    url = work.get('url')
                    title = work.get('title', 'Unknown')[:25]
                    
                    status_text.text(f"[{i+1}/{len(to_update)}] 处理: {title}...")
                    
                    md = scrape_markdown(url, api_key)
                    if md:
                        extracted = parse_size_duration(md)
                        changes = []
                        
                        if extracted['size'] and not work.get('size'):
                            url_to_work[url]['size'] = extracted['size']
                            changes.append(f"size='{extracted['size']}'")
                        
                        if extracted['duration'] and not work.get('duration'):
                            url_to_work[url]['duration'] = extracted['duration']
                            changes.append(f"duration='{extracted['duration']}'")
                        
                        if changes:
                            updated += 1
                            logs.append(f"✅ {title}: {', '.join(changes)}")
                        else:
                            logs.append(f"⚪ {title}: 无新数据")
                    else:
                        logs.append(f"❌ {title}: 抓取失败")
                    
                    progress_bar.progress((i + 1) / len(to_update))
                    log_area.code("\n".join(logs[-8:]))
                    time.sleep(0.3)
                
                # Save
                with open("aaajiao_works.json", "w", encoding="utf-8") as f:
                    json.dump(all_works, f, ensure_ascii=False, indent=2)
                
                st.success(f"✅ 完成！更新了 {updated}/{len(to_update)} 个作品")
                st.balloons()
                
                # Regenerate markdown
                scraper = AaajiaoScraper()
                scraper.works = all_works
                scraper.generate_markdown()
                st.info("📄 Markdown 报告已重新生成")
        
        st.divider()
        
        # ---- Feature 2: Data Cleaning ----
        st.subheader("🧹 数据清洗 / Data Cleaning")
        st.markdown("从 `materials` 字段中分离出混杂的尺寸和时长信息")
        
        # Preview
        mixed_materials = [w for w in all_works if w.get('materials') and 
                          any(kw in w.get('materials', '').lower() for kw in ['dimension', 'size', 'cm', '×', 'variable', '尺寸'])]
        
        if mixed_materials:
            st.warning(f"⚠️ 发现 {len(mixed_materials)} 个作品的 materials 字段可能包含尺寸信息")
            
            with st.expander("查看可能需要清洗的数据"):
                for w in mixed_materials[:10]:
                    st.markdown(f"- **{w.get('title', 'Unknown')[:30]}**: `{w.get('materials', '')[:60]}...`")
            
            if st.button("🧹 运行数据清洗 / Run Cleaning", key="clean_btn"):
                cleaned = 0
                for work in all_works:
                    old_materials = work.get('materials', '')
                    if not old_materials:
                        continue
                    
                    # Check if pure size
                    if re.match(r'^Dimension[s]?\s+variable\s*/?\s*尺寸可变$', old_materials, re.IGNORECASE):
                        work['materials'] = ''
                        work['size'] = old_materials
                        cleaned += 1
                    elif re.match(r'^Dimension[s]?\s+variable$', old_materials, re.IGNORECASE):
                        work['materials'] = ''
                        work['size'] = old_materials
                        cleaned += 1
                    elif re.match(r'^尺寸可变$', old_materials):
                        work['materials'] = ''
                        work['size'] = old_materials
                        cleaned += 1
                
                # Save
                with open("aaajiao_works.json", "w", encoding="utf-8") as f:
                    json.dump(all_works, f, ensure_ascii=False, indent=2)
                
                st.success(f"✅ 清洗完成！修改了 {cleaned} 个作品")
        else:
            st.success("✅ 数据已清洁，无需清洗")
        
        st.divider()
        
        # ---- Preview Updated Data ----
        st.subheader("📋 数据预览 / Data Preview")
        
        filter_option = st.radio(
            "筛选 / Filter",
            ["全部", "有尺寸", "有时长", "缺失尺寸", "视频作品"],
            horizontal=True
        )
        
        filtered = all_works
        if filter_option == "有尺寸":
            filtered = [w for w in all_works if w.get('size')]
        elif filter_option == "有时长":
            filtered = [w for w in all_works if w.get('duration')]
        elif filter_option == "缺失尺寸":
            filtered = [w for w in all_works if not w.get('size')]
        elif filter_option == "视频作品":
            filtered = video_works
        
        if filtered:
            df = pd.DataFrame(filtered)
            display_cols = ['title', 'year', 'type', 'size', 'duration', 'materials']
            cols_to_show = [c for c in display_cols if c in df.columns]
            st.dataframe(df[cols_to_show].head(50), use_container_width=True)
            st.caption(f"显示 {min(50, len(filtered))}/{len(filtered)} 条")


# Sidebar
with st.sidebar:
    st.markdown("### Console / 控制台")
    st.markdown("---")
    st.markdown("**Modes / 模式说明：**")
    st.markdown("- **Basic**: Scrape Sitemap / 抓取站点地图")
    st.markdown("- **Update**: Size & Duration / 更新尺寸时长")
    st.markdown("---")
    if st.button("❌ Exit App / 退出程序"):
        st.warning("Exiting... / 程序退出...")
        time.sleep(1)
        os._exit(0)

