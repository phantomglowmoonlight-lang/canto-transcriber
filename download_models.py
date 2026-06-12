"""
下載所有內置模型到本機目錄
執行：py download_models.py
"""
import os
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# ═══════════════════════════════════════════
# 模型 1：faster-whisper large-v3（語音識別）
# ═══════════════════════════════════════════
WHISPER_DIR = os.path.join(MODELS_DIR, "faster-whisper-large-v3")

print("=" * 60)
print("模型 1/2：faster-whisper large-v3（語音識別）")
print(f"存放目錄：{WHISPER_DIR}")
print("大小約 3GB，請確保網絡穩定...")
print("=" * 60)

try:
    from faster_whisper import WhisperModel

    # CPU 不支援 float16，使用 int8 下載（模型參數相同，僅載入精度不同）
    model = WhisperModel(
        "large-v3",
        device="cpu",
        compute_type="int8",  # CPU 下載用 int8
        download_root=WHISPER_DIR,
        local_files_only=False,
    )
    # 立即釋放記憶體
    del model
    print("✅ faster-whisper large-v3 下載完成！")
except Exception as e:
    print(f"❌ faster-whisper 下載失敗：{e}")
    print("  你可以稍後重新執行此腳本")

print()

# ═══════════════════════════════════════════
# 模型 2：粵語→書面語翻譯
# ═══════════════════════════════════════════
TRANSLATION_DIR = os.path.join(MODELS_DIR, "cantonese-chinese-translation")

print("=" * 60)
print("模型 2/2：raptorkwok/cantonese-chinese-translation（粵語→書面語）")
print(f"存放目錄：{TRANSLATION_DIR}")
print("大小約 400MB...")
print("=" * 60)

try:
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import json

    MODEL_ID = "raptorkwok/cantonese-chinese-translation"

    # 下載 tokenizer
    print("  下載 tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    tokenizer.save_pretrained(TRANSLATION_DIR)

    # 下載模型
    print("  下載模型...")
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID)

    # 修復 generation config 再儲存（避免驗證錯誤）
    if hasattr(model, 'generation_config'):
        gc = model.generation_config
        gc.return_dict_in_generate = True
        gc.output_attentions = False
        gc.output_hidden_states = False

    model.save_pretrained(TRANSLATION_DIR)
    del model
    del tokenizer

    print("✅ 翻譯模型下載完成！")
except Exception as e:
    print(f"❌ 翻譯模型下載失敗：{e}")
    print("  你可以稍後重新執行此腳本")
    # 嘗試清理不完整的下載
    if os.path.exists(TRANSLATION_DIR):
        shutil.rmtree(TRANSLATION_DIR, ignore_errors=True)

print()
print("=" * 60)
print("下載完成！")
print(f"  WHISPER_MODEL_PATH={WHISPER_DIR}")
print(f"  TRANSLATION_MODEL_PATH={TRANSLATION_DIR}")
print()
print("請確認 .env 已設定上述路徑。")
print("若模型下載失敗，可稍後重新執行：py download_models.py")
print("=" * 60)
