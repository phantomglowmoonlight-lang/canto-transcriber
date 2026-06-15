"""
音頻處理：格式轉換、切割、降噪、提音量
"""
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings

# ─── 確保 ffmpeg/ffprobe 在 PATH 中 ───
_ffmpeg_dir = None
# 1. 檢查內置的 bin 目錄
_bundled_bin = Path(__file__).parent.parent / "bin"
if (_bundled_bin / "ffmpeg.exe").exists():
    _ffmpeg_dir = str(_bundled_bin)
# 2. 檢查 .env 設定
elif settings.ffmpeg_path.strip():
    _p = Path(settings.ffmpeg_path.strip())
    if _p.exists():
        _ffmpeg_dir = str(_p.parent)

if _ffmpeg_dir and _ffmpeg_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize

# 支援格式白名單
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def _ffmpeg_cmd() -> str:
    """取得 ffmpeg 命令（PATH 已在模組載入時設定）"""
    return "ffmpeg"


def check_ffmpeg() -> bool:
    """檢查 ffmpeg 是否可用"""
    try:
        subprocess.run([_ffmpeg_cmd(), "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def validate_audio_file(path: Path) -> Tuple[bool, str]:
    """
    驗證音檔：格式、可讀性、長度

    回傳 (is_valid, error_message)
    """
    if not path.exists():
        return False, "檔案不存在"

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        return False, f"不支援的格式：{suffix}。支援格式：{', '.join(sorted(SUPPORTED_FORMATS))}"

    # 檢查是否可讀
    try:
        audio = AudioSegment.from_file(str(path))
    except Exception:
        return False, "無法讀取音檔，檔案可能已損壞"

    duration_sec = len(audio) / 1000.0
    if duration_sec < 1.0:
        return False, "音檔過短（< 1 秒），請確認上傳正確的錄音"

    if duration_sec > 36000:  # > 10 小時
        return False, "音檔過長（> 10 小時），請先分割後再上傳"

    return True, ""


def get_audio_duration(path: Path) -> float:
    """取得音檔長度（秒）"""
    audio = AudioSegment.from_file(str(path))
    return len(audio) / 1000.0


def convert_to_wav(input_path: Path, output_dir: Optional[Path] = None) -> Path:
    """
    將任意支援格式轉為 16kHz mono WAV（faster-whisper 輸入格式）

    回傳 WAV 檔案路徑
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="ct_audio_"))

    output_path = output_dir / f"{input_path.stem}_16k.wav"

    audio = AudioSegment.from_file(str(input_path))
    audio = audio.set_frame_rate(settings.sample_rate)
    audio = audio.set_channels(1)
    audio.export(str(output_path), format="wav")

    return output_path


def check_for_speech(audio: AudioSegment, threshold_db: float = -60) -> bool:
    """檢查音頻是否包含語音（非純靜音）"""
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    if len(samples) == 0:
        return False

    # 計算 RMS 能量
    rms = np.sqrt(np.mean(samples ** 2))
    if rms == 0:
        return False

    rms_db = 20 * np.log10(rms / 32768.0)  # 假設 16-bit 音頻
    return rms_db > threshold_db


def split_audio(wav_path: Path, output_dir: Optional[Path] = None) -> list[dict]:
    """
    將長音檔按時間切割（超過 chunk_max_minutes 時啟用）

    回傳切割段落列表，每個元素為 {index, start_sec, end_sec, path}
    段落間保留重疊（chunk_overlap_seconds）
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="ct_chunks_"))

    audio = AudioSegment.from_file(str(wav_path))
    total_ms = len(audio)
    chunk_ms = settings.chunk_max_minutes * 60 * 1000
    overlap_ms = settings.chunk_overlap_seconds * 1000

    if total_ms <= chunk_ms:
        # 不需切割
        return [{"index": 0, "start_sec": 0.0, "end_sec": total_ms / 1000.0, "path": wav_path}]

    chunks = []
    start_ms = 0
    idx = 0
    while start_ms < total_ms:
        end_ms = min(start_ms + chunk_ms, total_ms)
        chunk = audio[start_ms:end_ms]
        chunk_path = output_dir / f"chunk_{idx:04d}.wav"
        chunk.export(str(chunk_path), format="wav")
        chunks.append({
            "index": idx,
            "start_sec": start_ms / 1000.0,
            "end_sec": end_ms / 1000.0,
            "path": str(chunk_path),
        })
        # 下一段起點保留重疊
        start_ms += chunk_ms - overlap_ms
        idx += 1

    return chunks


def extract_segment(wav_path: Path, start_sec: float, end_sec: float) -> AudioSegment:
    """從原始 WAV 提取指定時間段"""
    audio = AudioSegment.from_file(str(wav_path))
    start_ms = int(start_sec * 1000)
    end_ms = int(end_sec * 1000)
    end_ms = min(end_ms, len(audio))
    start_ms = max(0, start_ms)
    return audio[start_ms:end_ms]


def apply_noise_reduction(audio: AudioSegment) -> AudioSegment:
    """
    對音頻片段應用降噪處理（基於 noisereduce 與 pydub）

    使用頻譜閘值降噪，保留語音頻段
    """
    try:
        import noisereduce as nr

        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        sample_rate = audio.frame_rate

        # noisereduce 需要 float 輸入
        reduced = nr.reduce_noise(y=samples, sr=sample_rate, prop_decrease=0.8)

        # 轉回 int16
        reduced = np.clip(reduced, -32768, 32767).astype(np.int16)

        return AudioSegment(
            reduced.tobytes(),
            frame_width=audio.sample_width,
            frame_rate=audio.frame_rate,
            channels=audio.channels,
        )
    except ImportError:
        # noisereduce 未安裝時使用 ffmpeg 內建 anlmdn 濾波器作為 fallback
        return _apply_ffmpeg_noise_reduction(audio)


def _apply_ffmpeg_noise_reduction(audio: AudioSegment) -> AudioSegment:
    """使用 ffmpeg anlmdn 濾波器降噪（fallback）"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
        audio.export(tmp_in.name, format="wav")
        try:
            subprocess.run([
                _ffmpeg_cmd(), "-y", "-i", tmp_in.name,
                "-af", "anlmdn=s=0.0001",
                "-ar", str(audio.frame_rate),
                "-ac", str(audio.channels),
                tmp_out.name,
            ], capture_output=True, timeout=30)
            result = AudioSegment.from_file(tmp_out.name)
            return result
        finally:
            os.unlink(tmp_in.name)
            os.unlink(tmp_out.name)


def apply_volume_boost(audio: AudioSegment, gain_db: float = 6.0) -> AudioSegment:
    """
    提高音量（增益控制）

    gain_db: 增益分貝數，預設 +6dB，最大 +12dB
    """
    gain_db = min(gain_db, 12.0)  # 限制最大增益防止 clipping
    return audio + gain_db


def save_audio_temp(audio: AudioSegment) -> Path:
    """將 AudioSegment 儲存為暫存 WAV"""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="ct_seg_")
    audio.export(tmp.name, format="wav")
    return Path(tmp.name)


def compute_waveform_peaks(wav_path: Path, num_peaks: int = 20000) -> list[float]:
    """
    計算波形峰值陣列（用於前端 Canvas 繪製）

    num_peaks: 回傳的峰值數量，預設 20000（每條 bar ~0.17 秒）
    回傳值為 0~1 之間的 float 陣列

    會將結果快取在 wav_path 同目錄的 .peaks 檔案中，
    避免每次請求都重新讀取整個音檔。
    """
    cache_path = wav_path.with_suffix(wav_path.suffix + ".peaks.npy")

    # 檢查快取是否匹配請求的峰值數量
    if cache_path.exists():
        try:
            cached = np.load(cache_path)
            if len(cached) == num_peaks:
                return cached.tolist()
        except Exception:
            pass

    audio = AudioSegment.from_file(str(wav_path))
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

    if len(samples) == 0:
        return [0.0] * num_peaks

    # 轉為單聲道（取左右平均）
    if audio.channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)

    # 取絕對值
    abs_samples = np.abs(samples)

    # 分組計算每組最大值
    group_size = max(1, len(abs_samples) // num_peaks)
    peaks = []
    for i in range(0, len(abs_samples), group_size):
        chunk = abs_samples[i:i + group_size]
        if len(chunk) > 0:
            peaks.append(float(np.max(chunk)))

    # 正規化到 0~1
    if peaks:
        max_val = max(peaks)
        if max_val > 0:
            peaks = [p / max_val for p in peaks]

    # 補齊或截斷到 num_peaks
    if len(peaks) > num_peaks:
        peaks = peaks[:num_peaks]
    elif len(peaks) < num_peaks:
        peaks.extend([0.0] * (num_peaks - len(peaks)))

    # 寫入快取
    try:
        np.save(cache_path, np.array(peaks, dtype=np.float32))
    except Exception:
        pass

    return peaks


def split_audio_by_points(
    wav_path: Path,
    cut_points: list[float],
    output_dir: Path,
) -> list[dict]:
    """
    按切割點將音檔切為多段

    cut_points: 切割時間點列表（秒），不含 0 和終點
    output_dir: 切割後音檔的輸出目錄

    回傳切割段落列表，每個元素為 {index, start_sec, end_sec, path}
    """
    audio = AudioSegment.from_file(str(wav_path))
    total_sec = len(audio) / 1000.0

    # 建立完整邊界（起點 → 切割點 → 終點）
    boundaries = [0.0] + sorted(cut_points) + [total_sec]

    cuts = []
    for i in range(len(boundaries) - 1):
        start_sec = boundaries[i]
        end_sec = boundaries[i + 1]
        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)
        chunk = audio[start_ms:end_ms]
        chunk_path = output_dir / f"seg_{i:04d}.wav"
        chunk.export(str(chunk_path), format="wav")
        cuts.append({
            "index": i,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "path": str(chunk_path),
        })

    return cuts

