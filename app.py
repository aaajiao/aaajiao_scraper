"""
aaajiao 作品集抓取工具 - Streamlit GUI

简化的单页界面，用于从 eventstructure.com 抓取作品数据。
功能：
- 一键抓取，三层成本优化策略
- 自动过滤展览和画册
- 图片整合工具
"""

import json
import os
import time

import pandas as pd
import streamlit as st

from scraper import AaajiaoScraper, deduplicate_works, is_artwork

# 页面配置
st.set_page_config(
    page_title="aaajiao 抓取工具",
    page_icon="🎨",
    layout="wide"
)

# 标题
st.title("🎨 aaajiao 作品集抓取工具")
st.markdown("自动从 eventstructure.com 抓取作品详情")


# ============ 辅助函数 ============

def load_existing_works() -> list:
    """从 JSON 文件加载已有作品。"""
    try:
        with open("aaajiao_works.json", "r", encoding="utf-8") as f:
            works = json.load(f)
            # 过滤掉展览（以防旧数据包含）
            return [w for w in works if is_artwork(w)]
    except FileNotFoundError:
        return []


def get_stats(works: list) -> dict:
    """计算作品统计数据。"""
    total = len(works)
    has_size = sum(1 for w in works if w.get('size'))
    has_duration = sum(1 for w in works if w.get('duration'))
    has_year = sum(1 for w in works if w.get('year'))

    return {
        "total": total,
        "has_size": has_size,
        "has_duration": has_duration,
        "has_year": has_year,
        "size_pct": (has_size / total * 100) if total > 0 else 0,
    }


def normalize_url(url: str) -> str:
    """规范化 URL 用于匹配。"""
    if not url:
        return ""
    url = url.strip().rstrip("/")
    return url


def merge_work_with_full_data(work: dict, full_works: list) -> dict:
    """将作品数据与 aaajiao_works.json 中的完整元数据合并。

    使用 URL 作为匹配键，保留缓存中的图片数据，补充 JSON 中的元数据。
    """
    url = normalize_url(work.get("url", ""))
    if not url:
        return work

    for full_work in full_works:
        if normalize_url(full_work.get("url", "")) == url:
            merged = work.copy()
            metadata_fields = [
                'type', 'materials', 'size', 'duration',
                'description_en', 'description_cn', 'video_link', 'tags',
                'title', 'title_cn', 'year'
            ]
            for key in metadata_fields:
                if full_work.get(key):
                    merged[key] = full_work[key]
            if len(full_work.get("images", [])) > len(merged.get("images", [])):
                merged["images"] = full_work["images"]
                merged["high_res_images"] = full_work.get("high_res_images", full_work["images"])
            return merged

    return work


def generate_rich_work_markdown(work: dict, include_local_images: bool = False) -> str:
    """生成包含完整元数据的作品 Markdown。

    Args:
        work: 作品字典
        include_local_images: True 使用本地图片路径，False 使用网络 URL
    """
    lines = []

    title = work.get("title", "无标题")
    title_cn = work.get("title_cn", "")
    year = work.get("year", "")

    if title_cn and title_cn != title:
        lines.append(f"## {title} / {title_cn}\n\n")
    else:
        lines.append(f"## {title}\n\n")

    lines.append("| 字段 | 内容 |\n")
    lines.append("|------|------|\n")

    if year:
        lines.append(f"| 年份 | {year} |\n")
    if work.get("type"):
        lines.append(f"| 类型 | {work['type']} |\n")
    if work.get("materials"):
        lines.append(f"| 材料 | {work['materials']} |\n")
    if work.get("size"):
        lines.append(f"| 尺寸 | {work['size']} |\n")
    if work.get("duration"):
        lines.append(f"| 时长 | {work['duration']} |\n")
    if work.get("video_link"):
        lines.append(f"| 视频 | [{work['video_link']}]({work['video_link']}) |\n")
    if work.get("url"):
        lines.append(f"| 链接 | [{work['url']}]({work['url']}) |\n")

    lines.append("\n")

    if work.get("description_cn"):
        lines.append(f"### 中文描述\n\n> {work['description_cn']}\n\n")
    if work.get("description_en"):
        lines.append(f"### English Description\n\n{work['description_en']}\n\n")

    if include_local_images and work.get("local_images"):
        images = work.get("local_images", [])
        if images:
            lines.append("### 图片\n\n")
            for img_path in images[:10]:
                rel_path = os.path.basename(img_path)
                lines.append(f"![{title}]({rel_path})\n\n")
    else:
        images = work.get("images", []) or work.get("high_res_images", [])
        if images:
            lines.append("### 图片\n\n")
            for img in images[:5]:
                lines.append(f"![]({img})\n\n")

    lines.append("---\n\n")
    return "".join(lines)


# ============ 初始化 Session State ============

if 'works' not in st.session_state:
    st.session_state.works = load_existing_works()
if 'running' not in st.session_state:
    st.session_state.running = False
if 'logs' not in st.session_state:
    st.session_state.logs = []


# ============ 主界面 ============

# --- 状态区域 ---
st.subheader("📦 当前状态")

works = st.session_state.works
stats = get_stats(works)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("作品总数", stats["total"])
with col2:
    st.metric("有尺寸", f"{stats['has_size']} ({stats['size_pct']:.0f}%)")
with col3:
    st.metric("有时长", stats["has_duration"])
with col4:
    st.metric("有年份", stats["has_year"])

st.divider()

# --- 主操作区域 ---
st.subheader("🚀 一键抓取")
st.markdown("""
**工作流程：** 获取 sitemap → 提取数据（三层优化）→ 过滤展览 → 保存

- **第1层：** 本地 HTML 解析（0 credits）
- **第2层：** Markdown 抓取 + 正则（1 credit）
- **第3层：** LLM 提取（2 credits）- 仅在必要时使用
""")

# 高级选项（默认折叠）
with st.expander("⚙️ 高级选项"):
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        incremental = st.checkbox(
            "增量更新",
            value=True,
            help="仅获取新增/更新的页面（基于 sitemap lastmod）"
        )
    with col_opt2:
        max_workers = st.slider(
            "并发数",
            min_value=1,
            max_value=8,
            value=4,
            help="并行提取的工作线程数"
        )

# 运行按钮
if st.button(
    "🚀 开始抓取",
    disabled=st.session_state.running,
    type="primary",
    use_container_width=True
):
    st.session_state.running = True
    st.session_state.logs = []

    progress_bar = st.progress(0)
    status_text = st.empty()
    log_area = st.empty()

    def progress_callback(msg: str, pct: float):
        st.session_state.logs.append(msg)
        progress_bar.progress(pct)
        status_text.text(msg)
        log_area.code("\n".join(st.session_state.logs[-10:]))

    try:
        scraper = AaajiaoScraper()
        result = scraper.run_full_pipeline(
            incremental=incremental,
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

        st.session_state.works = result["works"]
        stats = result["stats"]

        st.success(
            f"✅ 完成！提取了 {stats['extracted']} 个作品，"
            f"跳过了 {stats['skipped_exhibitions']} 个展览，"
            f"共保存 {stats['total']} 个作品。"
        )
        st.balloons()

    except Exception as e:
        st.error(f"错误：{str(e)}")
    finally:
        st.session_state.running = False

st.divider()

# --- 输出区域 ---
st.subheader("📥 输出文件")

col_dl1, col_dl2 = st.columns(2)

with col_dl1:
    try:
        with open("aaajiao_works.json", "rb") as f:
            st.download_button(
                label="📄 下载 JSON",
                data=f,
                file_name="aaajiao_works.json",
                mime="application/json",
                use_container_width=True
            )
    except FileNotFoundError:
        st.info("JSON 文件尚未生成")

with col_dl2:
    try:
        with open("aaajiao_portfolio.md", "rb") as f:
            st.download_button(
                label="📝 下载 Markdown",
                data=f,
                file_name="aaajiao_portfolio.md",
                mime="text/markdown",
                use_container_width=True
            )
    except FileNotFoundError:
        st.info("Markdown 文件尚未生成")

# --- 数据预览区域 ---
with st.expander("📋 数据预览", expanded=bool(works)):
    if works:
        df = pd.DataFrame(works)
        # 定义所有可用列及其显示名称
        all_columns = {
            'title': '标题',
            'title_cn': '中文标题',
            'year': '年份',
            'type': '类型',
            'materials': '材料',
            'size': '尺寸',
            'duration': '时长',
            'description_cn': '中文描述',
            'description_en': '英文描述',
            'video_link': '视频链接',
            'tags': '标签',
            'url': '链接'
        }
        # 默认显示的列
        default_cols = ['title', 'title_cn', 'year', 'type', 'materials', 'size', 'duration']
        available_cols = [c for c in all_columns.keys() if c in df.columns]

        # 列选择器
        selected_cols = st.multiselect(
            "选择显示的列",
            options=available_cols,
            default=[c for c in default_cols if c in available_cols],
            format_func=lambda x: all_columns.get(x, x)
        )

        if selected_cols:
            # 重命名列为中文显示
            display_df = df[selected_cols].copy()
            display_df.columns = [all_columns.get(c, c) for c in selected_cols]
            st.dataframe(display_df.head(100), use_container_width=True)
            st.caption(f"显示 {min(100, len(works))}/{len(works)} 个作品")
        else:
            st.warning("请至少选择一列")
    else:
        st.info("暂无数据。点击「开始抓取」开始。")

st.divider()

# ============ 图片工具区域 ============

st.subheader("🖼️ 图片工具")

# 加载缓存的作品用于图片工具
scraper_preview = AaajiaoScraper()
cached_works = scraper_preview.get_all_cached_works()
# 仅过滤为作品
cached_works = [w for w in cached_works if is_artwork(w)]

if cached_works:
    st.success(f"📦 找到 {len(cached_works)} 个已缓存作品")

    # --- 功能 1：图片整合 ---
    with st.expander("🖼️ 图片整合（下载到本地）"):
        st.markdown("""
        从缓存的作品中提取并下载图片。
        - 使用 HTML 解析（无 API 成本）
        - 下载到 `output/images/`
        """)

        col_img1, col_img2 = st.columns(2)
        with col_img1:
            download_images = st.checkbox("下载图片", value=True)
        with col_img2:
            img_limit = st.slider(
                "处理作品数",
                min_value=1,
                max_value=len(cached_works),
                value=min(50, len(cached_works))
            )

        merge_full_metadata = st.checkbox(
            "合并完整元数据",
            value=False,
            help="从 aaajiao_works.json 合并完整作品信息（类型、材料、尺寸、描述等）",
            key="local_merge_checkbox"
        )

        if st.button("🖼️ 开始图片整合", key="enrich_btn"):
            progress = st.progress(0)
            status = st.empty()

            full_works = []
            if merge_full_metadata:
                full_works = load_existing_works()
                if not full_works:
                    st.warning("⚠️ 未找到 aaajiao_works.json，将使用缓存数据")

            scraper = AaajiaoScraper()
            works_to_process = cached_works[:img_limit]
            enriched_works = []

            for i, work in enumerate(works_to_process):
                title = work.get("title", "未知")[:30]
                status.text(f"[{i+1}/{len(works_to_process)}] {title}...")

                try:
                    enriched = scraper.enrich_work_with_images(work, output_dir="output")
                    if merge_full_metadata and full_works:
                        enriched = merge_work_with_full_data(enriched, full_works)
                    enriched_works.append(enriched)
                except Exception as e:
                    st.warning(f"失败：{title} - {e}")
                    enriched_works.append(work)

                progress.progress((i + 1) / len(works_to_process))

            # 生成报告
            if merge_full_metadata:
                report_lines = [
                    "# aaajiao 作品集（完整元数据 + 图片）\n",
                    f"*生成时间：{time.strftime('%Y-%m-%d %H:%M')}*\n\n"
                ]
                for work in enriched_works:
                    report_lines.append(generate_rich_work_markdown(work, include_local_images=True))
            else:
                report_lines = [
                    "# aaajiao 作品集（含图片）\n",
                    f"*生成时间：{time.strftime('%Y-%m-%d %H:%M')}*\n\n"
                ]
                for work in enriched_works:
                    title = work.get("title", "无标题")
                    year = work.get("year", "")
                    local_images = work.get("local_images", [])

                    report_lines.append(f"## {title}\n")
                    report_lines.append(f"**年份：** {year}\n\n")

                    if local_images:
                        report_lines.append("### 图片\n\n")
                        for img_path in local_images[:10]:
                            rel_path = os.path.basename(img_path)
                            report_lines.append(f"![图片]({rel_path})\n\n")

                    report_lines.append("---\n\n")

            report_content = "".join(report_lines)

            os.makedirs("output", exist_ok=True)
            with open("output/portfolio_with_images.md", "w", encoding="utf-8") as f:
                f.write(report_content)

            st.success("✅ 图片整合完成！")
            st.download_button(
                label="📥 下载报告",
                data=report_content,
                file_name="aaajiao_portfolio_images.md",
                mime="text/markdown"
            )

    # --- 功能 2：网络图片报告 ---
    with st.expander("🌐 网络图片报告（不下载）"):
        st.markdown("生成轻量报告，使用在线图片链接。")

        web_merge_full_metadata = st.checkbox(
            "合并完整元数据",
            value=False,
            help="从 aaajiao_works.json 合并完整作品信息（类型、材料、尺寸、描述等）",
            key="web_merge_checkbox"
        )

        if st.button("📄 生成网络报告", key="web_report_btn"):
            progress = st.progress(0)
            status = st.empty()

            full_works = []
            if web_merge_full_metadata:
                full_works = load_existing_works()
                if not full_works:
                    st.warning("⚠️ 未找到 aaajiao_works.json，将使用缓存数据")

            # 按年份排序
            def get_sort_year(w):
                y = w.get("year", "0000")
                if "-" in str(y):
                    return str(y).split("-")[-1]
                return str(y)

            sorted_works = sorted(cached_works, key=get_sort_year, reverse=True)

            if web_merge_full_metadata:
                lines = [
                    "# aaajiao 作品集（完整元数据）\n",
                    f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}\n",
                    "> **注意**：图片为 eventstructure.com 的直链\n\n",
                    "---\n\n"
                ]
            else:
                lines = [
                    "# aaajiao 作品集（网络图片）\n",
                    f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}\n",
                    "> **注意**：图片为 eventstructure.com 的直链\n\n",
                    "---\n\n"
                ]

            scraper = AaajiaoScraper()

            for i, work in enumerate(sorted_works):
                status.text(f"处理中 {i+1}/{len(sorted_works)}...")
                progress.progress((i + 1) / len(sorted_works))

                if web_merge_full_metadata and full_works:
                    work = merge_work_with_full_data(work, full_works)

                # 获取图片（如果没有）
                imgs = work.get("images", []) or work.get("high_res_images", [])
                if not imgs and work.get("url"):
                    try:
                        imgs = scraper.extract_images_from_page(work.get("url"))
                        work["images"] = imgs
                    except Exception:
                        pass

                if web_merge_full_metadata:
                    lines.append(generate_rich_work_markdown(work, include_local_images=False))
                else:
                    title = work.get("title", "无标题")
                    year = work.get("year", "")
                    url = work.get("url", "")

                    lines.append(f"## {year} - {title}\n\n")
                    lines.append(f"**链接：** [{url}]({url})\n\n")

                    if imgs:
                        lines.append("### 图片\n\n")
                        for img in imgs[:5]:
                            lines.append(f"![]({img})\n\n")

                    lines.append("---\n\n")

            report = "".join(lines)

            st.success(f"✅ 已为 {len(sorted_works)} 个作品生成报告！")
            st.download_button(
                label="📥 下载网络报告",
                data=report,
                file_name="aaajiao_web_images_report.md",
                mime="text/markdown"
            )

else:
    st.warning("⚠️ 未找到已缓存作品。请先运行「开始抓取」。")


# ============ 侧边栏 ============

with st.sidebar:
    st.markdown("### 控制台")
    st.markdown("---")
    st.markdown("**成本优化：**")
    st.markdown("- 第1层：0 credits（本地）")
    st.markdown("- 第2层：1 credit（markdown）")
    st.markdown("- 第3层：2 credits（LLM）")
    st.markdown("---")
    st.markdown("**过滤规则：**")
    st.markdown("- ✅ 仅作品")
    st.markdown("- ❌ 排除展览")
    st.markdown("- ❌ 排除画册")
    st.markdown("---")

    if st.button("🔄 重新加载数据"):
        st.session_state.works = load_existing_works()
        st.rerun()

    if st.button("❌ 退出应用"):
        st.warning("正在退出...")
        time.sleep(1)
        os._exit(0)
