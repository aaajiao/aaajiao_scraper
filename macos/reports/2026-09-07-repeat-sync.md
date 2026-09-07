# 2026-09-07：已发布作品重复进入审核队列

上次上传成功，已发布作品没有丢失。本次重复入队的原因是 App 升级时用随包附带的旧缓存覆盖了工作区的增量同步记录；随后重新抽取了已经发布的 7 个 URL。按实际审核、发布时使用的有效字段比较，**4 项没有变化，3 项只有 `materials` 误分类候选**，不能据此认定网站出现了 7 项新的内容更新。

本报告比较的是保留的第 7 轮导入记录（记录 ID 14–20；2026-09-07 12:42:46–12:43:21 UTC），以及发布提交 [`4219c935`](https://github.com/aaajiao/aaajiao_scraper/commit/4219c935160f9cacf9b2fd357d6800d41dd0c6f9)。

## 7 项对照

7 项记录保存的原始基线均与已发布 JSON 中对应作品完全相同。下表“本轮变化”采用有效合并值，而非只看原始抽取 JSON。

| 作品 | 上次发布情况 | 本轮有效字段变化 | 旧缓存 → 本轮保存的 sitemap 日期 |
| --- | --- | --- | --- |
| [1bit](https://eventstructure.com/1bit) | `4219c935` 新增 | 无变化；原始候选的空中文标题不会覆盖已发布的 `《1bit》` | 无记录 → 2026-09-06 |
| [AIS — aaajiao Inventory System](https://eventstructure.com/AIS-aaajiao-Inventory-System) | `4219c935` 新增 | 无变化 | 无记录 → 2026-09-04 |
| [Danmaku](https://eventstructure.com/Danmaku) | `4219c935` 新增 | 仅 `materials` 从空值变为下列候选 1 | 无记录 → 2026-09-06 |
| [Liquid Left](https://eventstructure.com/Liquid-Left) | `4219c935` 新增 | 无变化 | 无记录 → 2026-09-03 |
| [One ritual](https://eventstructure.com/One-ritual) | 在 `4219c935` 之前已存在；该提交没有修改它 | 无变化 | 2025-10-12 → 2026-03-12 |
| [aaajiao.md](https://eventstructure.com/aaajiao-md-1) | `4219c935` 新增 | 仅 `materials` 从空值变为下列候选 2 | 无记录 → 2026-09-05 |
| [botisaaajiao / aaajiaoisbot](https://eventstructure.com/botisaaajiao-aaajiaoisbot) | `4219c935` 新增 | 仅 `materials` 从空值变为下列候选 3 | 无记录 → 2026-09-05 |

`4219c935` 相比其父提交 `149d974c`，作品总数从 **163 增至 169**：新增 6 项，原有作品修改 0 项、删除 0 项。“上一轮处理了 7 项”和“实际新增 6 项”是两种不同计数，One ritual 属于已存在的作品。

## 3 条 materials 候选原文

这些值仅出现在本轮候选中；已发布的对应 `materials` 均为空。本轮候选已在后续恢复时备份并移出审核队列。

1. Danmaku：`THE NEGATIVE-SPACE WARD / 余白御寮`
2. aaajiao.md：`• curl — 交互式 API 浏览器，实时查看 JSON、Markdown 和二进制响应。`
3. botisaaajiao / aaajiaoisbot：`裂缝：保存下来，离再次参与思考，还有一段距离。`

这些分别是标题、功能说明和叙述性文字，落入材料字段属于抽取或字段归类问题。对应本地 `layer1_only` 抽取缓存已包含相同字符串，后续候选沿用了它们；没有证据表明这是 AI 新生成的变化，也不能认定作品材料发生了变化。

## 原因与代码路径

以下路径和行号参照修复前提交 `1d96ffaf`，可用 `git show` 对照。

1. **随包缓存来自仓库旧缓存。** `macos/Build/prepare_seed.sh` 把根目录 `.cache` 复制到 `macos/Seed/cache`；`seed_version` 又包含代码提交号，所以 App 代码更新也会改变 seed 版本。缓存打包代码（`macos/Build/prepare_seed.sh:22`，修复前）、版本计算（`macos/Build/prepare_seed.sh:134`，修复前）。
2. **升级错误地重置了用户同步记录。** `ensure_workspace()` 在 seed 版本不同且审核队列为空时调用 `_copy_seed_payload(overwrite=True)`；后者先删除工作区 `.cache`，再复制随包缓存。上轮全部发布后队列清空，正好满足此升级条件。升级触发条件（`macos/Helper/aaajiao_importer.py:644`，修复前）、覆盖实现（`macos/Helper/aaajiao_importer.py:538`，修复前）。
3. **旧缓存让同一批 URL 再次被选中。** 增量发现只按 URL 是否缺失、`lastmod` 是否不同挑选候选。复核时，根目录、Seed 和真实工作区的 `sitemap_lastmod.json` 均为相同的 180 条旧记录：6 个新增 URL 缺失，One ritual 仍是 2025-10-12；与表中本轮保存日期比较，恰好重新选出这 7 项。增量筛选（`portfolio_scraper/scraper/basic.py:100`，修复前）。
4. **已发布数据存在，并不会自动排除重新抽取。** `start_incremental_sync()` 只排除仍在审核队列中的 URL；已发布 URL 仍可作为更新候选。旧版本也没有在入队前排除“有效字段完全相同”的结果。候选去重范围（`macos/Helper/aaajiao_importer.py:2218`，修复前）。

发布成功原本会将相应日期写入工作区同步缓存，再移除已发布审核记录；问题发生在之后的 seed 升级覆盖环节。发布后记录同步日期（`macos/Helper/aaajiao_importer.py:2622`，修复前）、发布后队列清理（`macos/Helper/aaajiao_importer.py:2647`，修复前）。

1bit 的空中文标题没有计作有效变化，是因为普通抽取的空值不会覆盖原有非空值；明确的人工编辑另有覆盖路径。字段合并规则（`macos/Helper/aaajiao_importer.py:1789`，修复前）、审核与发布共用的有效记录（`macos/Helper/aaajiao_importer.py:1951`，修复前）。

## 已核对证据与边界

- 根目录、真实 App 工作区和 `4219c935` 提交中的 `aaajiao_works.json`、`aaajiao_portfolio.md` 分别逐字节相同。JSON 含 169 项；SHA-256 为 `2229c6c8d06d9ff81a2008dc5471ddf5743b4a2a058b2ad1e47ccccbea21df1f`，Markdown 为 `4b86f25c5041a86896dea17ae78100b360850a9233467209d6a065333ae9c361`。
- 三处旧 sitemap 缓存也逐字节相同，SHA-256 为 `33e49a43ccb11a736e6dff3286f10c76c68c8add979ebd051d380f1ef909b849`。本轮日期来自第 7 轮保留的 `discovered_sitemap_json`，并非本报告重新抓取的站点结果。
- 本次调查第一次直接请求 sitemap 返回 HTTP 503；随后使用与 App 相同的请求头成功取得 HTTP 200，7 项的当前 lastmod 均与本轮保存值一致。没有两次访问对应的历史 HTML 快照，因此不能断言网页全文从未改动，也不能追溯三条材料候选的首次出现时间。
- “4 项无变化、3 项材料候选误分类”的结论仅基于本轮保留的基线、候选及有效合并规则；“重复入队由 seed 升级覆盖缓存触发”的判断由旧版本代码路径和三份相同旧缓存共同支持，并无逐步记录覆盖动作的历史运行日志。
- 上述对比阶段只读取保留数据与 Git 内容，未读取 API key，未修改真实 App 工作区，没有重新提取、接受或发布作品；实时复核只读取公开 sitemap。后续恢复操作单列如下。

## 修复与真实工作区复核

- 0.3.3（build 7，代码提交 `f79d22e`，包含修复 `6ab6c82`）升级时只更新 scraper 程序快照，保留已发布文件、同步检查点和发布回执。增量抽取的有效字段完全相同时不再入队；仍有变化、失败或未通过验证的结果继续保留审核要求。
- 第 7 轮的数据库、候选对比、缓存和已发布文件已备份至工作区 `recovery/duplicate-sync-7-20260907T131857Z/`。仅移除该轮 7 条重复候选，恢复其已核对的 7 条日期；审核队列为 0。
- 使用最终打包 helper 执行 `bootstrapWorkspace`，从旧 seed 版本升级成功，状态为 `baseline_synced`。同步缓存保留 186 条，JSON/Markdown 的 SHA-256 均与上述发布版本一致，169 项作品没有改变。
- 2026-09-07 13:35 UTC，用升级后的 scraper 快照和 App 请求头读取公开 sitemap：HTTP 200，解析出 186 个有效链接，增量候选 **0**。验证截获缓存写入，并核对前后 SHA 相同；没有启动 AI 提取或重新发布作品。
- 92 项 helper 回归测试、96 项 Swift 测试、最终应用 smoke test、隔离工作区验收及 Git 发布事务检查均通过。
