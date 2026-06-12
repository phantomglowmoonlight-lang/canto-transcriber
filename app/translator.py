"""
粵語→書面語翻譯器
- 主要：raptorkwok/cantonese-chinese-translation（BART 模型，~400MB，BLEU 62）
- 備援：內置字典（模型未下載時自動使用）
"""
import re
import logging
from pathlib import Path
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

# 模型快取（同 process 共用）
_translation_model = None
_translation_tokenizer = None


def _has_sdpa() -> bool:
    """檢查 torch 是否支援 SDPA"""
    try:
        import torch
        return hasattr(torch.nn.functional, 'scaled_dot_product_attention')
    except ImportError:
        return False


def _load_translation_model():
    """載入翻譯模型與 tokenizer（懶載入）"""
    global _translation_model, _translation_tokenizer

    if _translation_model is not None:
        return True

    model_path = settings.translation_model_path.strip() if settings.translation_model_path else None

    if not model_path:
        logger.info("未設定 translation_model_path，使用內置字典翻譯")
        return False

    model_dir = Path(model_path)
    if not model_dir.exists():
        logger.warning(f"翻譯模型路徑不存在：{model_path}，使用內置字典")
        return False

    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

        logger.info(f"載入翻譯模型：{model_path}")
        _translation_tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        _translation_model = AutoModelForSeq2SeqLM.from_pretrained(
            str(model_dir),
            local_files_only=True,
            # 明確指定 attention 實現以消除警告
            attn_implementation="eager" if not _has_sdpa() else "sdpa",
        )
        # 修正 generation config 中的 token ID 不匹配
        if hasattr(_translation_model, 'generation_config'):
            gc = _translation_model.generation_config
            gc.decoder_start_token_id = _translation_tokenizer.cls_token_id
            gc.eos_token_id = _translation_tokenizer.eos_token_id
            gc.pad_token_id = _translation_tokenizer.pad_token_id
        logger.info("翻譯模型載入完成")
        return True
    except Exception as e:
        logger.warning(f"翻譯模型載入失敗：{e}，使用內置字典")
        return False


def _translate_with_model(text: str) -> str:
    """使用 BART 模型翻譯單句"""
    if _translation_model is None or _translation_tokenizer is None:
        return text

    try:
        inputs = _translation_tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        inputs.pop("token_type_ids", None)

        # 使用 tokenizer 的 special token IDs（而非 model config 中可能過時的設定）
        outputs = _translation_model.generate(
            **inputs,
            max_length=512,
            num_beams=4,
            early_stopping=True,
            decoder_start_token_id=_translation_tokenizer.cls_token_id,
            eos_token_id=_translation_tokenizer.eos_token_id,
            pad_token_id=_translation_tokenizer.pad_token_id,
        )

        # Handle GenerateOutput vs tensor
        if hasattr(outputs, 'sequences'):
            token_ids = outputs.sequences[0].tolist()
        else:
            token_ids = outputs[0].tolist()

        result = _translation_tokenizer.decode(token_ids, skip_special_tokens=True)
        return result.strip()
    except Exception as e:
        logger.warning(f"模型翻譯失敗：{e}")
        return text


# ═══════════════════════════════════════════
# 內置字典（備援用，模型不可用時自動切換）
# ═══════════════════════════════════════════

CANTONESE_TO_WRITTEN_DICT = [
    # 時間
    ("而家", "現在"), ("今日", "今天"), ("聽日", "明天"), ("尋日", "昨天"),
    ("琴日", "昨天"), ("後日", "後天"), ("前日", "前天"),
    ("朝早", "早上"), ("晏晝", "下午"), ("夜晚", "晚上"),
    ("上晝", "上午"), ("下晝", "下午"), ("尋晚", "昨晚"),
    ("聽朝", "明天早上"), ("今朝", "今天早上"),
    # 代詞
    ("佢哋", "他們"), ("我哋", "我們"), ("你哋", "你們"),
    ("佢", "他"),
    # 指示詞
    ("呢度", "這裡"), ("嗰度", "那裡"), ("邊度", "哪裡"),
    ("呢個", "這個"), ("嗰個", "那個"), ("邊個", "哪個"),
    ("呢啲", "這些"), ("嗰啲", "那些"),
    ("呢", "這"), ("嗰", "那"),
    # 疑問
    ("點解", "為什麼"), ("點樣", "怎樣"), ("幾多", "多少"), ("幾時", "什麼時候"),
    # 動詞（複合詞優先，長詞在前避免部分匹配）
    ("大家好", "各位好"),
    ("講得好", "說得好"),
    ("做得好", "做得好"),
    ("話畀我知", "告訴我"),
    ("話畀", "告訴"),
    ("話俾", "告訴"),
    ("話你知", "告訴你"),
    ("話", "說"),
    ("唔同意", "不同意"),
    ("同意", "同意"),
    ("係咪", "是不是"), ("有冇", "有沒有"),
    ("鍾意", "喜歡"), ("諗", "想"),
    ("睇", "看"), ("食", "吃"), ("飲", "喝"), ("講", "說"),
    ("係", "是"), ("俾", "給"), ("畀", "給"),
    ("幫手", "幫忙"), ("傾偈", "討論"),
    ("搞掂", "完成"), ("識", "會"),
    ("搵", "找"), ("行", "走"),
    # 否定
    ("唔係", "不是"), ("唔會", "不會"), ("唔可以", "不可以"),
    ("唔使", "不需要"), ("唔想", "不想"), ("唔知道", "不知道"),
    ("唔記得", "忘記"), ("唔該", "謝謝"),
    ("冇問題", "沒問題"), ("冇辦法", "沒辦法"), ("冇可能", "不可能"),
    ("冇人", "沒有人"), ("冇錯", "沒錯"),
    ("唔", "不"), ("冇", "沒有"), ("未", "還沒"),
    # ── 副詞（複合詞保護優先）──
    ("各位好", "各位好"),   # 防止「好」被誤轉為「很」
    ("你好", "你好"),
    ("好快", "很快"),
    ("好慢", "很慢"),
    ("好多", "很多"),
    ("好少", "很少"),
    ("好大", "很大"),
    ("好細", "很小"),
    ("好高", "很高"), ("好低", "很低"),
    ("好遠", "很遠"), ("好近", "很近"),
    ("好貴", "很貴"), ("好平", "很便宜"),
    ("好容易", "很容易"), ("好難", "很難"),
    ("好開心", "很開心"),
    ("好", "很"),
    ("幾好", "挺好"), ("幾", "挺"),
    ("咁", "這麼"), ("咁樣", "這樣"),
    # 介詞/連詞
    ("喺", "在"), ("同埋", "以及"), ("同", "和"),
    ("但係", "但是"), ("如果", "如果"), ("因為", "因為"), ("所以", "所以"),
    # 助詞
    ("嘅", "的"), ("咗", "了"), ("啲", "些"), ("吓", "一下"),
    ("晒", "全部"), ("住", "著"), ("緊", "正在"),
    # 口語詞
    ("嘢", "事情"), ("屋企", "家裡"),
    ("點", "怎麼"), ("咩", "嗎"), ("啦", "了"),
]
CANTONESE_TO_WRITTEN_DICT.sort(key=lambda x: len(x[0]), reverse=True)


def _translate_with_dict(text: str) -> str:
    """使用內置字典翻譯"""
    result = text
    for canto, written in CANTONESE_TO_WRITTEN_DICT:
        if canto in result:
            result = result.replace(canto, written)
    return re.sub(r'\s+', ' ', result).strip()


# ═══════════════════════════════════════════
# 公開 API
# ═══════════════════════════════════════════

def translate_text(text: str) -> str:
    """
    翻譯單句粵語→書面語
    優先使用 BART 模型，不可用或結果異常時自動切換內置字典
    """
    if not text or not text.strip():
        return text

    # 先嘗試模型
    if _load_translation_model():
        try:
            result = _translate_with_model(text)
            # 檢查模型輸出是否合理：結果不應該與原文完全相同（除非本身就是書面語）
            # 且結果不應該過短
            if result and result != text and len(result) > 1:
                return result
        except Exception:
            pass

    # 備援：內置字典
    return _translate_with_dict(text)


def translate_segments_builtin(
    segments: list[dict],
    scope: str = "all",
    segment_ids: Optional[list[int]] = None,
) -> dict:
    """
    批量翻譯段落

    回傳:
    {
        "success": True,
        "updated_segments": [...],
        "method": "model" | "dict",
    }
    """
    use_model = _load_translation_model()
    method = "model" if use_model else "dict"
    logger.info(f"翻譯模式：{method}")

    if scope == "selected" and segment_ids:
        target_ids = set(segment_ids)
    else:
        target_ids = {seg["id"] for seg in segments}

    updated = []
    translated_count = 0
    for seg in segments:
        seg_copy = dict(seg)
        if seg["id"] in target_ids and seg.get("text"):
            original = seg["text"]
            translated = translate_text(original)
            if translated and translated != original:
                seg_copy["text_written"] = translated
                seg_copy["translation_stale"] = False
                translated_count += 1
        updated.append(seg_copy)

    logger.info(f"翻譯完成：{translated_count} 句，模式：{method}")
    return {
        "success": True,
        "updated_segments": updated,
        "method": method,
        "translated_count": translated_count,
    }
