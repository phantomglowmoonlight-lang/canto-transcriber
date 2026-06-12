"""
廣東話會議錄音轉文字 — 桌面應用入口
供 PyInstaller 打包為獨立 exe
"""
from app.desktop import run_desktop

if __name__ == "__main__":
    run_desktop()
