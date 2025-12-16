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

# 按钮区域
col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🚀 开始抓取", disabled=st.session_state.scraping, type="primary"):
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

# 侧边栏：退出功能
with st.sidebar:
    st.markdown("### 控制台")
    if st.button("❌ 退出程序"):
        st.warning("程序正在退出...您可以关闭此浏览器标签页了。")
        # 给一点时间让上面的提示渲染出来
        time.sleep(1)
        os._exit(0)
