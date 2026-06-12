"""
桌面應用啟動器：使用 pywebview 內嵌 Web UI，完全原生視窗體驗
"""
import sys
import os
import threading
import logging

# 確保專案根目錄在 path 中
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

logger = logging.getLogger("desktop")


def _start_server(host: str = "127.0.0.1", port: int = 8000):
    """在背景執行緒啟動 FastAPI 伺服器"""
    import uvicorn
    from app.api_server import app

    # 抑制 uvicorn 的 logger 以免干擾
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(app, host=host, port=port, log_level="warning")


def run_desktop():
    """主入口：啟動伺服器 → 開啟原生視窗"""
    import webview

    HOST = "127.0.0.1"
    PORT = 8000
    URL = f"http://{HOST}:{PORT}"

    # 背景啟動 API 伺服器
    server_thread = threading.Thread(
        target=_start_server,
        args=(HOST, PORT),
        daemon=True,
    )
    server_thread.start()

    # 等待伺服器就緒
    import time
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(f"{URL}/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # 建立原生視窗
    window = webview.create_window(
        title="廣東話會議錄音轉文字",
        url=URL,
        width=1280,
        height=860,
        min_size=(960, 640),
        resizable=True,
        confirm_close=True,
    )

    webview.start(debug=False)
