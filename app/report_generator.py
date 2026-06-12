"""
AI 會議報告生成模組：透過 OpenAI 相容 API（Ollama 等）生成結構化會議報告
"""
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = """你是一位專業的會議記錄整理助手。以下是{source_desc}，請根據內容生成結構化會議報告。

報告必須包含以下部分：
1. 會議基本資訊（日期從內容中推斷，參與人列表）
2. 討論議題（每個議題要點總結）
3. 每個議題中的關鍵發言引述
4. 會議結論
5. 待辦事項（格式：- [ ] 事項 @負責人）

要求：
- 使用{lang_desc}撰寫
- 保留有代表性的原文引述（使用 > 區塊引用）
- 待辦事項具體可執行，明確責任人
- 使用 Markdown 格式輸出"""


def generate_report(
    segments: list[dict],
    written: bool = False,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    report_lang: Optional[str] = None,
) -> dict:
    """
    透過 LLM API 生成結構化會議報告

    回傳:
    {
        "success": true,
        "report": "# 會議紀要\n...",
        "model": "gemma3:12b",
        "tokens_used": 1234
    }
    """
    provider = provider or settings.llm_provider
    model = model or settings.llm_model
    api_base = api_base or settings.llm_api_base
    api_key = api_key or settings.llm_api_key
    report_lang = report_lang or settings.report_language

    # 構建完整轉寫文本
    source_desc = "一份書面語的會議轉寫" if written else "一份粵語口語的會議轉寫"
    lang_desc_map = {"zh": "繁體中文", "yue": "粵語口語風格", "en": "英文"}
    lang_desc = lang_desc_map.get(report_lang, "繁體中文")

    # 構建會議文本
    transcript_lines = []
    for seg in segments:
        speaker = seg.get("speaker", "人物 #1")
        text = seg.get("text_written" if written else "text", "")
        timestamp = f"[{_format_ts(seg['start'])}]"
        transcript_lines.append(f"{timestamp} {speaker}：{text}")

    transcript = "\n".join(transcript_lines)

    # 構建 API 請求
    system_prompt = REPORT_SYSTEM_PROMPT.format(
        source_desc=source_desc,
        lang_desc=lang_desc,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"以下是會議轉寫內容：\n\n{transcript}"},
    ]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 處理 Ollama 端點路徑
    api_url = api_base.rstrip("/")
    if provider == "ollama" and "/v1" not in api_url:
        api_url += "/v1"
    api_url += "/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            report = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)

            return {
                "success": True,
                "report": report,
                "model": model,
                "tokens_used": tokens,
            }
    except httpx.HTTPError as e:
        logger.error(f"LLM API 請求失敗：{e}")
        return {
            "success": False,
            "error": f"API 請求失敗：{str(e)}",
            "report": "",
            "model": model,
        }
    except Exception as e:
        logger.error(f"生成報告時發生錯誤：{e}")
        return {
            "success": False,
            "error": str(e),
            "report": "",
            "model": model,
        }


def translate_to_written(
    segments: list[dict],
    scope: str = "all",
    segment_ids: Optional[list[int]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    將粵語口語翻譯為書面語

    scope: "all" 整篇翻譯 / "selected" 選取翻譯
    segment_ids: scope="selected" 時指定段落 ID

    回傳:
    {
        "success": true,
        "updated_segments": [...],
        "model": "..."
    }
    """
    provider = provider or settings.llm_provider
    model = model or settings.llm_model
    api_base = api_base or settings.llm_api_base
    api_key = api_key or settings.llm_api_key

    # 確定要翻譯的段落
    if scope == "selected" and segment_ids:
        target_segments = [s for s in segments if s["id"] in segment_ids]
    else:
        target_segments = segments

    if not target_segments:
        return {"success": False, "error": "沒有可翻譯的段落"}

    # 構建翻譯 prompt
    sentences = []
    for seg in target_segments:
        sentences.append(f"[{seg['id']}] {seg['text']}")

    system_prompt = """你是粵語口語到繁體中文書面語的翻譯專家。請將以下粵語口語句子翻譯成標準繁體中文書面語。

規則：
1. 保留原意，不要增減資訊
2. 口語化詞彙轉為書面語（例如：「嘅」→「的」、「咗」→「了」、「唔」→「不」、「冇」→「沒有」）
3. 保留專有名詞（人名、地名、公司名）不翻譯
4. 每句獨立翻譯，輸出格式為：[段落ID] 翻譯結果
5. 不要輸出任何其他內容"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(sentences)},
    ]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    api_url = api_base.rstrip("/")
    if provider == "ollama" and "/v1" not in api_url:
        api_url += "/v1"
    api_url += "/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

        # 解析翻譯結果
        translations = {}
        for line in content.strip().split("\n"):
            line = line.strip()
            if line.startswith("[") and "]" in line:
                try:
                    id_str = line[1:line.index("]")]
                    seg_id = int(id_str)
                    text = line[line.index("]") + 1:].strip()
                    translations[seg_id] = text
                except (ValueError, IndexError):
                    continue

        # 更新段落
        updated = []
        for seg in segments:
            seg_copy = dict(seg)
            if seg["id"] in translations:
                seg_copy["text_written"] = translations[seg["id"]]
                seg_copy["translation_stale"] = False
            elif seg["id"] in {s["id"] for s in target_segments}:
                seg_copy["text_written"] = None
            updated.append(seg_copy)

        return {
            "success": True,
            "updated_segments": updated,
            "model": model,
        }

    except Exception as e:
        logger.error(f"翻譯失敗：{e}")
        return {"success": False, "error": str(e)}


def _format_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"
