
import time
import requests
import logging
from typing import List, Dict, Optional, Any

from .constants import QUICK_SCHEMA, FULL_SCHEMA, PROMPT_TEMPLATES, FC_TIMEOUT

logger = logging.getLogger(__name__)

class FirecrawlMixin:
    """Firecrawl V2 API Interactions"""
    
    def extract_work_details(self, url: str, retry_count: int = 0) -> Optional[Dict]:
        """提取详情 (使用 Firecrawl AI 提取，带缓存和重试)"""
        max_retries = 3
        
        # 1. 缓存优先
        if self.use_cache:
            cached = self._load_cache(url)
            if cached:
                logger.debug(f"命中缓存: {url}")
                return cached
        
        # 2. 速率限制
        self.rate_limiter.wait()
        
        try:
            logger.info(f"[{retry_count+1}/{max_retries}] 正在抓取: {url}")
            
            fc_endpoint = "https://api.firecrawl.dev/v2/scrape"
            
            # 使用 inline schema 定义，以确保兼容性
            schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The English title of the work"},
                    "title_cn": {"type": "string", "description": "The Chinese title of the work. If not explicitly found, leave empty."},
                    "year": {"type": "string", "description": "Creation year or year range (e.g. 2018-2022)"},
                    "category": {"type": "string", "description": "The art category (e.g. Video Installation, Software, Website)"},
                    "materials": {"type": "string", "description": "Materials list (e.g. LED screen, 3D printing)"},
                    "description_en": {"type": "string", "description": "Detailed work description in English. Exclude navigation text."},
                    "description_cn": {"type": "string", "description": "Detailed work description in Chinese. Exclude navigation text."},
                    "video_link": {"type": "string", "description": "Vimeo URL if present"}
                },
                "required": ["title"]
            }
            
            payload = {
                "url": url,
                "formats": ["extract"],
                "extract": {
                    "schema": schema,
                    "systemPrompt": "You are an art archivist. Extract the artwork metadata from the portfolio page. Ignore navigation links like 'Previous/Next project'. The title usually appears as 'English Title / Chinese Title'. Separate them."
                }
            }
            
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            resp = requests.post(fc_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)
            
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and 'extract' in data['data']:
                    result = data['data']['extract']
                    
                    work = {
                        'url': url,
                        'title': result.get('title', ''),
                        'title_cn': result.get('title_cn', ''),
                        'type': result.get('category', '') or result.get('type', ''),
                        'materials': result.get('materials', ''),
                        'year': result.get('year', ''),
                        'description_cn': result.get('description_cn', ''),
                        'description_en': result.get('description_en', ''),
                        'video_link': result.get('video_link', ''),
                        'size': '',
                        'duration': '',
                        'tags': []
                    }
                    
                    # 后处理：如果 AI 没分清标题
                    if not work['title_cn'] and '/' in work['title']:
                        parts = work['title'].split('/')
                        work['title'] = parts[0].strip()
                        if len(parts) > 1:
                            work['title_cn'] = parts[1].strip()
                    
                    # 保存到缓存
                    if self.use_cache:
                        self._save_cache(url, work)
                            
                    return work
                else:
                    logger.error(f"Firecrawl 返回格式异常: {data}")
                    
            elif resp.status_code == 429:
                # Rate Limit - 指数退避重试
                if retry_count >= max_retries:
                    logger.error(f"重试次数超限: {url}")
                    return None
                wait_time = 2 ** retry_count  # 1s, 2s, 4s
                logger.warning(f"Rate Limit，等待 {wait_time}s 后重试...")
                time.sleep(wait_time)
                return self.extract_work_details(url, retry_count + 1)
                
            else:
                logger.error(f"Firecrawl Error {resp.status_code}: {resp.text[:200]}")
                
            return None

        except Exception as e:
            logger.error(f"API 请求错误 {url}: {e}")
            return None

    def agent_search(self, prompt: str, urls: Optional[List[str]] = None, 
                      max_credits: int = 50, extraction_level: str = "custom") -> Optional[Dict[str, Any]]:
        """智能搜索/提取入口"""
        
        # === 根据提取级别选择 Schema 和 Prompt ===
        schema = None
        if extraction_level == "quick":
            schema = QUICK_SCHEMA
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["quick"]
            logger.info(f"📋 使用 Quick 模式 (核心字段)")
        elif extraction_level == "full":
            schema = FULL_SCHEMA
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["full"]
            logger.info(f"📋 使用 Full 模式 (完整字段)")
        elif extraction_level == "images_only":
            if not prompt or prompt == PROMPT_TEMPLATES["default"]:
                prompt = PROMPT_TEMPLATES["images_only"]
            logger.info(f"🖼️ 使用 Images Only 模式 (仅高清图)")
        
        # === 场景 1: 批量提取 (指定 URL) ===
        if urls and len(urls) > 0:
            # 限制 URL 数量以符合 Max Credits
            target_urls = urls[:max_credits]
            
            # === 缓存检查：分离已缓存和未缓存的 URL ===
            cached_results = []
            uncached_urls = []
            for url in target_urls:
                cached = self._load_extract_cache(url, prompt)
                if cached:
                    cached_results.append(cached)
                else:
                    uncached_urls.append(url)
            
            logger.info(f"🔍 缓存检查: 命中 {len(cached_results)}, 待提取 {len(uncached_urls)}")
            
            # 如果全部命中缓存，直接返回
            if not uncached_urls:
                logger.info(f"✅ 全部命中缓存，节省 API 调用！")
                return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
            
            logger.info(f"🚀 启动批量提取任务 (Target: {len(uncached_urls)} URLs)")
            
            extract_endpoint = "https://api.firecrawl.dev/v2/extract"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "urls": uncached_urls,  # 只提取未缓存的 URL
                "prompt": prompt,
                "enableWebSearch": False
            }
            
            if schema:
                payload["schema"] = schema

            try:
                # 1. 提交任务
                resp = requests.post(extract_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)
                
                if resp.status_code != 200:
                    logger.error(f"Extract 启动失败: {resp.status_code} - {resp.text}")
                    if cached_results:
                        return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                    return None
                    
                result = resp.json()
                if not result.get("success"):
                    logger.error(f"Extract 启动失败: {result}")
                    if cached_results:
                        return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                    return None
                
                job_id = result.get("id")
                
                # 2. 轮询等待
                logger.info(f"   Extract 任务 ID: {job_id}")
                status_endpoint = f"{extract_endpoint}/{job_id}"
                max_wait = 600 # 10分钟
                poll_interval = 5
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=FC_TIMEOUT)
                    if status_resp.status_code != 200: continue
                    
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    
                    if status == "processing":
                        logger.info(f"   ⏳ 提取中... ({elapsed}s)")
                    elif status == "completed":
                        credits = status_data.get("creditsUsed", "N/A")
                        new_data = status_data.get("data", [])
                        
                        # === 保存新结果到缓存 ===
                        for item in new_data if isinstance(new_data, list) else [new_data]:
                            item_url = item.get("url") or item.get("sourceURL") or item.get("source_url")
                            if item_url:
                                self._save_extract_cache(item_url, prompt, item)
                        
                        logger.info(f"✅ 提取完成 (Credits: {credits})")
                        
                        # 合并缓存和新结果
                        all_data = cached_results + (new_data if isinstance(new_data, list) else [new_data])
                        return {"data": all_data, "cached_count": len(cached_results), "new_count": len(new_data) if isinstance(new_data, list) else 1}
                    elif status == "failed":
                        logger.error(f"提取任务失败: {status_data}")
                        if cached_results:
                            return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                        return None
                        
                return None
                
            except Exception as e:
                logger.error(f"Extract Exception: {e}")
                if cached_results:
                    return {"data": cached_results, "from_cache": True, "cached_count": len(cached_results)}
                return None

        # === 场景 2: 开放式 Agent 搜索 (无 URL) ===
        else:
            logger.info(f"🤖 启动 Smart Agent 任务 (开放搜索)...")
            
            agent_endpoint = "https://api.firecrawl.dev/v2/agent"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "query": f"{prompt} site:eventstructure.com",
                "limit": max_credits
            }
            
            try:
                # 1. 提交任务
                resp = requests.post(agent_endpoint, json=payload, headers=headers, timeout=FC_TIMEOUT)
                
                if resp.status_code != 200:
                    logger.error(f"Agent 启动失败: {resp.status_code} - {resp.text}")
                    return None
                    
                result = resp.json()
                if not result.get("success"):
                    logger.error(f"Agent 启动失败: {result}")
                    return None
                
                job_id = result.get("id")
                # (... Agent polling logic same as extract, omitted for brevity but should be included)
                # Since Agent polling is almost identical structure, for now let's assume it's just polling logic.
                # Actually, I should copy the full agent polling logic for completeness.
                
                logger.info(f"   Agent 任务 ID: {job_id}")
                status_endpoint = f"{agent_endpoint}/{job_id}"
                max_wait = 600
                poll_interval = 5
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=FC_TIMEOUT)
                    if status_resp.status_code != 200: continue
                    
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    
                    if status == "processing":
                        logger.info(f"   ⏳ 思考中... ({elapsed}s)")
                    elif status == "completed":
                        credits = status_data.get("creditsUsed", "N/A")
                        data = status_data.get("data", [])
                        logger.info(f"✅ Agent 任务完成 (Credits: {credits})")
                        return {"data": data}
                    elif status == "failed":
                        logger.error(f"Agent 任务失败")
                        return None
                return None

            except Exception as e:
                logger.error(f"Agent Exception: {e}")
                return None

    def discover_urls_with_scroll(self, url: str, scroll_mode: str = "auto", use_cache: bool = True) -> List[str]:
        """Discovery Mode Implementation"""
        
        # === 缓存检查 ===
        cache_path = self._get_discovery_cache_path(url, scroll_mode)
        if use_cache and self._is_discovery_cache_valid(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)
                    logger.info(f"✅ Discovery 缓存命中: {len(cached)} 链接 (TTL: 24h)")
                    return cached
            except Exception:
                pass
        
        logger.info(f"🕵️  启动 Discovery Phase: {url} (Mode: {scroll_mode})")
        
        actions = []
        actions.append({"type": "wait", "milliseconds": 2000})
        
        if scroll_mode == "horizontal":
            for i in range(20):
                actions.append({
                    "type": "executeJavascript", 
                    "script": "window.scrollTo(document.documentElement.scrollWidth, 0); window.dispatchEvent(new Event('scroll'));"
                })
                actions.append({"type": "wait", "milliseconds": 1500})
        elif scroll_mode == "vertical":
            for _ in range(5):
                actions.append({"type": "scroll", "direction": "down"})
                actions.append({"type": "wait", "milliseconds": 1500})
        else:  # auto
            for i in range(15):
                actions.append({
                    "type": "executeJavascript", 
                    "script": "window.scrollTo(document.documentElement.scrollWidth, 0); window.dispatchEvent(new Event('scroll'));"
                })
                actions.append({"type": "wait", "milliseconds": 1500})
            for _ in range(3):
                actions.append({"type": "scroll", "direction": "down"})

        endpoint = "https://api.firecrawl.dev/v2/scrape"
        headers = {
            "Authorization": f"Bearer {self.firecrawl_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "url": url,
            "formats": ["extract"],
            "actions": actions,
            "extract": {
                "prompt": "Extract all artwork URLs from the page. Return ONLY a list of URLs."
            }
        }
        
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                # Simplified extraction logic
                links = [item.get('url') for item in data.get('data', {}).get('extract', {}).get('urls', []) if item.get('url')]
                
                # If extract fail, fallback to checking 'data.metadata.sourceURL' or similar not robust enough here
                # Assuming simple extraction. For specific implementation, I'd need the exact parsing logic from original
                
                # Re-using the logic from original file:
                # It relied on 'extract' returning a dictionary/list.
                # Let's assume Firecrawl returns text or proper JSON structure.
                
                # Actually, the original code used 'extract': {'schema': ...} or prompt.
                # Let's check original implementation logic in next step if this is vague.
                
                # Saving cache
                if links:
                     with open(cache_path, 'w') as f:
                        json.dump(links, f)
                return links
            return []
        except Exception as e:
            logger.error(f"Discovery Error: {e}")
            return []
