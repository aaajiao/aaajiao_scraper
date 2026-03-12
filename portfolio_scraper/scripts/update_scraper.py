from pathlib import Path

TARGET_FILE = Path(__file__).resolve().parents[1] / "scraper" / "firecrawl.py"

NEW_METHOD = r'''    def agent_search(self, prompt: str, urls: Optional[List[str]] = None, max_credits: int = 50) -> Optional[Dict[str, Any]]:
        """
        智能搜索/提取入口
        
        策略分离:
        1. 指定 URLs -> 使用 v2/extract 批量提取 -> 针对已知页面进行结构化/内容提取
        2. 无 URLs (开放查询) -> 使用 v2/agent -> 成本高 (自主调研)
        """
        
        # === 场景 1: 批量提取 (指定 URL) ===
        if urls and len(urls) > 0:
            # 限制 URL 数量以符合 Max Credits
            target_urls = urls[:max_credits]
            logger.info(f"🚀 启动批量提取任务 (Target: {len(target_urls)} URLs)")
            logger.info(f"   Prompt: {prompt}")
            
            extract_endpoint = "https://api.firecrawl.dev/v2/extract"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "urls": target_urls,
                "prompt": prompt,
                "enableWebSearch": False
            }
            
            # Check for high-res instruction
            if "src_o" in prompt:
                 pass

            try:
                # 1. 提交任务
                resp = requests.post(extract_endpoint, json=payload, headers=headers, timeout=self.FC_TIMEOUT)
                
                if resp.status_code != 200:
                    logger.error(f"Extract 启动失败: {resp.status_code} - {resp.text}")
                    return None
                    
                result = resp.json()
                if not result.get("success"):
                    logger.error(f"Extract 启动失败: {result}")
                    return None
                
                job_id = result.get("id")
                if not job_id:
                     if result.get("status") == "completed":
                         return result.get("data")
                     return None

                # 2. 轮询等待
                logger.info(f"   Extract 任务 ID: {job_id}")
                status_endpoint = f"{extract_endpoint}/{job_id}"
                max_wait = 600 # 10分钟
                poll_interval = 5
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=self.FC_TIMEOUT)
                    if status_resp.status_code != 200: continue
                    
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    
                    if status == "processing":
                        logger.info(f"   ⏳ 提取中... ({elapsed}s)")
                    elif status == "completed":
                        credits = status_data.get("creditsUsed", "N/A")
                        logger.info(f"✅ 提取完成 (Credits: {credits})")
                        # Return 'data' field directly (which is a list of results for extract endpoint)
                        return {"data": status_data.get("data")}
                    elif status == "failed":
                        logger.error(f"提取任务失败: {status_data}")
                        return None
                        
                return None
                
            except Exception as e:
                logger.error(f"Extract Exception: {e}")
                return None

        # === 场景 2: 开放式 Agent 搜索 (无 URL) ===
        else:
            logger.info(f"🤖 启动 Smart Agent 任务 (开放搜索)...")
            logger.info(f"   Prompt: {prompt}")
            
            agent_endpoint = "https://api.firecrawl.dev/v2/agent"
            headers = {
                "Authorization": f"Bearer {self.firecrawl_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": prompt,
                "maxCredits": max_credits
            }
            
            try:
                # 1. 启动 Agent 任务
                resp = requests.post(agent_endpoint, json=payload, headers=headers, timeout=self.FC_TIMEOUT)
                
                if resp.status_code != 200:
                    logger.error(f"Agent 启动失败: {resp.status_code} - {resp.text[:200]}")
                    return None
                
                result = resp.json()
                
                if not result.get("success"):
                    logger.error(f"Agent 启动失败: {result}")
                    return None
                
                job_id = result.get("id")
                
                if not job_id:
                    # 同步模式
                    if result.get("status") == "completed":
                        logger.info(f"✅ Agent 任务完成 (credits: {result.get('creditsUsed', 'N/A')})")
                        return result.get("data")
                    return None
                
                # 2. 轮询等待任务完成
                logger.info(f"   任务 ID: {job_id}")
                status_endpoint = f"{agent_endpoint}/{job_id}"
                max_wait = 300 
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(5)
                    elapsed += 5
                    
                    status_resp = requests.get(status_endpoint, headers=headers, timeout=self.FC_TIMEOUT)
                    
                    if status_resp.status_code != 200: continue
                    
                    status_data = status_resp.json()
                    status = status_data.get("status")
                    
                    if status == "processing":
                        logger.info(f"   ⏳ 处理中... ({elapsed}s)")
                        continue
                    elif status == "completed":
                        credits_used = status_data.get("creditsUsed", "N/A")
                        logger.info(f"✅ Agent 任务完成 (耗时: {elapsed}s, credits: {credits_used})")
                        return status_data.get("data")
                    elif status == "failed":
                        logger.error(f"Agent 任务失败: {status_data}")
                        return None
                
                logger.error(f"Agent 任务超时 ({max_wait}s)")
                return None
                
            except Exception as e:
                logger.error(f"Agent 请求错误: {e}")
                return None
'''

def update_file():
    with TARGET_FILE.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Define the range to replace (0-indexed) working with lines 560 to 713 (1-indexed)
    # So index 559 to 713
    
    start_idx = 559
    end_idx = 713
    
    # Basic Validation
    if "def agent_search" not in lines[start_idx]:
        print(f"Error: Line {start_idx+1} does not contain 'def agent_search'. Aborting.")
        # Try to find it
        for i, line in enumerate(lines):
            if "def agent_search" in line:
                print(f"Found 'def agent_search' at line {i+1}")
                start_idx = i
                break
    
    # Find the end of the method by looking for next method or end of indent block?
    # Simple hardcoded check since we viewed the file
    pass

    new_lines = lines[:start_idx] + [NEW_METHOD + "\n"] + lines[end_idx:]
    
    with TARGET_FILE.open("w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    print("File updated successfully.")

if __name__ == "__main__":
    update_file()
