"""
說話人註冊表：維護 {代號 → 姓名} 映射
"""
from typing import Optional


class SpeakerRegistry:
    """管理說話人代號與真實姓名的映射"""

    def __init__(self, speaker_counts: Optional[dict[str, int]] = None):
        """
        speaker_counts: { "人物 #1": 23, "人物 #2": 18 }
        """
        self._map: dict[str, Optional[str]] = {}
        if speaker_counts:
            for speaker_id, count in speaker_counts.items():
                self._map[speaker_id] = None  # None = 未命名

    def set_name(self, speaker_id: str, name: str) -> bool:
        """
        設定說話人真實姓名

        回傳 False 如果 speaker_id 不存在
        """
        if speaker_id not in self._map:
            return False
        name = name.strip()
        if not name:
            return False
        self._map[speaker_id] = name
        return True

    def get_name(self, speaker_id: str) -> str:
        """取得說話人顯示名稱（已命名回傳姓名，未命名回傳代號）"""
        return self._map.get(speaker_id) or speaker_id

    def reset_name(self, speaker_id: str):
        """重置為預設代號"""
        if speaker_id in self._map:
            self._map[speaker_id] = None

    def get_display_name(self, speaker_id: str) -> str:
        """唯讀顯示名稱"""
        name = self._map.get(speaker_id)
        return name or speaker_id

    def check_duplicate(self) -> Optional[list[str]]:
        """
        檢查是否有兩個不同代號被命名為相同姓名

        回傳衝突的姓名列表，無衝突回傳 None
        """
        named = {}
        for sid, name in self._map.items():
            if name:
                if name in named:
                    return [name, sid, named[name]]
                named[name] = sid
        return None

    @property
    def speakers(self) -> list[dict]:
        """列出所有說話人資訊"""
        result = []
        for sid, name in self._map.items():
            result.append({
                "id": sid,
                "name": name,
                "display": name or sid,
            })
        return result

    def to_dict(self) -> dict:
        return {
            sid: name
            for sid, name in self._map.items()
        }

    @classmethod
    def from_dict(cls, data: dict, counts: Optional[dict[str, int]] = None) -> "SpeakerRegistry":
        reg = cls(counts or {})
        for sid, name in (data or {}).items():
            if name:
                reg.set_name(sid, name)
        return reg
