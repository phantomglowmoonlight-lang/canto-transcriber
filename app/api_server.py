"""
FastAPI 伺服器：提供 REST API 與 Web UI
"""
import asyncio
import json
import logging
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import os
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def _parse_speaker_id(sid: str) -> int:
    """從 speaker_id 提取數字序號用於排序"""
    try:
        return int(sid.replace("人物 #", "").split()[0])
    except (ValueError, IndexError):
        return 9999


# ─── 崩潰日誌
def _setup_crash_log():
    _log_path = Path(sys.executable).parent / "crash.log" if getattr(sys, 'frozen', False) else Path.cwd() / "crash.log"
    def _log(exc_type, exc_value, exc_tb):
        ts = datetime.now().isoformat()
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {tb_str}\n")
    sys.excepthook = _log
_setup_crash_log()

from app.config import settings
from app.audio_processor import (
    check_ffmpeg,
    validate_audio_file,
    convert_to_wav,
    split_audio,
    extract_segment,
    apply_noise_reduction,
    apply_volume_boost,
    save_audio_temp,
    get_audio_duration,
    check_for_speech,
)
from app.transcriber import transcribe_audio
from app.diarizer import diarize, assign_speakers_to_stt_segments
from app.text_processor import (
    apply_speaker_names,
    build_speaker_counts,
    merge_adjacent_same_speaker,
    validate_segment_selection,
)
from app.speaker_registry import SpeakerRegistry
from app.exporter import export_txt, export_docx, export_srt
from app.report_generator import generate_report
from app.translator import translate_segments_builtin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="廣東話會議錄音轉文字系統", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 任務儲存 ───

class TaskStore:
    """基於 JSON 檔案的任務儲存，支援原子寫入與快取恢復"""

    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _last_task_path(self) -> Path:
        return self.tasks_dir / "_last_task.txt"

    def save(self, task: dict):
        """原子化寫入：先寫 .tmp 再 rename，確保不損壞"""
        path = self._task_path(task["task_id"])
        temp_path = path.with_suffix(".tmp")
        data = json.dumps(task, ensure_ascii=False, indent=2)
        temp_path.write_text(data, encoding="utf-8")
        # Windows 上 rename 會覆蓋（原子操作）
        temp_path.replace(path)

    def load(self, task_id: str) -> Optional[dict]:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # JSON 損壞（異常關機導致），嘗試從 .tmp 備份恢復
            tmp_path = path.with_suffix(".tmp")
            if tmp_path.exists():
                try:
                    return json.loads(tmp_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            # 無法恢復，記錄並返回 None
            logging.getLogger(__name__).warning(f"任務檔案損壞：{path}")
            return None

    def delete(self, task_id: str):
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
        # 清除最後任務記錄
        last_path = self._last_task_path()
        if last_path.exists():
            last_id = last_path.read_text(encoding="utf-8").strip()
            if last_id == task_id:
                last_path.unlink(missing_ok=True)

    def list_all(self) -> list[dict]:
        tasks = []
        for p in sorted(self.tasks_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                tasks.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return tasks

    def get_last_task_id(self) -> Optional[str]:
        """讀取上次任務 ID（用於崩潰恢復）"""
        last_path = self._last_task_path()
        if not last_path.exists():
            return None
        task_id = last_path.read_text(encoding="utf-8").strip()
        if task_id and self._task_path(task_id).exists():
            return task_id
        return None

    def update_last_task(self, task_id: str):
        """記錄最後活躍的任務 ID"""
        last_path = self._last_task_path()
        last_path.write_text(task_id, encoding="utf-8")


task_store = TaskStore(settings.tasks_path)


# ─── 輔助函式 ───

def _process_transcription(task: dict, wav_path: Path, audio_filename: str):
    """後台處理轉寫任務"""
    task_id = task["task_id"]

    try:
        # 更新狀態 → processing
        task["status"] = "processing"
        task_store.save(task)

        # 階段 1：音檔切割（如有需要）
        chunks = split_audio(wav_path)
        total_chunks = len(chunks)

        # 階段 2：分段轉寫
        all_segments = []
        time_offset = 0.0
        for i, chunk in enumerate(chunks):
            chunk_path = Path(chunk["path"])
            chunk_result = transcribe_audio(chunk_path)

            # 調整時間戳（考慮切割偏移）
            for seg in chunk_result["segments"]:
                seg["id"] = len(all_segments)
                seg["start"] += chunk["start_sec"]
                seg["end"] += chunk["start_sec"]
                # 初始化附加欄位
                seg["text_written"] = None
                seg["translation_stale"] = False
                seg["speaker"] = ""
                seg["audio_processing"] = {"noise_reduction": False, "volume_boost": False}
                seg["retranscribe_count"] = 0
                all_segments.append(seg)

            # 更新進度（STT 佔 10%-80%）
            progress = 0.1 + 0.7 * ((i + 1) / total_chunks)
            task["progress"] = progress
            task_store.save(task)

        # 檢查是否有語音內容
        if not all_segments or all(not s["text"].strip() for s in all_segments):
            task["status"] = "completed"
            task["progress"] = 1.0
            task["result"] = {
                "language": "yue",
                "language_probability": 1.0,
                "segments": [],
                "speaker_map": {},
                "warning": "未偵測到語音內容",
            }
            task_store.save(task)
            return

        # 階段 3：說話人分離（80%-95%）
        task["progress"] = 0.85
        task_store.save(task)

        diarization_segments = diarize(wav_path)
        all_segments = assign_speakers_to_stt_segments(all_segments, diarization_segments)

        # 合併同一說話人的連續段落
        all_segments = merge_adjacent_same_speaker(all_segments)

        # 建立說話人映射（95%-100%）
        task["progress"] = 0.95
        task_store.save(task)

        speaker_counts = build_speaker_counts(all_segments)
        # 安全排序：避免非標準 speaker_id 導致崩潰
  # 未知格式排在最後
        speaker_map = {
            sid: {"count": count, "name": None}
            for sid, count in sorted(speaker_counts.items(), key=lambda x: _safe_speaker_key(x[0]))
        }

        # 完成
        task["status"] = "completed"
        task["progress"] = 1.0
        task["result"] = {
            "language": "yue",
            "language_probability": 1.0,
            "segments": all_segments,
            "speaker_map": speaker_map,
        }
        task["updated_at"] = datetime.now().isoformat()
        task_store.save(task)

        logger.info(f"任務 {task_id} 轉寫完成：{len(all_segments)} 個段落")

    except Exception as e:
        logger.error(f"任務 {task_id} 處理失敗：{e}")
        task["status"] = "failed"
        task["error"] = str(e)
        task["updated_at"] = datetime.now().isoformat()
        task_store.save(task)


# ─── API 端點 ───

@app.get("/v1/health")
async def health():
    """健康檢查"""
    return {
        "status": "ok",
        "ffmpeg_available": check_ffmpeg(),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/v1/transcribe")
async def transcribe(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    diarization: str = Form("vad"),
    no_stt: str = Form("false"),
):
    """提交任務：可選是否立即開始 STT（no_stt=true 僅載入音檔，留待手動處理）"""
    return await _create_task(background_tasks, audio, diarization, no_stt == "true")


@app.post("/v1/upload")
async def upload_only(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
):
    """僅載入音檔，不自動 STT（用於先切割再批量處理）"""
    return await _create_task(background_tasks, audio, "vad", no_stt=True)


async def _create_task(
    background_tasks: BackgroundTasks,
    audio: UploadFile,
    diarization: str = "vad",
    no_stt: bool = False,
):
    """建立任務的共用邏輯"""
    if not check_ffmpeg():
        raise HTTPException(400, "需要安裝 ffmpeg，請參閱 README")

    task_id = uuid.uuid4().hex[:12]
    upload_dir = settings.tasks_path / f"upload_{task_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(audio.filename or "audio.mp3").suffix.lower()
    original_path = upload_dir / f"original{suffix}"
    with open(original_path, "wb") as f:
        content = await audio.read()
        f.write(content)

    is_valid, error_msg = validate_audio_file(original_path)
    if not is_valid:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(400, error_msg)

    try:
        from pydub import AudioSegment
        audio_seg = AudioSegment.from_file(str(original_path))
        if not check_for_speech(audio_seg):
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise HTTPException(400, "未偵測到語音內容，請確認錄音是否正常")
    except Exception:
        pass

    wav_path = convert_to_wav(original_path, upload_dir)
    duration_sec = get_audio_duration(original_path)

    if no_stt:
        # 僅載入，不 STT：建立一個空的段落（整段音頻）
        segments = [{
            "id": 0,
            "start": 0.0,
            "end": duration_sec,
            "text": "[待 STT]",
            "text_written": None,
            "translation_stale": False,
            "speaker": "",
            "audio_processing": {"noise_reduction": False, "volume_boost": False},
            "retranscribe_count": 0,
            "stt_status": "pending",
        }]
        task = {
            "task_id": task_id,
            "status": "completed",
            "progress": 1.0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "audio_filename": audio.filename or "unknown",
            "audio_duration_sec": duration_sec,
            "diarization_mode": diarization,
            "error": None,
            "result": {
                "language": "yue",
                "language_probability": 1.0,
                "segments": segments,
                "speaker_map": {},
            },
            "_wav_path": str(wav_path),
            "_original_path": str(original_path),
            "_upload_dir": str(upload_dir),
        }
        task_store.save(task)
        task_store.update_last_task(task_id)
        return {"task_id": task_id}
    else:
        # 自動 STT
        task = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0.0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "audio_filename": audio.filename or "unknown",
            "audio_duration_sec": duration_sec,
            "diarization_mode": diarization,
            "error": None,
            "result": None,
            "_wav_path": str(wav_path),
            "_original_path": str(original_path),
            "_upload_dir": str(upload_dir),
        }
        task_store.save(task)
        task_store.update_last_task(task_id)
        background_tasks.add_task(_process_transcription, task, wav_path, audio.filename or "unknown")
        return {"task_id": task_id}


@app.get("/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """查詢任務狀態與結果"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    # 回傳時隱藏內部路徑
    response = {k: v for k, v in task.items() if not k.startswith("_")}
    return response


@app.delete("/v1/tasks/{task_id}")
async def delete_task(task_id: str):
    """刪除任務（含暫存檔案）"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    # 清理暫存目錄
    upload_dir = task.get("_upload_dir")
    if upload_dir and Path(upload_dir).exists():
        shutil.rmtree(upload_dir, ignore_errors=True)

    task_store.delete(task_id)
    return {"ok": True}


@app.get("/v1/last-task")
async def get_last_task():
    """取得上次未完成的任務（用於崩潰恢復）"""
    task_id = task_store.get_last_task_id()
    if not task_id:
        return {"task_id": None}
    task = task_store.load(task_id)
    if task is None:
        return {"task_id": None}
    return {k: v for k, v in task.items() if not k.startswith("_")}


@app.get("/v1/tasks")
async def list_tasks():
    """列出所有任務"""
    tasks = task_store.list_all()
    return [
        {k: v for k, v in t.items() if not k.startswith("_")}
        for t in tasks
    ]


@app.post("/v1/tasks/{task_id}/translate")
async def translate(task_id: str, body: dict):
    """翻譯粵語為書面語"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成，無法翻譯")

    scope = body.get("scope", "all")
    segment_ids = body.get("segment_ids")

    result = translate_segments_builtin(
        task["result"]["segments"],
        scope=scope,
        segment_ids=segment_ids,
    )

    if result["success"]:
        task["result"]["segments"] = result["updated_segments"]
        task["updated_at"] = datetime.now().isoformat()
        task_store.save(task)

    return result


@app.put("/v1/tasks/{task_id}/speakers")
async def update_speakers(task_id: str, body: dict):
    """更新說話人名稱映射"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成")

    speaker_map = task["result"].get("speaker_map", {})

    for speaker_id, name in body.items():
        if speaker_id in speaker_map:
            name = (name or "").strip()
            speaker_map[speaker_id]["name"] = name if name else None

    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)

    return {"speaker_map": speaker_map}


@app.post("/v1/tasks/{task_id}/retranscribe")
async def retranscribe(task_id: str, body: dict):
    """局部重新 STT（可疊加降噪/提音量）"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成")

    segment_ids = body.get("segment_ids", [])
    noise_reduction = body.get("noise_reduction", False)
    volume_boost = body.get("volume_boost", False)

    segments = task["result"]["segments"]
    is_valid, error_msg, selected = validate_segment_selection(segments, segment_ids)
    if not is_valid:
        raise HTTPException(400, error_msg)

    # 獲取原始 WAV
    wav_path = Path(task["_wav_path"])
    if not wav_path.exists():
        raise HTTPException(400, "原始音檔已遺失，無法重新識別")

    # 提取時間段
    start_sec = selected[0]["start"]
    end_sec = selected[-1]["end"]
    audio_seg = extract_segment(wav_path, start_sec, end_sec)

    # 應用音頻處理
    if noise_reduction:
        audio_seg = apply_noise_reduction(audio_seg)
    if volume_boost:
        audio_seg = apply_volume_boost(audio_seg)

    # 暫存處理後的音頻
    processed_path = save_audio_temp(audio_seg)

    try:
        # 重新 STT
        stt_result = transcribe_audio(processed_path)

        # 更新對應段落
        new_segs = stt_result["segments"]
        if not new_segs:
            raise HTTPException(400, "重新識別失敗：未偵測到語音")

        # 分配新文字到原有段落（按比例分攤）
        original_count = len(selected)
        new_count = len(new_segs)

        if new_count == 1:
            # 單一新段落 → 合併到第一個選取段落
            all_text = "".join(sg.get("text", "") for sg in new_segs if sg.get("text"))
            selected[0]["text"] = all_text
            selected[0]["translation_stale"] = True
            selected[0]["audio_processing"] = {"noise_reduction": noise_reduction, "volume_boost": volume_boost}
            selected[0]["retranscribe_count"] = selected[0].get("retranscribe_count", 0) + 1
            # 清除其他選取段落
            for s in selected[1:]:
                s["text"] = ""
                s["translation_stale"] = True
        else:
            # 多段落 → 按時間比例分配
            for nseg in new_segs:
                # 找最接近的原始段落
                nseg_mid = (nseg["start"] + nseg["end"]) / 2
                ratio = nseg_mid / (new_segs[-1]["end"] or 0.001)
                orig_idx = min(int(ratio * original_count), original_count - 1)
                selected[orig_idx]["text"] = nseg["text"]
                selected[orig_idx]["translation_stale"] = True
                selected[orig_idx]["audio_processing"] = {"noise_reduction": noise_reduction, "volume_boost": volume_boost}
                selected[orig_idx]["retranscribe_count"] = selected[orig_idx].get("retranscribe_count", 0) + 1

        # 儲存
        task["updated_at"] = datetime.now().isoformat()
        task_store.save(task)

        return {"success": True, "updated_segment_ids": segment_ids}

    except Exception as e:
        raise HTTPException(500, f"重新識別失敗：{str(e)}")
    finally:
        # 清理暫存檔
        if processed_path.exists():
            try:
                os.unlink(str(processed_path))
            except OSError:
                pass


@app.post("/v1/tasks/{task_id}/export")
async def export(task_id: str, body: dict):
    """匯出結果"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成")

    fmt = body.get("format", "txt")
    written = body.get("language", "yue") == "written"

    segments = task["result"]["segments"]
    # 篩選指定段落
    seg_ids = body.get("segment_ids")
    if seg_ids:
        segments = [s for s in segments if s["id"] in seg_ids]
    speaker_map = task["result"].get("speaker_map", {})
    registry = SpeakerRegistry({sid: info.get("count", 0) for sid, info in speaker_map.items()})
    for sid, info in speaker_map.items():
        if info.get("name"):
            registry.set_name(sid, info["name"])

    export_dir = settings.tasks_path / f"export_{task_id}"
    export_dir.mkdir(parents=True, exist_ok=True)

    audio_filename = task.get("audio_filename", "unknown")

    if fmt == "txt":
        file_ext = ".txt"
        output_path = export_dir / f"{Path(audio_filename).stem}{file_ext}"
        export_txt(segments, output_path, audio_filename, written=written, registry=registry)
    elif fmt == "docx":
        file_ext = ".docx"
        font_name = body.get("font_name", "微軟正黑體")
        font_size = body.get("font_size", 12)
        include_timestamp = body.get("include_timestamp", True)
        include_speaker_color = body.get("include_speaker_color", True)
        output_path = export_dir / f"{Path(audio_filename).stem}{file_ext}"
        export_docx(
            segments, output_path, audio_filename,
            written=written, registry=registry,
            font_name=font_name, font_size=font_size,
            include_timestamp=include_timestamp,
            include_speaker_color=include_speaker_color,
        )
    elif fmt == "srt":
        output_path = export_dir / f"{Path(audio_filename).stem}.srt"
        export_srt(segments, output_path, audio_filename, written=written, registry=registry)
    else:
        raise HTTPException(400, f"不支援的格式：{fmt}")

    return FileResponse(
        str(output_path),
        media_type="application/octet-stream",
        filename=output_path.name,
    )


@app.post("/v1/tasks/{task_id}/report")
async def report(task_id: str, body: dict):
    """生成 AI 會議報告"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成")

    written = body.get("language", "yue") == "written"
    provider = body.get("provider")
    model = body.get("model")
    api_base = body.get("api_base")
    api_key = body.get("api_key")
    report_lang = body.get("report_language")

    segments = task["result"]["segments"]
    # 先應用說話人名稱
    speaker_map = task["result"].get("speaker_map", {})
    registry = SpeakerRegistry({sid: info.get("count", 0) for sid, info in speaker_map.items()})
    for sid, info in speaker_map.items():
        if info.get("name"):
            registry.set_name(sid, info["name"])

    if registry.speakers:
        segments = apply_speaker_names(segments, registry)

    result = generate_report(
        segments,
        written=written,
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        report_lang=report_lang,
    )

    return result


# ─── 音檔播放 ───

@app.get("/v1/tasks/{task_id}/audio")
async def get_audio(task_id: str):
    """提供原始音檔供前端播放（優先回傳原始格式，其次 WAV）"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    # 優先回傳原始音檔（瀏覽器支援格式較多）
    original_path = task.get("_original_path")
    if original_path and Path(original_path).exists():
        # 偵測 MIME 類型
        suffix = Path(original_path).suffix.lower()
        mime_map = {
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac",
        }
        return FileResponse(original_path, media_type=mime_map.get(suffix, "audio/mpeg"))

    # Fallback: WAV
    wav_path = task.get("_wav_path")
    if wav_path and Path(wav_path).exists():
        return FileResponse(wav_path, media_type="audio/wav")

    raise HTTPException(404, "音檔不可用")


# ─── 波形 API ───

@app.get("/v1/tasks/{task_id}/waveform")
async def get_waveform(task_id: str, peaks: int = 2000):
    """回傳波形峰值陣列（用於前端 Canvas 繪製）"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    wav_path = task.get("_wav_path")
    if not wav_path or not Path(wav_path).exists():
        raise HTTPException(400, "音檔不可用")

    from app.audio_processor import compute_waveform_peaks
    return {"peaks": compute_waveform_peaks(Path(wav_path), num_peaks=peaks)}


# ─── 切割 API ───

@app.post("/v1/tasks/{task_id}/split")
async def split_task(task_id: str, body: dict):
    """按切割點將音檔切為多段，追加到現有 segments"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(400, "任務尚未完成，無法切割")

    cut_points = body.get("cut_points", [])
    ranges = body.get("ranges")

    if ranges:
        # Convert ranges to cut_points equivalent
        points = []
        for r in ranges:
            points.append(r["start"])
            points.append(r["end"])
        cut_points = sorted(set(points))

    if not cut_points or len(cut_points) < 1:
        raise HTTPException(400, "至少需要一個切割點或時間段")

    cut_points = sorted(set(cut_points))
    if cut_points[0] <= 0 or cut_points[-1] >= task["audio_duration_sec"]:
        raise HTTPException(400, "切割點必須在音檔範圍內（不含 0 和終點）")

    wav_path = Path(task["_wav_path"])
    if not wav_path.exists():
        raise HTTPException(400, "原始音檔已遺失")

    from app.audio_processor import extract_segment, save_audio_temp

    segment_dir = Path(task["_upload_dir"]) / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    existing_segments = task["result"].get("segments", [])
    max_id = max((s["id"] for s in existing_segments), default=-1)
    cut_set = sorted(set(cut_points))

    new_segments = []
    for seg in existing_segments:
        # 找出落在這個段落內的切割點
        inner = [p for p in cut_set if seg["start"] < p < seg["end"]]
        if not inner:
            # 無關段落，保留原樣
            new_segments.append(seg)
            continue

        # 有切割點，細分這個段落
        boundaries = [seg["start"]] + inner + [seg["end"]]
        for i in range(len(boundaries) - 1):
            st, et = boundaries[i], boundaries[i + 1]
            seg_audio = extract_segment(wav_path, st, et)
            sp = save_audio_temp(seg_audio)
            import shutil
            dest = segment_dir / f"cut_{st:.3f}_{et:.3f}.wav"
            shutil.move(str(sp), str(dest))
            max_id += 1
            new_segments.append({
                "id": max_id,
                "start": st,
                "end": et,
                "text": "[待 STT]",
                "text_written": None,
                "translation_stale": False,
                "speaker": seg.get("speaker", ""),
                "audio_processing": {"noise_reduction": False, "volume_boost": False},
                "retranscribe_count": 0,
                "stt_status": "pending",
                "segment_path": str(dest),
            })

    task["result"]["segments"] = new_segments
    task["result"]["speaker_map"] = {}
    task["_cut_points"] = cut_points
    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)
    task_store.update_last_task(task_id)

    return {
        "success": True,
        "segments": new_segments,
        "segment_count": len(new_segments),
    }


@app.post("/v1/tasks/{task_id}/export-audio")
async def export_task_audio(task_id: str, body: dict, background_tasks: BackgroundTasks):
    """匯出指定段落的音頻為高品質 WAV"""
    from fastapi.responses import FileResponse
    from app.audio_processor import extract_segment
    from pydub import AudioSegment
    import tempfile, os

    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    seg_ids = body.get("segment_ids", [])
    if not seg_ids:
        raise HTTPException(400, "請指定至少一個段落 ID")

    wav_path = Path(task["_wav_path"])
    if not wav_path.exists():
        raise HTTPException(400, "原始音檔已遺失")

    segments = task["result"].get("segments", [])
    combined = AudioSegment.empty()
    for sid in seg_ids:
        seg = next((s for s in segments if s["id"] == sid), None)
        if seg is None:
            continue
        sp = seg.get("segment_path")
        if sp and Path(sp).exists():
            chunk = AudioSegment.from_file(str(sp))
        else:
            chunk = extract_segment(wav_path, seg["start"], seg["end"])
        combined += chunk

    if len(combined) == 0:
        raise HTTPException(400, "無法讀取所選段落的音頻")

    # 匯出為高品質 WAV
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="ct_export_")
    combined.export(tmp.name, format="wav", parameters=["-ar", "44100", "-ac", "2", "-sample_fmt", "s16"])

    def cleanup():
        try: os.unlink(tmp.name)
        except: pass
    background_tasks.add_task(cleanup)

    return FileResponse(
        tmp.name,
        media_type="audio/wav",
        filename=f"export_{task_id}_{len(seg_ids)}seg.wav",
        headers={"Content-Disposition": f'attachment; filename="export_{task_id}_{len(seg_ids)}seg.wav"'},
    )


# ─── 逐段 STT API ───

@app.post("/v1/tasks/{task_id}/stt-segment")
async def stt_segment(task_id: str, body: dict):
    """對任務中指定 segment 執行 STT（用於批量逐段處理）"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if not task.get("result") or not task["result"].get("segments"):
        raise HTTPException(400, "任務無段落資料")

    segment_id = body.get("segment_id")
    if segment_id is None:
        raise HTTPException(400, "需提供 segment_id")
    noise_reduction = body.get("noise_reduction", False)
    volume_boost = body.get("volume_boost", False)

    segments = task["result"]["segments"]
    target = next((s for s in segments if s["id"] == segment_id), None)
    if target is None:
        raise HTTPException(404, f"段落 #{segment_id} 不存在")

    from pydub import AudioSegment as PydubSegment

    wav_path = Path(task["_wav_path"])
    seg_path = target.get("segment_path")

    # 取得音頻片段
    if seg_path and Path(seg_path).exists():
        audio_seg = PydubSegment.from_file(str(Path(seg_path)))
    elif wav_path.exists():
        audio_seg = extract_segment(wav_path, target["start"], target["end"])
    else:
        raise HTTPException(400, "音檔不可用")

    # 可選音頻處理
    if noise_reduction:
        audio_seg = apply_noise_reduction(audio_seg)
    if volume_boost:
        audio_seg = apply_volume_boost(audio_seg)

    # 暫存並轉寫
    tmp_path = save_audio_temp(audio_seg)
    try:
        stt_result = transcribe_audio(tmp_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # 更新段落
    new_segs = stt_result.get("segments", [])
    if new_segs:
        # 合併所有 STT 子段落的文字，排除低信心段落
        texts = []
        low_conf = []
        for sg in new_segs:
            txt = sg.get("text", "").strip()
            if not txt:
                continue
            logprob = sg.get("avg_logprob", 0)
            # avg_logprob 是負值，-1.0 以上算合理，-2.0 以下很低
            if logprob < -2.0:
                low_conf.append(txt)
                continue
            texts.append(txt)

        full_text = "".join(texts) if texts else ("".join(low_conf) if low_conf else "")
        target["text"] = full_text if full_text else "[未偵測到語音]"

        # 記錄信心數據
        if new_segs:
            avg_logprob = sum(sg.get("avg_logprob", 0) for sg in new_segs if sg.get("avg_logprob") is not None) / max(len([s for s in new_segs if s.get("avg_logprob") is not None]), 1)
            target["stt_confidence"] = max(0, 1.0 + avg_logprob)  # 0~1 範圍
    else:
        target["text"] = "[未偵測到語音]"
        target["stt_confidence"] = 0.0
    else:
        target["text"] = "[未偵測到語音]"
    target["speaker"] = target.get("speaker", "") or f"人物 #{segment_id}"
    target["stt_status"] = "completed"
    target["retranscribe_count"] = target.get("retranscribe_count", 0) + 1

    # 更新 speaker_map
    speaker_map = task["result"].get("speaker_map", {})
    spk_id = target["speaker"]
    if spk_id not in speaker_map:
        speaker_map[spk_id] = {"count": 0, "name": None}
    speaker_map[spk_id]["count"] = speaker_map[spk_id].get("count", 0) + 1
    task["result"]["speaker_map"] = speaker_map

    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)
    task_store.update_last_task(task_id)

    return {
        "success": True,
        "segment_id": segment_id,
        "text": target["text"],
        "speaker": target["speaker"],
    }


# ─── 段落批量 STT 狀態查詢 ───

@app.get("/v1/tasks/{task_id}/stt-status")
async def get_stt_status(task_id: str):
    """取得逐段 STT 的整體進度"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")

    segments = (task.get("result") or {}).get("segments", [])
    total = len(segments)
    completed = sum(1 for s in segments if s.get("stt_status") == "completed")
    failed = sum(1 for s in segments if s.get("stt_status") == "failed")
    pending = total - completed - failed

    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "progress": (completed + failed) / total if total > 0 else 0,
        "segments": [
            {"id": s["id"], "start": s["start"], "end": s["end"],
             "text": s.get("text") if s.get("stt_status") != "pending" else None,
             "stt_status": s.get("stt_status", "pending")}
            for s in segments
        ],
    }


# ─── 手動添加段落 API ───

@app.post("/v1/tasks/{task_id}/diarize")
async def diarize_task(task_id: str):
    """對已完成 STT 的任務執行說話人分離"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if not task.get("result") or not task["result"].get("segments"):
        raise HTTPException(400, "任務無段落資料")

    wav_path = Path(task["_wav_path"])
    if not wav_path.exists():
        raise HTTPException(400, "原始音檔已遺失")

    segments = task["result"]["segments"]

    # 執行說話人分離
    diarization_segments = diarize(wav_path)
    segments = assign_speakers_to_stt_segments(segments, diarization_segments)
    segments = merge_adjacent_same_speaker(segments)

    # 重建 speaker_map
    speaker_counts = build_speaker_counts(segments)

    speaker_map = {
        sid: {"count": count, "name": None}
        for sid, count in sorted(speaker_counts.items(), key=lambda x: _safe_key(x[0]))
    }

    task["result"]["segments"] = segments
    task["result"]["speaker_map"] = speaker_map
    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)
    task_store.update_last_task(task_id)

    return {
        "success": True,
        "speaker_map": speaker_map,
        "segment_count": len(segments),
    }


@app.post("/v1/tasks/{task_id}/segments")
async def add_segment(task_id: str, body: dict):
    """手動添加時間段到任務"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if not task.get("result") or not task["result"].get("segments"):
        segments = []
    else:
        segments = task["result"]["segments"]

    start = body.get("start")
    end = body.get("end")

    if start is None or end is None:
        raise HTTPException(400, "需提供 start 和 end 時間")
    if end - start < 0.5:
        raise HTTPException(400, "時間段過短（最少 0.5 秒）")
    if start < 0 or end > task["audio_duration_sec"]:
        raise HTTPException(400, "時間超出音檔範圍")

    # 檢查與現有段落重疊
    for seg in segments:
        if not (end <= seg["start"] or start >= seg["end"]):
            raise HTTPException(400,
                f"與段落 #{seg['id']} ({seg['start']:.1f}s ~ {seg['end']:.1f}s) 重疊")

    new_id = max((s["id"] for s in segments), default=-1) + 1
    new_seg = {
        "id": new_id,
        "start": start,
        "end": end,
        "text": "[待 STT]",
        "text_written": None,
        "translation_stale": False,
        "speaker": "",
        "audio_processing": {"noise_reduction": False, "volume_boost": False},
        "retranscribe_count": 0,
        "stt_status": "pending",
    }

    segments.append(new_seg)
    segments.sort(key=lambda s: s["start"])
    # 重新分配 ID
    for i, s in enumerate(segments):
        s["id"] = i

    if not task.get("result"):
        task["result"] = {}
    task["result"]["segments"] = segments
    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)
    task_store.update_last_task(task_id)

    return {"success": True, "segment": new_seg}


@app.put("/v1/tasks/{task_id}/segments/{segment_id}")
async def update_segment(task_id: str, segment_id: int, body: dict):
    """更新單一段落的文字內容"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if not task.get("result") or not task["result"].get("segments"):
        raise HTTPException(400, "任務尚無段落")

    segments = task["result"]["segments"]
    for seg in segments:
        if seg["id"] == segment_id:
            if "text" in body:
                seg["text"] = body["text"]
            if "text_written" in body:
                seg["text_written"] = body["text_written"]
            task["updated_at"] = datetime.now().isoformat()
            task_store.save(task)
            return {"success": True, "segment": seg}

    raise HTTPException(404, f"段落 #{segment_id} 不存在")


@app.delete("/v1/tasks/{task_id}/segments")
async def delete_segments(task_id: str, ids: str = Query("")):
    """刪除指定 ID 的段落"""
    task = task_store.load(task_id)
    if task is None:
        raise HTTPException(404, "任務不存在")
    if not task.get("result") or not task["result"].get("segments"):
        return {"success": True, "deleted_count": 0}

    parsed_ids = []
    for part in ids.split(","):
        part = part.strip()
        if part:
            try: parsed_ids.append(int(part))
            except: pass

    if not parsed_ids:
        raise HTTPException(400, "需提供 ids 參數，例如 ?ids=1,2,3")

    segments = task["result"]["segments"]
    before = len(segments)
    task["result"]["segments"] = [s for s in segments if s["id"] not in parsed_ids]
    deleted_count = before - len(task["result"]["segments"])
    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)

    return {"success": True, "deleted_count": deleted_count}


# ─── 靜態檔案與前端 ───

frontend_dir = Path(__file__).parent.parent / "frontend"


@app.get("/v1/settings")
async def get_settings():
    """取得目前 AI 設定（API Key 模糊化）"""
    from app.settings_manager import UI_SETTINGS_KEYS, mask_api_key
    result = {}
    for key in UI_SETTINGS_KEYS:
        val = getattr(settings, key, "")
        if key == "llm_api_key":
            val = mask_api_key(val)
        result[key] = val
    return result


@app.put("/v1/settings")
async def update_settings(body: dict):
    """更新 UI 設定並持久化"""
    from app.settings_manager import save_ui_settings, UI_SETTINGS_KEYS, mask_api_key
    saved = save_ui_settings(settings.tasks_path, body)
    # 更新當前 settings 物件（熱載入，不重啟）
    for key in UI_SETTINGS_KEYS:
        if key in saved:
            setattr(settings, key, saved[key])
    result = {}
    for key in UI_SETTINGS_KEYS:
        val = getattr(settings, key, "")
        if key == "llm_api_key":
            val = mask_api_key(val)
        result[key] = val
    return {"success": True, "settings": result}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Web UI 入口"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Canto Transcriber</h1><p>Web UI coming soon</p>")


# ─── 啟動 ───

def start_server(host: str = None, port: int = None):
    """以程式方式啟動伺服器"""
    import uvicorn
    host = host or settings.api_host
    port = port or settings.api_port
    logger.info(f"啟動 API 伺服器：http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
