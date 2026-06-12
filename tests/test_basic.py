"""
基本功能測試
"""
import json
import tempfile
import unittest
from pathlib import Path
from app.audio_processor import (
    check_ffmpeg,
    validate_audio_file,
    SUPPORTED_FORMATS,
)
from app.speaker_registry import SpeakerRegistry
from app.text_processor import (
    build_speaker_counts,
    segments_to_text,
    validate_segment_selection,
    merge_adjacent_same_speaker,
    _format_timestamp,
)


class TestAudioProcessor(unittest.TestCase):
    """音頻處理模組測試"""

    def test_ffmpeg_check(self):
        """確認 ffmpeg 檢查可執行（不要求必定存在）"""
        result = check_ffmpeg()
        self.assertIsInstance(result, bool)

    def test_supported_formats(self):
        """確認支援格式白名單包含必要格式"""
        required = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
        self.assertTrue(required.issubset(SUPPORTED_FORMATS))

    def test_validate_nonexistent_file(self):
        """不存在的檔案應回傳錯誤"""
        is_valid, msg = validate_audio_file(Path("/nonexistent/file.mp3"))
        self.assertFalse(is_valid)
        self.assertIn("不存在", msg)

    def test_validate_unsupported_format(self):
        """不支援的格式應回傳錯誤"""
        import tempfile, os
        fd, fname = tempfile.mkstemp(suffix=".xyz")
        os.close(fd)
        with open(fname, "wb") as f:
            f.write(b"dummy")
        is_valid, msg = validate_audio_file(Path(fname))
        self.assertFalse(is_valid)
        os.unlink(fname)

    def test_format_timestamp(self):
        """時間戳格式化"""
        self.assertEqual(_format_timestamp(0), "00:00")
        self.assertEqual(_format_timestamp(65), "01:05")
        self.assertEqual(_format_timestamp(3661), "01:01:01")


class TestSpeakerRegistry(unittest.TestCase):
    """說話人註冊表測試"""

    def setUp(self):
        self.reg = SpeakerRegistry({"人物 #1": 10, "人物 #2": 5})

    def test_set_and_get_name(self):
        """設定與取得姓名"""
        self.assertTrue(self.reg.set_name("人物 #1", "陳大明"))
        self.assertEqual(self.reg.get_name("人物 #1"), "陳大明")
        self.assertEqual(self.reg.get_name("人物 #2"), "人物 #2")  # 未命名

    def test_empty_name_rejected(self):
        """空名稱應被拒絕"""
        self.assertFalse(self.reg.set_name("人物 #1", ""))
        self.assertFalse(self.reg.set_name("人物 #1", "   "))

    def test_reset_name(self):
        """重置名稱"""
        self.reg.set_name("人物 #1", "陳大明")
        self.reg.reset_name("人物 #1")
        self.assertIsNone(self.reg._map["人物 #1"])

    def test_duplicate_detection(self):
        """重複名稱檢測"""
        self.reg.set_name("人物 #1", "陳大明")
        self.assertIsNone(self.reg.check_duplicate())
        self.reg.set_name("人物 #2", "陳大明")
        self.assertIsNotNone(self.reg.check_duplicate())

    def test_display_name(self):
        """顯示名稱"""
        self.assertEqual(self.reg.get_display_name("人物 #1"), "人物 #1")
        self.reg.set_name("人物 #1", "陳大明")
        self.assertEqual(self.reg.get_display_name("人物 #1"), "陳大明")


class TestTextProcessor(unittest.TestCase):
    """文本處理測試"""

    def test_build_speaker_counts(self):
        """說話人次數統計"""
        segments = [
            {"id": 0, "start": 0, "end": 1, "text": "A", "speaker": "人物 #1"},
            {"id": 1, "start": 1, "end": 2, "text": "B", "speaker": "人物 #2"},
            {"id": 2, "start": 2, "end": 3, "text": "C", "speaker": "人物 #1"},
        ]
        counts = build_speaker_counts(segments)
        self.assertEqual(counts["人物 #1"], 2)
        self.assertEqual(counts["人物 #2"], 1)

    def test_merge_adjacent_same_speaker(self):
        """合併相鄰相同說話人"""
        segments = [
            {"id": 0, "start": 0, "end": 1, "text": "Hello", "speaker": "人物 #1"},
            {"id": 1, "start": 1.5, "end": 2, "text": "World", "speaker": "人物 #1"},
        ]
        merged = merge_adjacent_same_speaker(segments, max_gap_sec=2.0)
        self.assertEqual(len(merged), 1)
        self.assertIn("Hello", merged[0]["text"])
        self.assertIn("World", merged[0]["text"])

    def test_merge_different_speaker(self):
        """不同說話人不合併"""
        segments = [
            {"id": 0, "start": 0, "end": 1, "text": "A", "speaker": "人物 #1"},
            {"id": 1, "start": 1, "end": 2, "text": "B", "speaker": "人物 #2"},
        ]
        merged = merge_adjacent_same_speaker(segments)
        self.assertEqual(len(merged), 2)

    def test_segments_to_text(self):
        """轉文字輸出"""
        segments = [
            {"id": 0, "start": 0, "end": 2, "text": "大家好", "speaker": "人物 #1"},
            {"id": 1, "start": 2, "end": 5, "text": "你好", "speaker": "人物 #2"},
        ]
        text = segments_to_text(segments)
        self.assertIn("人物 #1", text)
        self.assertIn("大家好", text)

    def test_validate_segment_selection(self):
        """段落選取驗證"""
        segments = [
            {"id": 0, "start": 0, "end": 2, "text": "A"},
            {"id": 1, "start": 2, "end": 4, "text": "B"},
            {"id": 2, "start": 4, "end": 6, "text": "C"},
        ]
        # 正常選取
        valid, _, selected = validate_segment_selection(segments, [0, 1])
        self.assertTrue(valid)
        self.assertEqual(len(selected), 2)

        # 空選取
        valid, msg, _ = validate_segment_selection(segments, [])
        self.assertFalse(valid)

        # 不存在的 ID
        valid, msg, _ = validate_segment_selection(segments, [99])
        self.assertFalse(valid)
        self.assertIn("不存在", msg)

        # 過短段落
        short_segments = [{"id": 0, "start": 0, "end": 0.3, "text": "A"}]
        valid, msg, _ = validate_segment_selection(short_segments, [0])
        self.assertFalse(valid)
        self.assertIn("太短", msg)


if __name__ == "__main__":
    unittest.main()
