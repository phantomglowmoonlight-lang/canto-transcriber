"""
全域配置管理，基於 pydantic-settings，支援 .env 覆蓋
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ─── 語音識別 ───
    whisper_model_size: str = "large-v3"
    whisper_device: str = "cuda"    # GPU 加速（無 CUDA 時自動降級 CPU）
    whisper_compute_type: str = "float16"
    # 本機模型路徑（預先下載後設定，留空則自動從 HuggingFace 下載到 cache_dir）
    whisper_model_path: str = ""

    # ─── 粵語→書面語翻譯 ───
    # 翻譯模型路徑（執行 download_models.py 下載後自動填入）
    translation_model_path: str = ""

    # ─── 音頻處理 ───
    chunk_max_minutes: int = 10
    chunk_overlap_seconds: int = 30
    sample_rate: int = 16000

    # ─── 說話人分離 ───
    diarization_mode: str = "auto"  # auto / pyannote / vad
    hf_token: str = ""

    # ─── AI 會議報告 ───
    llm_provider: str = "ollama"
    llm_api_base: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "gemma3:12b"
    report_language: str = "zh"

    # ─── API 伺服器 ───
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ─── 外部工具路徑 ───
    ffmpeg_path: str = ""  # 留空自動搜尋 PATH；可設為絕對路徑如 C:\ffmpeg\bin\ffmpeg.exe

    # ─── 路徑 ───
    tasks_dir: str = "tasks"
    cache_dir: str = ""  # 留空用 faster-whisper 預設快取

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def tasks_path(self) -> Path:
        p = Path(self.tasks_dir)
        if not p.is_absolute():
            p = Path.cwd() / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def audio_max_duration_sec(self) -> float:
        """單段最長秒數（用於切割判斷）"""
        return self.chunk_max_minutes * 60.0


# 全域單例
settings = Settings()

# 載入使用者 UI 設定（覆蓋 .env 中的值）
try:
    from app.settings_manager import load_ui_settings, UI_SETTINGS_KEYS
    ui_settings = load_ui_settings(settings.tasks_path)
    for key, val in ui_settings.items():
        if hasattr(settings, key):
            setattr(settings, key, val)
            logger = __import__("logging").getLogger(__name__)
            logger.info(f"從 settings.json 載入設定：{key}")
except Exception:
    pass  # 非致命，使用 .env 中的值
