#!/usr/bin/env python3
"""
aaajiao Scraper GUI
图形化界面启动器
"""

import sys
import os
import threading
import logging
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess

# 导入核心爬虫逻辑
try:
    from aaajiao_scraper import AaajiaoScraper
except ImportError:
    messagebox.showerror("错误", "找不到 aaajiao_scraper.py 文件！")
    sys.exit(1)

class TextHandler(logging.Handler):
    """
    自定义日志处理器，将日志发送到GUI
    """
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)

class ScraperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("aaajiao 作品集爬虫工具")
        self.root.geometry("600x500")
        
        # 居中显示
        self._center_window()
        
        # 变量
        self.is_running = False
        self.log_queue = queue.Queue()
        self.progress_var = tk.DoubleVar()
        self.status_var = tk.StringVar(value="准备就绪")
        
        # 界面布局
        self._create_widgets()
        
        # 设置自定义日志处理
        self._setup_logging()
        
        # 启动定时器检查日志队列
        self.root.after(100, self._process_log_queue)

    def _center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _create_widgets(self):
        # 1. 顶部控制区
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        
        # 标题
        ttk.Label(top_frame, text="aaajiao Scraper", font=("Helvetica", 16, "bold")).pack(side=tk.LEFT)
        
        # 开始按钮
        self.btn_start = ttk.Button(top_frame, text="开始抓取", command=self.start_scraping)
        self.btn_start.pack(side=tk.RIGHT, padx=5)
        
        # 2. 状态和进度区
        status_frame = ttk.Frame(self.root, padding="10")
        status_frame.pack(fill=tk.X)
        
        ttk.Label(status_frame, textvariable=self.status_var, foreground="gray").pack(anchor=tk.W)
        
        self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))
        
        # 3. 日志区
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', height=10, font=("Menlo", 11))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置日志颜色标签
        self.log_text.tag_config('INFO', foreground='black')
        self.log_text.tag_config('WARNING', foreground='orange')
        self.log_text.tag_config('ERROR', foreground='red')
        
        # 4. 底部按钮
        bottom_frame = ttk.Frame(self.root, padding="10")
        bottom_frame.pack(fill=tk.X)
        
        self.btn_open_folder = ttk.Button(bottom_frame, text="打开输出文件夹", command=self.open_output_folder, state='disabled')
        self.btn_open_folder.pack(side=tk.RIGHT)
        
        ttk.Label(bottom_frame, text="© aaajiao scraper tool", font=("Arial", 9), foreground="gray").pack(side=tk.LEFT)

    def _setup_logging(self):
        # 创建自定义 Handler
        self.text_handler = TextHandler(self.log_queue)
        self.text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
        
        # 获取 aaajiao_scraper 的 logger 并添加 Handler
        self.scraper_logger = logging.getLogger('aaajiao_scraper')
        
        # 确保不会重复添加 handler
        if not any(isinstance(h, TextHandler) for h in self.scraper_logger.handlers):
            self.scraper_logger.addHandler(self.text_handler)
            self.scraper_logger.setLevel(logging.INFO)

        # 同时监听 requests 的日志以便捕获错误（可选）
        # logging.getLogger('urllib3').addHandler(self.text_handler)

    def _process_log_queue(self):
        """定期从队列读取日志并更新UI"""
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.configure(state='normal')
            
            # Simple color coding based on message content
            tag = 'INFO'
            if 'WARNING' in msg: tag = 'WARNING'
            if 'ERROR' in msg: tag = 'ERROR'
            
            self.log_text.insert(tk.END, msg + '\n', tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state='disabled')
            
            # 尝试解析进度
            self._parse_progress(msg)
            
        self.root.after(100, self._process_log_queue)

    def _parse_progress(self, msg):
        """简单的日志解析以更新进度条"""
        # 解析 "找到 X 件作品" 来设置最大值
        if "找到" in msg and "件作品" in msg:
            try:
                import re
                match = re.search(r'找到 (\d+)', msg)
                if match:
                    total = int(match.group(1))
                    self.progress_bar.configure(maximum=total)
                    self.status_var.set(f"发现 {total} 个作品，准备下载...")
            except:
                pass

        # 解析 "[1/54] 完成:"
        if "完成:" in msg and "[" in msg:
            try:
                import re
                match = re.search(r'\[(\d+)/', msg)
                if match:
                    current = int(match.group(1))
                    self.progress_var.set(current)
            except:
                pass
        
        # 解析完成
        if "抓取结束" in msg:
            self.status_var.set("抓取任务完成！")
            self.progress_var.set(self.progress_bar['maximum'])

    def start_scraping(self):
        if self.is_running:
            return
            
        self.is_running = True
        self.btn_start.configure(state='disabled')
        self.btn_open_folder.configure(state='disabled')
        self.progress_var.set(0)
        self.status_var.set("正在初始化...")
        
        # 清空日志
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        
        # 在新线程运行爬虫
        threading.Thread(target=self._run_scraper_thread, daemon=True).start()

    def _run_scraper_thread(self):
        try:
            self.log_queue.put("INFO - 脚本启动...")
            
            scraper = AaajiaoScraper()
            # 注入 logger (如果 scraper 使用的是 global logger, setup_logging 已经处理了)
            
            # 1. 抓取
            scraper.scrape_all()
            
            # 2. 保存
            scraper.save_to_json()
            scraper.generate_markdown()
            
            self.log_queue.put("INFO - 所有任务已完成。")
            
            # 完成回调
            self.root.after(0, self._on_finished_success)
            
        except Exception as e:
            self.log_queue.put(f"ERROR - 发生未捕获异常: {str(e)}")
            self.root.after(0, self._on_finished_error)

    def _on_finished_success(self):
        self.is_running = False
        self.btn_start.configure(state='normal')
        self.btn_open_folder.configure(state='normal')
        messagebox.showinfo("成功", "所有作品已抓取并生成文档！")

    def _on_finished_error(self):
        self.is_running = False
        self.btn_start.configure(state='normal')
        messagebox.showerror("错误", "运行过程中发生错误，请检查日志。")

    def open_output_folder(self):
        path = os.getcwd()
        subprocess.call(["open", path])

if __name__ == "__main__":
    root = tk.Tk()
    app = ScraperApp(root)
    root.mainloop()
