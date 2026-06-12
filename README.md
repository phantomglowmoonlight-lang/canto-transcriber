# 廣東話會議錄音轉文字系統

> 完整產品需求文檔請見 [PRD.md](./PRD.md)
> UI 設計規範請見 [UI-SPEC.md](./UI-SPEC.md)

## 概述

一套純本機運行的會議錄音轉寫工具，專為廣東話（粵語）會議場景設計。支援長音檔自動切割、說話人分離、人名管理、TXT/DOCX 匯出，以及 AI 會議報告生成。

## 功能列表

| 功能 | 說明 |
|------|------|
| 廣東話語音識別 | 基於 faster-whisper large-v3 模型，支援 `yue` 語言代碼 |
| 粵語→書面語翻譯 | 將 STT 輸出的粵語口語翻譯為書面語，支援三種檢視模式（原文/書面語/對照） |
| 自動音檔切割 | 超過 10 分鐘自動按時間切割，段落間保留重疊避免切斷句子 |
| 說話人分離 | 自動辨識一號人物、二號人物等，支援手動命名與全篇替換 |
| 單句/多句重新 STT | 選取識別不準的句子，從原始音檔重新跑語音識別 |
| 降噪 / 提音量 toggle | 針對選取句子獨立開關降噪或增益，兩者可疊加，改善識別準確率 |
| 多格式匯出 | TXT 純文字 / DOCX 帶格式文件，可選粵語原文或書面語版本 |
| AI 會議報告 | 透過 LLM API（Ollama / OpenAI）將轉寫內容生成結構化會議報告，可選基於粵語還是書面語 |
| Web API | FastAPI 服務器，可整合到其他系統 |
| 簡易 Web UI | 內建瀏覽器介面，無須安裝額外工具 |

## 技術棧

| 組件 | 技術選擇 | 原因 |
|------|----------|------|
| 語音識別 | faster-whisper (large-v3) | 支援粵語，準確率最強，純本機，Apache-2.0 |
| 音頻處理 | ffmpeg + pydub | 萬能格式轉換，精確切割 |
| 說話人分離 | pyannote-audio / webrtcvad | 兩級備援：精準分離 / 基礎 VAD 分段 |
| 後端框架 | FastAPI + uvicorn | 輕量高效，自動生成 API 文檔 |
| AI 整合 | OpenAI 相容 API | 支援 Ollama 本機 LLM 或任何 OpenAI 相容端點 |
| 文件生成 | python-docx | 純 Python DOCX 生成，無需 Word |
| 配置管理 | pydantic-settings | 類型安全，支援 .env |

## 系統架構

```
錄音檔案 (*.mp3/*.wav/*.m4a/*.ogg)
        │
        ▼
┌───────────────────┐
│  audio_processor  │  音頻載入、格式轉換、切割
│  (pydub + ffmpeg) │  自動過長切割 + 重疊保留
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│   transcriber     │  faster-whisper 廣東話轉寫
│  (faster-whisper) │  輸出帶時間戳的逐段文字
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│    diarizer       │  說話人分離
│  (pyannote/VAD)   │  區分不同發言人
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  text_processor   │  合併分段、人名替換
│  + speaker_reg    │  維護 {代號→姓名} 映射
└────────┬──────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────┐
│Export │ │  API  │  AI 會議報告生成
│txt/docx│ │server │  (可選 LLM 整合)
└───────┘ └───────┘
```

## 安裝步驟

### 前置需求

- Python 3.10+
- ffmpeg（系統路徑可用）
- 建議 8GB+ RAM（large-v3 模型約需 4GB）

### 安裝

```bash
# 1. 建立虛擬環境
cd canto-transcriber
python -m venv venv
source venv/bin/activate      # Linux/Mac
# 或 venv\Scripts\activate    # Windows

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 複製環境變數
cp .env.example .env
# 編輯 .env 設定模型路徑、LLM API 等

# 4. 確認 ffmpeg 可用
ffmpeg -version
```

### 首次下載模型

第一次執行時，faster-whisper 會自動下載 large-v3 模型（約 3GB）。下載時間取決於網絡速度。

下載完成後模型會快取在 `~/.cache/whisper/` 或 `%USERPROFILE%\.cache\whisper\`。

## 使用方式

### CLI 命令列

```bash
# 基本轉寫
python -m app.cli transcribe 會議錄音.mp3

# 指定輸出目錄
python -m app.cli transcribe 會議錄音.mp3 --output ./output

# 指定說話人分離模式（vad=簡單VAD, pyannote=精準分離）
python -m app.cli transcribe 會議錄音.mp3 --diarization pyannote

# 轉寫完成後打開互動式人名編輯
python -m app.cli edit ./output/會議錄音.json

# 匯出成 DOCX
python -m app.cli export ./output/會議錄音.json --format docx

# 生成 AI 會議報告（需配置 LLM API）
python -m app.cli report ./output/會議錄音.json --output ./output/會議報告.md

# 啟動 API 服務器
python -m app.cli serve --port 8000
```

### 互動式編輯人名

執行 `edit` 命令後進入互動模式：

```
發現以下發言人：
  人物 #1（出現 23 次）
  人物 #2（出現 18 次）
  人物 #3（出現 5 次）

輸入人物編號和姓名（例如：1 陳大明），或輸入 "done" 完成：
> 1 陳大明
已將「人物 #1」→「陳大明」

> 2 李小華
已將「人物 #2」→「李小華」

> done
正在套用全篇替換... 完成！
已輸出：./output/會議錄音_已命名.txt
```

### API 服務器

```bash
# 啟動 API
python -m app.cli serve

# 服務器運行在 http://localhost:8000
# API 文檔在 http://localhost:8000/docs
```

#### API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/v1/transcribe` | 提交音檔轉寫任務 |
| GET | `/v1/tasks/{task_id}` | 查詢任務狀態與結果 |
| POST | `/v1/tasks/{task_id}/export` | 匯出轉寫結果 |
| POST | `/v1/tasks/{task_id}/report` | 生成 AI 會議報告 |
| POST | `/v1/speakers/rename` | 替換發言人姓名 |
| GET | `/v1/health` | 健康檢查 |

**提交轉寫任務：**
```bash
curl -X POST http://localhost:8000/v1/transcribe \
  -F "audio=@會議錄音.mp3" \
  -F "diarization=vad"
```

**生成會議報告：**
```bash
curl -X POST http://localhost:8000/v1/tasks/{task_id}/report \
  -H "Content-Type: application/json" \
  -d '{"model": "ollama", "model_name": "gemma3:12b", "prompt_template": "custom"}'
```

### Web UI

啟動 API 服務器後，瀏覽器打開 `http://localhost:8000` 即可使用內建 Web 介面。

## 音檔切割策略

系統對長音檔採取兩級切割：

1. **語音活動檢測（VAD）級**：用 webrtcvad 偵測靜音段落，按自然停頓分段
2. **時間級**：若段落仍超過 10 分鐘，強制按時間切割（預設 10 分鐘一段）
3. **重疊保留**：切割點前後保留 30 秒重疊，避免句首遺漏

切割後的段落獨立轉寫，最後按時間戳合併。

## 說話人分離說明

### pyannote-audio（精準模式）

需要 Hugging Face token：
1. 註冊 https://huggingface.co
2. 同意 pyannote 模型條款：
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. 在 HF 生成 Access Token
4. 填入 `.env` 的 `HF_TOKEN`

### VAD 分段模式（輕量模式）

無需任何 token，使用 webrtcvad + 時間聚類，適合發言人輪流發言的會議場景。精確度低於 pyannote，但零配置、零下載。

## 配置參考（.env）

```ini
# --- 語音識別 ---
WHISPER_MODEL_SIZE=large-v3
WHISPER_DEVICE=auto         # auto/cpu/cuda
WHISPER_COMPUTE_TYPE=float16   # int8/float16/float32

# --- 音頻處理 ---
CHUNK_MAX_MINUTES=10
CHUNK_OVERLAP_SECONDS=30
SAMPLE_RATE=16000

# --- 說話人分離 ---
DIARIZATION_MODE=auto         # auto/pyannote/vad
HF_TOKEN=                     # pyannote 需要

# --- AI 會議報告 ---
LLM_PROVIDER=ollama           # ollama / openai / custom
LLM_API_BASE=http://localhost:11434/v1
LLM_API_KEY=
LLM_MODEL=gemma3:12b
REPORT_LANGUAGE=zh             # zh / yue / en

# --- API 服務器 ---
API_HOST=0.0.0.0
API_PORT=8000
```

## 專案結構

```
canto-transcriber/
├── README.md
├── requirements.txt
├── .env.example
├── .env                      # 本地配置（不入 git）
├── app/
│   ├── __init__.py
│   ├── config.py             # pydantic-settings 配置
│   ├── cli.py                # CLI 入口（typer）
│   ├── api_server.py         # FastAPI 服務器
│   ├── audio_processor.py    # 音頻載入 / 切割
│   ├── transcriber.py        # faster-whisper 轉寫
│   ├── diarizer.py           # 說話人分離
│   ├── text_processor.py     # 文本後處理 / 人名替換
│   ├── speaker_registry.py   # 發言人註冊表
│   ├── exporter.py           # TXT / DOCX 匯出
│   └── report_generator.py   # AI 會議報告
├── frontend/
│   └── index.html            # 內建 Web UI
└── tests/
    └── test_basic.py
```

## 注意事項

1. **模型體積**：large-v3 約 3GB，首次下載需要網絡。這是目前廣東話語音識別準確率最高的本機方案
2. **背景噪音**：會議錄音品質建議乾淨，背景噪音會影響轉寫準確率。可使用內建的降噪功能改善
3. **多語言混合**：如果會議中英夾雜，轉寫效果仍可接受，但建議主要使用單一語言
4. **ffmpeg**：Windows 用戶可從 https://ffmpeg.org/download.html 下載，確保加入 PATH
