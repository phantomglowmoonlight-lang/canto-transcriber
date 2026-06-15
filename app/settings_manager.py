"""
設定持久化管理：將 UI 可配置的設定儲存為 JSON 檔案
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 可被 UI 設定的欄位（白名單）
UI_SETTINGS_KEYS = {
    "llm_provider",
    "llm_api_base",
    "llm_api_key",
    "llm_model",
    "report_language",
}


def get_settings_path(tasks_dir: Path) -> Path:
    """settings.json 存放在 tasks 目錄上層（應用資料目錄）"""
    return tasks_dir.parent / "settings.json"


def load_ui_settings(tasks_dir: Path) -> dict:
    """從 settings.json 載入使用者 UI 設定"""
    path = get_settings_path(tasks_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in UI_SETTINGS_KEYS}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"無法讀取 {path}：{e}")
        return {}


def save_ui_settings(tasks_dir: Path, settings: dict) -> dict:
    """儲存 UI 設定到 settings.json，回傳實際儲存的內容"""
    path = get_settings_path(tasks_dir)
    # 僅儲存白名單欄位
    allowed = {k: v for k, v in settings.items() if k in UI_SETTINGS_KEYS}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"設定已儲存到 {path}")
    except OSError as e:
        logger.error(f"無法寫入 {path}：{e}")
        raise
    return allowed


def mask_api_key(key: str) -> str:
    """模糊化 API Key，只顯示前 4 和後 4 字元"""
    if not key or len(key) < 12:
        return key[:4] + "****" if key else ""
    return key[:4] + "****" + key[-4:]
