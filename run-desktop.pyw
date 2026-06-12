"""
廣東話會議錄音轉文字 — 桌面應用（雙擊啟動，無 console 視窗）
直接執行：pyw run-desktop.pyw
"""
import sys
import os

# 確保專案根目錄在 path 中
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from app.desktop import run_desktop

if __name__ == "__main__":
    run_desktop()
