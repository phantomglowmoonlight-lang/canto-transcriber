"""
文本後處理：合併分段、人名替換、格式整理
"""
import copy
import logging
from typing import Optional
from app.speaker_registry import SpeakerRegistry

logger = logging.getLogger(__name__)


def apply_speaker_names(segments: list[dict], registry: SpeakerRegistry) -> list[dict]:
    """
    將說話人代號替換為真實姓名（深拷貝，不修改原始資料）

    回傳新的 segments 列表，其中 speaker 欄位已更新
    """
    result = copy.deepcopy(segments)
    for seg in result:
        original = seg.get("speaker", "人物 #1")
        seg["speaker"] = registry.get_name(original)
    return result


def merge_adjacent_same_speaker(segments: list[dict], max_gap_sec: float = 2.0) -> list[dict]:
    """
    合併相鄰同一說話人的段落（間距小於 max_gap_sec）

    回傳合併後的列表
    """
    if not segments:
        return segments

    merged = []
    current = dict(segments[0])
    current_texts = [current["text"]]

    for seg in segments[1:]:
        same_speaker = seg.get("speaker") == current.get("speaker")
        close_enough = (seg["start"] - current["end"]) < max_gap_sec

        if same_speaker and close_enough:
            current["end"] = seg["end"]
            current_texts.append(seg["text"])
        else:
            current["text"] = " ".join(current_texts)
            merged.append(current)
            current = dict(seg)
            current_texts = [current["text"]]

    current["text"] = " ".join(current_texts)
    merged.append(current)

    return merged


def build_speaker_counts(segments: list[dict]) -> dict[str, int]:
    """統計每位說話人的發言次數"""
    counts: dict[str, int] = {}
    for seg in segments:
        speaker = seg.get("speaker", "人物 #1")
        counts[speaker] = counts.get(speaker, 0) + 1
    return counts


def segments_to_text(segments: list[dict], use_written: bool = False) -> str:
    """
    將 segments 轉為純文字

    use_written: True 時使用 text_written 欄位（書面語）
    """
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "人物 #1")
        text = seg.get("text_written" if use_written else "text", "")
        timestamp = f"[{_format_timestamp(seg['start'])}]"
        lines.append(f"{timestamp} {speaker}：\n{text}\n")
    return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    """將秒數格式化為 HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def validate_segment_selection(
    segments: list[dict],
    segment_ids: list[int],
) -> tuple[bool, str, Optional[list[dict]]]:
    """
    驗證用戶選取的段落是否有效

    回傳 (is_valid, error, selected_segments)
    """
    if not segment_ids:
        return False, "未選取任何段落", None

    selected = []
    for sid in segment_ids:
        found = None
        for seg in segments:
            if seg.get("id") == sid or (isinstance(sid, int) and seg.get("id") == sid):
                found = seg
                break
        if found is None:
            return False, f"段落 ID {sid} 不存在", None
        selected.append(found)

    # 檢查段落是否過短
    total_duration = selected[-1]["end"] - selected[0]["start"]
    if total_duration < 0.5:
        return False, "選取段落太短（< 0.5 秒），可能無法有效識別", None

    return True, "", selected
