"""
語音識別模組：使用 faster-whisper 進行廣東話 STT
"""
import logging
import os
from pathlib import Path
from typing import Optional, Callable

# ─── 確保 cuDNN DLL 能被 ctranslate2 找到 ───
# 1. 開發模式：從 pip 的 nvidia.cudnn 複製 DLL 到 ctranslate2 目錄
# 2. 打包模式：build_exe.py 已直接將 DLL 放入 _internal/ctranslate2/（無需額外動作）
def _register_cudnn_path():
    import importlib, shutil, sys
    if getattr(sys, 'frozen', False):
        return  # PyInstaller 打包時已處理
    try:
        ctranslate2_spec = importlib.util.find_spec("ctranslate2")
        if not ctranslate2_spec or not ctranslate2_spec.origin:
            return
        dst_dir = os.path.dirname(ctranslate2_spec.origin)
        ops_dll = os.path.join(dst_dir, "cudnn_ops_infer64_8.dll")
        if os.path.exists(ops_dll):
            return
        cudnn_spec = importlib.util.find_spec("nvidia.cudnn")
        if not cudnn_spec or not cudnn_spec.origin:
            return
        src_bin = os.path.join(os.path.dirname(cudnn_spec.origin), "bin")
        if not os.path.isdir(src_bin):
            return
        copied = 0
        for f in os.listdir(src_bin):
            if f.endswith(".dll"):
                src = os.path.join(src_bin, f)
                dst = os.path.join(dst_dir, f)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied += 1
        if copied:
            logging.getLogger(__name__).info(f"cuDNN: {copied} 個 DLL 已複製到 ctranslate2")
    except Exception:
        pass

_register_cudnn_path()

from faster_whisper import WhisperModel
from app.config import settings

logger = logging.getLogger(__name__)

# 全域模型快取（同一個 process 內共用）
_model_cache: Optional[WhisperModel] = None


def _get_model() -> WhisperModel:
    """取得或初始化 faster-whisper 模型（懶載入 + 快取）"""
    global _model_cache
    if _model_cache is None:
        device = settings.whisper_device
        compute_type = settings.whisper_compute_type

        logger.info(f"正在載入 faster-whisper 模型：{settings.whisper_model_size}，裝置：{device}")

        model_path = settings.whisper_model_path.strip() if settings.whisper_model_path else None

        def _load(dev, ctype):
            if model_path:
                model_dir = Path(model_path)
                if model_dir.exists() and (model_dir / "config.json").exists():
                    logger.info(f"使用本機模型：{model_path}")
                    return WhisperModel(str(model_dir), device=dev, compute_type=ctype, local_files_only=True)
                else:
                    logger.info(f"從本機目錄載入：{model_path}")
                    return WhisperModel(settings.whisper_model_size, device=dev, compute_type=ctype,
                                        download_root=str(model_dir), local_files_only=True)
            else:
                download_root = settings.cache_dir if settings.cache_dir else None
                return WhisperModel(settings.whisper_model_size, device=dev, compute_type=ctype,
                                    download_root=download_root)

        try:
            _model_cache = _load(device, compute_type)
        except Exception as e:
            if device in ("cuda", "auto"):
                logger.warning(f"CUDA 載入失敗（{e}），降級到 CPU")
                _model_cache = _load("cpu", "int8")
            else:
                raise

        logger.info("模型載入完成")
    return _model_cache


def transcribe_audio(
    wav_path: Path,
    language: str = "yue",
    progress_callback: Optional[Callable[[float], None]] = None,
    initial_prompt: Optional[str] = None,
) -> dict:
    """
    對 WAV 檔案進行廣東話語音識別

    參數:
        initial_prompt: 熱詞提示，用於提高特定詞彙的辨識準確度
                        例如："以下是會議討論：陳偉芝，蕭榮施惠，張浩霖，心理輔導"

    回傳:
    {
        "language": "yue",
        "language_probability": 0.95,
        "duration_sec": 123.4,
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.5, "text": "大家好", "avg_logprob": -0.15},
            ...
        ]
    }
    """
    model = _get_model()

    # 預設熱詞：常見會議用語
    if not initial_prompt:
        initial_prompt = (
            "以下是會議討論，請專注於粵語語音識別。"
            "人物：陳偉芝，蕭榮施惠，張浩霖，胡小龍，林軍司，王教師，"
            "張家英，神順風，王子牙。"
            "詞彙：心理輔導，精神科，躁鬱症，缺課，個案，報告，評估，"
            "考試，學期，家長，治療，藥物，情緒，行為。"
        )

    # faster-whisper 轉寫
    segments_result, info = model.transcribe(
        str(wav_path),
        language=language,
        beam_size=7,
        best_of=5,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
        condition_on_previous_text=True,
        initial_prompt=initial_prompt,
        vad_filter=True,  # Silero VAD 過濾非語音片段
        vad_parameters=dict(
            threshold=0.5,
            min_speech_duration_ms=250,
            max_speech_duration_s=30,
            min_silence_duration_ms=2000,
            speech_pad_ms=400,
        ),
    )

    logger.info(f"偵測語言：{info.language}，機率：{info.language_probability:.2%}")

    segments = []
    for seg in segments_result:
        segments.append({
            "id": seg.id,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "avg_logprob": seg.avg_logprob,
            "no_speech_prob": seg.no_speech_prob,
        })
        if progress_callback and info.duration:
            progress_callback(min(seg.end / info.duration, 1.0))

    # 記錄 VAD 統計
    if segments:
        avg_conf = sum(max(0, 1.0 + s["avg_logprob"]) for s in segments) / len(segments)
        logger.info(f"STT 完成：{len(segments)} 段，平均信心 {avg_conf:.2%}")

    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration_sec": info.duration,
        "segments": segments,
    }


def transcribe_audio_segment(
    wav_path: Path,
    start_sec: float,
    end_sec: float,
    language: str = "yue",
) -> dict:
    """
    對指定時間範圍進行語音識別（用於局部重新 STT）

    回傳格式同 transcribe_audio，但只含該時間段的 segments
    """
    # 注意：faster-whisper 處理完整檔案效率較好，但這裡我們用裁剪後的音檔
    # 時間偏移在呼叫方處理
    result = transcribe_audio(wav_path, language=language)
    return result
