import streamlit as st
import time
import pandas as pd
import json
import os
from aaajiao_scraper import AaajiaoScraper
import concurrent.futures

# 配置页面
st.set_page_config(
    page_title="aaajiao Scraper",
    page_icon="🎨",
    layout="wide"
)

# 标题
st.title("🎨 aaajiao 作品集抓取工具")
st.markdown("此工具可以从 eventstructure.com 自动抓取作品信息并生成文档。")

# 初始化 session state
if 'works' not in st.session_state:
    st.session_state.works = []
if 'scraping' not in st.session_state:
    st.session_state.scraping = False
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'agent_result' not in st.session_state:
    st.session_state.agent_result = None

def run_scraper():
    st.session_state.scraping = True
    st.session_state.works = []
    st.session_state.log_messages = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_area = st.empty()
    
    try:
        scraper = AaajiaoScraper()
        
        # 1. 获取链接
        status_text.text("正在获取作品列表...")
        st.session_state.log_messages.append("正在扫描主页获取链接...")
        links = scraper.get_all_work_links()
        total_links = len(links)
        st.session_state.log_messages.append(f"找到 {total_links} 个作品链接")
        
        # 2. 并发抓取
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
                            msg = f"[{completed_count}/{total_links}] 成功: {data.get('title', 'Unknown')}"
                        else:
                            msg = f"[{completed_count}/{total_links}] 失败: {url}"
                            
                        st.session_state.log_messages.append(msg)
                        
                        # 更新UI
                        progress = completed_count / total_links
                        progress_bar.progress(progress)
                        status_text.text(f"正在抓取: {completed_count}/{total_links}")
                        
                        # 仅显示最近5条日志以免刷屏
                        log_area.code("\n".join(st.session_state.log_messages[-5:]))
                        
                    except Exception as e:
                        st.session_state.log_messages.append(f"错误: {e}")

        # 3. 保存文件
        status_text.text("正在保存文件...")
        # 此时 works 已经填充到 scraper 实例中了吗？没有，我们手动赋值
        scraper.works = st.session_state.works
        
        scraper.save_to_json()
        scraper.generate_markdown()
        
        st.success(f"抓取完成！共获取 {len(st.session_state.works)} 个作品。")
        st.balloons()
        
    except Exception as e:
        st.error(f"发生错误: {str(e)}")
    finally:
        st.session_state.scraping = False


def run_agent(prompt: str, urls: str, max_credits: int, download_images: bool = False):
    """运行 Agent 查询"""
    st.session_state.agent_result = None
    
    status_area = st.empty()
    result_area = st.empty()
    
    try:
        scraper = AaajiaoScraper()
        
        status_area.info("🤖 启动 Agent 任务...")
        
        # 解析 URLs
        url_list = None
        if urls.strip():
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
        
        # 如果需要下载图片，增强 prompt
        enhanced_prompt = prompt
        if download_images and "image" not in prompt.lower():
            enhanced_prompt = f"{prompt}. Also extract all image URLs from the page."
        
        # 调用 Agent
        result = scraper.agent_search(enhanced_prompt, urls=url_list, max_credits=max_credits)
        
        if result:
            st.session_state.agent_result = result
            status_area.success("✅ Agent 查询完成!")
            result_area.json(result)
            
            # 如果勾选了下载图片，生成报告
            if download_images:
                status_area.info("📥 正在下载图片并生成报告...")
                scraper.generate_agent_report(result, "agent_output", prompt=enhanced_prompt)
                status_area.success("✅ 报告生成完成!")
        else:
            status_area.error("❌ Agent 查询失败")
            
    except Exception as e:
        status_area.error(f"发生错误: {str(e)}")


# ============ 主界面：使用 Tabs ============

tab1, tab2 = st.tabs(["📋 批量抓取", "🤖 Agent 查询"])

# ============ Tab 1: 批量抓取 ============
with tab1:
    st.markdown("从 Sitemap 获取所有作品链接，逐一抓取详细信息。")
    
    if st.button("🚀 开始抓取", disabled=st.session_state.scraping, type="primary", key="scrape_btn"):
        run_scraper()

    # 结果展示区域
    if st.session_state.works:
        st.divider()
        st.subheader("📊 抓取结果预览")
        
        # 转为 DataFrame 展示
        df = pd.DataFrame(st.session_state.works)
        # 选取主要列展示
        display_cols = ['title', 'title_cn', 'year', 'type', 'url']
        cols_to_show = [c for c in display_cols if c in df.columns]
        st.dataframe(df[cols_to_show], use_container_width=True)
        
        st.divider()
        st.subheader("📥 下载文件")
        
        c1, c2 = st.columns(2)
        with c1:
            # 读取生成的文件供下载
            try:
                with open("aaajiao_works.json", "rb") as f:
                    st.download_button(
                        label="下载 JSON 数据",
                        data=f,
                        file_name="aaajiao_works.json",
                        mime="application/json"
                    )
            except FileNotFoundError:
                st.warning("JSON 文件尚未生成")
                
        with c2:
            try:
                with open("aaajiao_portfolio.md", "rb") as f:
                    st.download_button(
                        label="下载 Markdown 文档",
                        data=f,
                        file_name="aaajiao_portfolio.md",
                        mime="text/markdown"
                    )
            except FileNotFoundError:
                st.warning("Markdown 文件尚未生成")

    elif not st.session_state.scraping:
        st.info("点击上方按钮开始运行。")


# ============ Tab 2: Agent 查询 ============
with tab2:
    st.markdown("""
    使用自然语言描述你想要的信息，Firecrawl Agent 会自动搜索并提取数据。
    
    **示例查询：**
    - "Find all video installations by aaajiao"
    - "Get complete information including all images"
    - "Summarize the artwork and list exhibition history"
    """)
    
    # 输入区域
    prompt = st.text_area(
        "查询描述 (Prompt)",
        placeholder="例如: Get complete information about this artwork including all images",
        height=100
    )
    
    urls = st.text_input(
        "指定 URL（可选，多个用逗号分隔）",
        placeholder="https://eventstructure.com/Absurd-Reality-Check"
    )
    
    col1, col2 = st.columns(2)
    with col1:
        max_credits = st.slider("最大 Credits 消耗", min_value=10, max_value=100, value=50)
    with col2:
        download_images = st.checkbox("📥 下载图片并生成报告", value=True)
    
    if st.button("🔍 开始查询", type="primary", key="agent_btn", disabled=not prompt.strip()):
        run_agent(prompt, urls, max_credits, download_images)
    
    # 显示上次结果
    if st.session_state.agent_result:
        st.divider()
        st.subheader("📋 查询结果")
        
        c1, c2 = st.columns(2)
        with c1:
            # 提供下载按钮
            result_json = json.dumps(st.session_state.agent_result, ensure_ascii=False, indent=2)
            st.download_button(
                label="下载结果 JSON",
                data=result_json,
                file_name="agent_result.json",
                mime="application/json"
            )
        
        with c2:
            # 如果有生成报告，提供下载
            report_path = "agent_output/artwork_report.md"
            if os.path.exists(report_path):
                with open(report_path, "rb") as f:
                    st.download_button(
                        label="下载 Markdown 报告",
                        data=f,
                        file_name="artwork_report.md",
                        mime="text/markdown"
                    )
        
        # 显示下载的图片
        images_dir = "agent_output/images"
        if os.path.exists(images_dir):
            images = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
            if images:
                st.subheader("🖼️ 下载的图片")
                cols = st.columns(min(len(images), 3))
                for i, img in enumerate(sorted(images)[:6]):
                    with cols[i % 3]:
                        st.image(os.path.join(images_dir, img), caption=img, use_container_width=True)


# 侧边栏：退出功能
with st.sidebar:
    st.markdown("### 控制台")
    st.markdown("---")
    st.markdown("**模式说明：**")
    st.markdown("- **批量抓取**：抓取所有作品")
    st.markdown("- **Agent 查询**：自然语言查询")
    st.markdown("---")
    if st.button("❌ 退出程序"):
        st.warning("程序正在退出...您可以关闭此浏览器标签页了。")
        # 给一点时间让上面的提示渲染出来
        time.sleep(1)
        os._exit(0)

