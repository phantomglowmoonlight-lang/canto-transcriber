"""
廣東話會議錄音轉文字 — 桌面應用啟動器
pywebview 原生視窗 + 內建 FastAPI 伺服器
"""
import sys
import os
import threading
import time
import urllib.request
import logging
import webview

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

def _start_server(host="127.0.0.1", port=8000):
    import uvicorn
    from app.api_server import app, start_server
    start_server(host=host, port=port)

def run_desktop():
    HOST = "127.0.0.1"
    PORT = 8000
    URL = f"http://{HOST}:{PORT}"

    # 背景啟動伺服器
    t = threading.Thread(target=_start_server, args=(HOST, PORT), daemon=True)
    t.start()

    # 等待伺服器就緒
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{URL}/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    webview.create_window(
        title="廣東話會議錄音轉文字",
        url=URL,
        width=1280,
        height=860,
        min_size=(960, 640),
        resizable=True,
        confirm_close=True,
    )

    webview.start(debug=False)
