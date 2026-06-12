"""
說話人分離模組：支援 VAD 輕量模式（預設）與 pyannote 精準模式
"""
import logging
from pathlib import Path
from typing import Optional
import numpy as np
import webrtcvad
from pydub import AudioSegment
from app.config import settings

logger = logging.getLogger(__name__)

# webrtcvad 支援的採樣率
VAD_SAMPLE_RATES = {8000, 16000, 32000, 48000}
# 預設 VAD 積極度（0-3，越高越嚴格）
VAD_AGGRESSIVENESS = 2
# 語音幀長度（ms），webrtcvad 只支援 10/20/30ms
FRAME_DURATION_MS = 30


def _vad_to_speech_segments(
    audio: AudioSegment,
    frame_duration_ms: int = FRAME_DURATION_MS,
    aggressiveness: int = VAD_AGGRESSIVENESS,
) -> list[dict]:
    """
    使用 webrtcvad 偵測語音段落

    回傳：
    [
        {"start": 0.0, "end": 2.5, "has_speech": true},
        ...
    ]
    """
    # 確保採樣率在 VAD 支援範圍內
    sr = audio.frame_rate
    if sr not in VAD_SAMPLE_RATES:
        # 重新採樣到 16kHz
        audio = audio.set_frame_rate(16000)
        sr = 16000

    vad = webrtcvad.Vad(aggressiveness)
    samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
    samples_bytes = samples.tobytes()

    frame_len_samples = int(sr * frame_duration_ms / 1000)
    total_frames = len(samples_bytes) // (frame_len_samples * 2)  # 16-bit = 2 bytes

    speech_flags = []
    for i in range(total_frames):
        start_byte = i * frame_len_samples * 2
        frame = samples_bytes[start_byte:start_byte + frame_len_samples * 2]
        if len(frame) < frame_len_samples * 2:
            break
        is_speech = vad.is_speech(frame, sr)
        speech_flags.append(is_speech)

    # 合併連續語音幀為段落
    segments = []
    if not speech_flags:
        return segments

    in_speech = speech_flags[0]
    seg_start = 0
    for i in range(1, len(speech_flags)):
        if speech_flags[i] != in_speech:
            seg_end = i
            start_sec = seg_start * frame_duration_ms / 1000.0
            end_sec = seg_end * frame_duration_ms / 1000.0
            segments.append({"start": round(start_sec, 2), "end": round(end_sec, 2), "has_speech": in_speech})
            seg_start = i
            in_speech = speech_flags[i]

    # 最後一段
    seg_end = len(speech_flags)
    start_sec = seg_start * frame_duration_ms / 1000.0
    end_sec = seg_end * frame_duration_ms / 1000.0
    segments.append({"start": round(start_sec, 2), "end": round(end_sec, 2), "has_speech": in_speech})

    return segments


def _cluster_speakers_by_time(segments: list[dict]) -> list[dict]:
    """
    基於時間聚類的簡易說話人分離

    策略：以 VAD 語音段落的時間間距來推測不同說話人。
    短間距（< 0.8 秒）視為同一人連續發言，長間距視為不同人交替。
    """
    if not segments:
        return segments

    SPEAKER_CHANGE_THRESHOLD_SEC = 0.8
    current_speaker = 0
    last_end = 0.0

    for seg in segments:
        gap = seg["start"] - last_end if last_end > 0 else SPEAKER_CHANGE_THRESHOLD_SEC
        if gap > SPEAKER_CHANGE_THRESHOLD_SEC:
            current_speaker += 1
        seg["speaker"] = f"人物 #{current_speaker}"
        last_end = seg["end"]

    return segments


def diarize(
    wav_path: Path,
    mode: Optional[str] = None,
) -> list[dict]:
    """
    說話人分離主入口

    mode: "vad" | "pyannote" | "auto"
    回傳帶 speaker 欄位的 segments 列表
    """
    mode = mode or settings.diarization_mode

    if mode == "pyannote" and settings.hf_token:
        return _diarize_pyannote(wav_path)
    else:
        return _diarize_vad(wav_path)


def _diarize_vad(wav_path: Path) -> list[dict]:
    """
    VAD 輕量模式：webrtcvad 語音偵測 + 時間聚類
    """
    audio = AudioSegment.from_file(str(wav_path))
    vad_segments = _vad_to_speech_segments(audio)

    # 只保留語音段落
    speech_only = [s for s in vad_segments if s["has_speech"]]
    if not speech_only:
        return []

    # 時間聚類分說話人
    speaker_segments = _cluster_speakers_by_time(speech_only)

    # 合併短間距的同一說話人段落
    merged = _merge_same_speaker_segments(speaker_segments)
    return merged


def _merge_same_speaker_segments(segments: list[dict]) -> list[dict]:
    """合併同一說話人的連續段落"""
    if not segments:
        return segments

    merged = []
    current = dict(segments[0])

    for seg in segments[1:]:
        if seg["speaker"] == current["speaker"] and (seg["start"] - current["end"]) < 2.0:
            current["end"] = seg["end"]
        else:
            merged.append(current)
            current = dict(seg)
    merged.append(current)

    return merged


def _diarize_pyannote(wav_path: Path) -> list[dict]:
    """
    pyannote 精準模式：需要 HF token 與 pyannote.audio 安裝
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        logger.warning("pyannote.audio 未安裝，回退到 VAD 模式")
        return _diarize_vad(wav_path)

    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.hf_token,
        )
        diarization = pipeline(str(wav_path))

        speaker_map = {}
        speaker_idx = 0
        segments = []

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_map:
                speaker_idx += 1
                speaker_map[speaker] = f"人物 #{speaker_idx}"
            segments.append({
                "start": round(turn.start, 2),
                "end": round(turn.end, 2),
                "has_speech": True,
                "speaker": speaker_map[speaker],
            })

        return segments
    except Exception as e:
        logger.error(f"pyannote 分離失敗：{e}，回退到 VAD 模式")
        return _diarize_vad(wav_path)


def assign_speakers_to_stt_segments(
    stt_segments: list[dict],
    diarization_segments: list[dict],
) -> list[dict]:
    """
    將說話人分離結果映射到 STT 段落

    規則：以 STT 段落的時間中點為準，查找最接近的說話人段落
    """
    if not diarization_segments:
        # 無分離結果時，全部標為同一說話人
        for seg in stt_segments:
            seg["speaker"] = "人物 #1"
        return stt_segments

    for seg in stt_segments:
        mid = (seg["start"] + seg["end"]) / 2
        best_speaker = "人物 #1"
        best_overlap = 0

        for ds in diarization_segments:
            # 計算重量疊
            overlap_start = max(seg["start"], ds["start"])
            overlap_end = min(seg["end"], ds["end"])
            overlap = overlap_end - overlap_start
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = ds.get("speaker", "人物 #1")

        seg["speaker"] = best_speaker

    return stt_segments
