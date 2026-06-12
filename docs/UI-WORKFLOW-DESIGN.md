# CantoTranscriber UI 與操作流程方案

> 版本：v1.0  
> 基於現有 frontend/index.html + app/api_server.py 架構  
> 解決老闆提出的 6 個核心問題

---

## 目錄

1. [整體佈局圖](#1-整體佈局圖)
2. [操作流程（完整狀態機）](#2-操作流程完整狀態機)
3. [功能模塊 UI 規格](#3-功能模塊-ui-規格)
4. [切割功能 UI 細節](#4-切割功能-ui-細節)
5. [Cache 機制說明](#5-cache-機制說明)
6. [批量 STT 的進度與錯誤處理](#6-批量-stt-的進度與錯誤處理)

---

## 1. 整體佈局圖

### 1.1 頁面結構（三頁 SPA）

現有系統分三頁：Upload → Processing → Workspace。  
保留此結構，但擴充 Workspace 頁加入時間線/波形/切割功能。

```
┌─────────────────────────────────────────────────────────────┐
│  [上傳頁面]        [處理中頁面]        [工作區頁面]          │
│                                                             │
│  ┌─────────┐      ┌─────────┐      ┌──────────────────────┐│
│  │ drop zone│ ──→  │ progress│ ──→  │ toolbar (頂部工具列)  ││
│  │         │      │  bar    │      ├──────────────────────┤│
│  │confirm  │      │ steps   │      │ 波形 + 時間線 (新!)   ││
│  │ modal   │      │ 列表    │      ├──────────────────────┤│
│  │ (新!)   │      │         │      │ 段落列表 (原有)       ││
│  └─────────┘      └─────────┘      │ + 側欄 (說話人面板)   ││
│                                     ├──────────────────────┤│
│                                     │ 播放器底欄 (強化)     ││
│                                     └──────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Workspace 頁面詳細佈局

```
┌─ 頂部工具列 (height: 48px) ─────────────────────────────────┐
│ [📂 新建項目]  會議_2024_10_15.mp3 (1:23:45)  [🔊] [✂ 切割]   │
│                        [書面語翻譯] [AI報告] [匯出 ▼]         │
├─ 波形 + 時間線 (新區域, height: 180px, 可摺疊) ────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  波形視圖 (Canvas, 可縮放縮放桿 + / -)                  │ │
│  │  ▄▃▂▁▁▂▃▄▅▆▇██▇▆▅▄▃▂▁▁▂▃▄▅▆▇██▇▆▅▄▃▂               │ │
│  │           ▶ (播放頭, 可拖動)                             │ │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │                 │ │
│  │  0:00  0:30  1:00  1:30  2:00  2:30  3:00             │ │
│  │                                                          │ │
│  │  [切割標註示例]                                          │ │
│  │  ▄▃▂▁▁│▂▃▄▅▆▇█│█▇▆▅▄▃│▂▁▁▂▃▄▅▆▇│██▇▆▅▄▃▂▁            │ │
│  │        ✂       ✂       ✂                                │ │
│  │        A       B       C        (切割點標籤)             │ │
│  └─────────────────────────────────────────────────────────┘ │
│  [− 縮小]  [+] 放大    [⏎ 重設縮放]    [切割中...] [✓ 確認切割]│
│                                                              │
├─ 主工作區 ───────────────────────────────────────────────────┤
│  ┌─ 段落列表 (flex: 7) ────┐ ┌─ 說話人面板 (flex: 3) ────┐  │
│  │ 檢視: [原文|書面語|對照]  │ │  人物 #1 (23次)           │  │
│  │ ☐ 00:00:08 [人物 #2]    │ │  [____陳大明___]          │  │
│  │   我諗我哋要討論預算      │ │  人物 #2 (18次)           │  │
│  │ ☐ 00:00:22 [人物 #1]    │ │  [____李小華___]          │  │
│  │   冇問題，你繼續講        │ │  人物 #3 (5次)            │  │
│  │ ☐ 00:00:30 [人物 #1]    │ │  [未命名______]           │  │
│  │   ...                    │ │                           │  │
│  └──────────────────────────┘ └───────────────────────────┘  │
├─ 播放器底欄 (height: 64px) ──────────────────────────────────┤
│ [⏮] [▶/⏸] [⏭]   ═══●═══════════   00:23:45 / 01:23:45    │
│ [🔁 循環A-B] 速度[1.0x ▾] [-5s] [+5s]                      │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 上傳頁面 — 新增確認對話框

```
┌────────────────────────────────────────────────┐
│             拖入檔案後的確認視窗                   │
│ ┌────────────────────────────────────────────┐  │
│ │                                            │  │
│ │  📁 已選取音檔                              │  │
│ │                                            │  │
│ │  檔案名稱：會議錄音_2024-10-15.mp3          │  │
│ │  檔案大小：156.3 MB                         │  │
│ │  時長：01:23:45 (約 83 分鐘)               │  │
│ │  格式：MP3 (audio/mpeg)                    │  │
│ │                                            │  │
│ │  ┌─ 處理選項 ─────────────────┐            │  │
│ │  │  ● VAD 輕量模式 (建議)      │            │  │
│ │  │  ○ pyannote 精準模式        │            │  │
│ │  │  □ 自動切割長音頻 (≥10分鐘)  │            │  │
│ │  └────────────────────────────┘            │  │
│ │                                            │  │
│ │  ┌─ 時間範圍 (可裁剪) ────────┐            │  │
│ │  │  從 [00:00:00 ▸] 到 [01:23:45 ▸]       │  │
│ │  │  [🔄 預聽]                │            │  │
│ │  └────────────────────────────┘            │  │
│ │                                            │  │
│ │       [取消]          [開始轉寫]            │  │
│ └────────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

> 注意：時間範圍裁剪是進階功能（P2），初期可以先不實作，只顯示時長資訊供確認。

---

## 2. 操作流程（完整狀態機）

### 2.1 全生命周期流程圖

```
                     ┌──────────┐
                     │ 應用啟動  │
                     └────┬─────┘
                          │
                          ▼
                   ┌──────────────┐
              ┌────│ 檢查上次快取   │
              │    └──────┬───────┘
              │   ┌───────▼────────┐
              │   │ 有未完成任務?   │──── 有 ──→ 載入恢復
              │   └───────┬────────┘
              │           │ 無
              │           ▼
              │    ┌──────────────┐
              └───→│   上傳頁面    │
                   └──────┬───────┘
                          │
                    拖入/選取檔案
                          │
                          ▼
                   ┌──────────────┐
                   │ 確認對話框    │ ← 新功能：顯示檔名、時長、格式
                   │ (可選裁剪)    │
                   └──────┬───────┘
                          │ 用戶確認
                          ▼
                   ┌──────────────┐
                   │ POST /transcribe
                   │ → 處理中頁面  │
                   │   輪詢進度    │
                   └──────┬───────┘
                          │ 完成
                          ▼
                   ┌──────────────────────┐
                   │     Workspace 頁面    │
                   │                      │
                   │ ┌──────────────────┐ │
                   │ │ 可選: 手動切割    │ │
                   │ │ ✂ 切割模式       │ │
                   │ │ → 標註切割點     │ │
                   │ │ → 調整切割點     │ │
                   │ │ → 確認切割      │ │
                   │ │ → 產生多段音頻   │ │
                   │ └────────┬─────────┘ │
                   │          │           │
                   │ ┌────────▼─────────┐ │
                   │ │ 下一步: 批量 STT  │ │
                   │ │ 逐段處理          │ │
                   │ │ 做一段存一段      │ │
                   │ │ (進度可中斷恢復)  │ │
                   │ └────────┬─────────┘ │
                   │          │           │
                   │ ┌────────▼─────────┐ │
                   │ │ 結果檢視/編輯     │ │
                   │ │ · 播放同步校對    │ │
                   │ │ · 人名編輯       │ │
                   │ │ · 書面語翻譯     │ │
                   │ │ · 單段重新 STT   │ │
                   │ │ · AI 報告       │ │
                   │ │ · 匯出          │ │
                   │ └──────────────────┘ │
                   └──────────────────────┘
                          │
                 用戶點擊「新建項目」
                          │
                          ▼
                   ┌──────────────┐
                   │ 清理快取      │
                   │ → 回到上傳頁  │
                   └──────────────┘
```

### 2.2 狀態轉換詳表

| 當前狀態 | 觸發事件 | 下一狀態 | 副作用 |
|---------|---------|---------|--------|
| 啟動 | 無快取 | 上傳頁面 | — |
| 啟動 | 有快取任務 | 直接進入 workspace | 載入 task.json |
| 上傳頁面 | 拖入檔案 | 顯示確認對話框 | 前端計算時長/格式 |
| 確認對話框 | 用戶取消 | 上傳頁面 | 清除暫存 |
| 確認對話框 | 用戶確認 | 處理中頁面 | POST /v1/transcribe |
| 處理中 | 進度 100% | Workspace | — |
| 處理中 | 失敗 | 顯示錯誤 + 重試 | — |
| Workspace | 點擊「✂ 切割」| 切割模式 | 波形顯示切割 UI |
| 切割模式 | 標註切割點 | 待確認切割 | — |
| 待確認切割 | 確認切割 | 切割完成 | 後端切割音檔 + 更新 segments |
| 待確認切割 | 取消切割 | 一般 Workspace | 清除切割標註 |
| Workspace | 點擊「下一步 STT」| 批量 STT 中 | 逐段提交 /v1/transcribe |
| 批量 STT 中 | 一段完成 | 更新該段結果 | 寫入 task.json |
| 批量 STT 中 | 所有完成 | 結果檢視 | — |
| 批量 STT 中 | 某一失敗 | 顯示錯誤，可重試該段 | 已完成的保留 |
| 結果檢視 | 點擊「新建項目」| 確認放棄 | 清理 task + 上傳檔案 |
| 確認放棄 | 確認 | 上傳頁面 | 刪除 task.json + upload dir |
| 確認放棄 | 取消 | 停留在 workspace | — |

### 2.3 分割後的平行處理流程（重點）

```
STT 完成後的 Workspace 不是終點，而是編輯中樞。

用戶可以有兩種路徑：

路徑 A（不切割，直接 STT）：
  Workspace → [下一步] → 批量 STT（整段）→ 完成

路徑 B（先切割，再逐段 STT）：
  Workspace → [✂ 切割] → 標切割點 → [確認切割]
  → 切割完成，產生 N 個 segment
  → [下一步] → 批量 STT（逐段處理，做一段存一段）
  → 全部完成

兩種路徑在批量 STT 完成後匯合到同一結果檢視。
```

---

## 3. 功能模塊 UI 規格

### 3.1 波形 + 時間線（新功能 — 解決問題 1 和 4）

#### 3.1.1 技術方案

| 項目 | 選擇 | 理由 |
|------|------|------|
| 波形生成 | 後端 Python (pydub + numpy) 計算波形峰值 → 前端接收 JSON 陣列 | 避免前端 decode 音檔，減少記憶體 |
| 波形繪製 | 前端 Canvas 自繪，從後端獲取峰值數據 (Array<number>) | 零依賴，完全控制互動 |
| 縮放 | 用 zoomLevel 變數控制 Canvas 繪製的採樣間隔 | 簡單有效 |
| CDN 輔助 | wavesurfer.js (可選) 如果自繪時間不夠 | 但自繪方案優先 |

#### 3.1.2 後端 API（新增）

```
GET /v1/tasks/{task_id}/waveform
Response: {
  "duration": 5025.3,
  "peaks": [0.12, 0.34, 0.56, ...],      // 標準化 0.0~1.0 峰值陣列
  "sample_rate": 100,                      // 每秒採樣數
  "total_samples": 502530
}
```

後端實現（`audio_processor.py` 新增函數）：

```python
def compute_waveform_peaks(wav_path: Path, samples_per_second: int = 100) -> dict:
    """
    讀取 WAV，計算標準化峰值，回傳前端可用數據。
    samples_per_second 控制數據量（100 samples/sec → 1hr=360K floats → ~2.8MB JSON）
    """
    from pydub import AudioSegment
    import numpy as np

    audio = AudioSegment.from_file(str(wav_path))
    # 轉為 mono + 32bit float
    audio = audio.set_channels(1).set_frame_rate(16000)
    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
    samples /= np.max(np.abs(samples)) + 1e-10

    # 降採樣
    step = max(1, len(samples) // int(audio.duration_seconds * samples_per_second))
    peaks = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i+step]
        peaks.append(float(np.max(np.abs(chunk))))

    return {
        "duration": audio.duration_seconds,
        "peaks": peaks,
        "sample_rate": samples_per_second,
        "total_samples": len(peaks),
    }
```

#### 3.1.3 前端 Canvas 繪製邏輯

```
class WaveformRenderer:
    - canvas: HTMLCanvasElement (全寬, height: 150px)
    - peaks: number[] (來自 API)
    - zoomLevel: number (1=全部可見, 越大越精細)
    - scrollOffset: number (縮放後的水平偏移)
    - playheadX: number (播放頭位置)
    - cutMarkers: number[] (切割點時間戳位置)

    繪製:
      1. 背景 (淺灰 #F1F5F9)
      2. 波形條 (深藍 #2563EB, 透明度 0.3~0.8)
      3. 時間刻度 (每 5 秒/30 秒/1 分鐘 依 zoomLevel 而定)
      4. 段落高亮 (當前播放段落背景色)
      5. 切割標註線 (紅色虛線, 附標籤 A/B/C)
      6. 播放頭 (紅色豎線 + 圓形拖動點)

    互動事件:
      - mousedown on canvas → 計算游標時間 → 跳轉播放
      - mousedown on playhead → 進入拖動模式 → mousemove 追蹤
      - mouseup → 結束拖動 → 設定 currentTime
      - wheel → 橫向滾動 (shift+wheel 縮放)
      - 切割模式下點擊 → 新增切割點
      - 拖動切割點標籤 → 移動切割點位置
```

#### 3.1.4 播放頭雙向同步

```
播放器 ↔ 波形頭雙向綁定：

方向 A (播放器 → 波形)：
  audioEl.ontimeupdate → waveformRenderer.setPlayhead(currentTime)

方向 B (波形 → 播放器)：
  canvas.onclick (或 playhead drag) → audioEl.currentTime = t

一致保證：
  以 audioEl.currentTime 為真實來源，波形只反映不反寫。
```

### 3.2 播放器控制（解決問題 2）

#### 3.2.1 現有問題診斷

查看現有 `frontend/index.html`，播放功能確實存在但問題在於：

1. `togglePlay()` 函數在工作區載入時建立 `<audio>`，但音檔路徑可能不正確或未正確載入
2. 時間條 (`seek-bar`) 使用了 HTML range input，預設樣式和事件綁定可能衝突
3. 播放按鈕狀態未正確反映 `audioEl.paused` 狀態

#### 3.2.2 修復方案

**播放器狀態機：**

```
[初始化]
    │
    ▼
[載入中] ← audioEl.src = /v1/tasks/{id}/audio
    │
    ▼
[已載入/停止] ──點擊 ▶──→ [播放中] ──點擊 ⏸──→ [暫停]
    ▲                      │                  │
    │                      │ 音頻結束          │
    └──────────────←───────┘                  │
    │                                         │
    └───────────────←──── 點擊 ⏹ ────────────┘
```

**UI 元件 (audio-bar 區域)：**

```
┌─────────────────────────────────────────────────────────────────┐
│ [⏮] [▶/⏸] [⏹]    ════●═══════════════════   00:23:45 / 01:23:45 │
│                      ↑ 自訂進度條 (非原生 range)                  │
│ [🔁 循環本段]  速度 [1.0x ▾]  [-5s] [+5s]  [🔊 ████░]          │
└─────────────────────────────────────────────────────────────────┘
```

**關鍵實作細節：**

| 問題 | 解決方案 |
|------|---------|
| 播放按鈕無響應 | 使用 `audioEl.play()` 的 Promise 處理，catch autoplay 政策阻擋 |
| 進度條無法拖拉 | 改用自訂 div + mousedown/mousemove/mouseup 事件，不用原生 `<input type="range">` |
| 時間顯示更新 | `requestAnimationFrame` 驅動而非 `timeupdate`（精度更高） |
| 音檔載入失敗 | 顯示「音檔不可用」+ 重新載入按鈕 |
| 播放頭同步段落 | `timeupdate` → 遍歷 segments → 高亮當前段落 |

**自訂進度條實作：**

```html
<div class="custom-seekbar" id="seekbar">
  <div class="seekbar-track">          <!-- 灰色底條 -->
    <div class="seekbar-fill"></div>    <!-- 藍色已播放部分 -->
    <div class="seekbar-thumb"></div>   <!-- 圓形拖動頭 -->
  </div>
</div>
```

```javascript
// 拖拉邏輯
seekbar.addEventListener('mousedown', (e) => {
  if (e.target.closest('.seekbar-thumb')) {
    isDragging = true;
  } else {
    // 點擊跳轉
    const rect = seekbar.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    audioEl.currentTime = ratio * audioEl.duration;
  }
});
document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  const rect = seekbar.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  audioEl.currentTime = ratio * audioEl.duration;
  updateSeekbar(ratio);
});
document.addEventListener('mouseup', () => { isDragging = false; });
```

### 3.3 上傳確認對話框（解決問題 3）

#### 3.3.1 流程

```
1. 用戶拖入檔案 → drop-zone.drag-over 高亮
2. 放開 → 前端驗證格式 (白名單 .mp3/.wav/.m4a/.ogg/.flac/.aac)
3. 格式有效 → 彈出確認 modal（在 body append modal-overlay）
   格式無效 → toast 錯誤 + 紅色 drop-zone 邊框
4. Modal 顯示（見 1.3 節佈局）：
   - 檔名
   - 檔案大小（自動換算 KB/MB/GB）
   - 音檔時長（使用 AudioContext 或 FileReader → pydub 後端計算）
   - 格式
   - 處理選項（沿用現有 diar-options）
   - [取消] [開始轉寫] 按鈕
5. 用戶確認 → POST /v1/transcribe (multipart) → 跳轉處理中頁面
6. 用戶取消 → 回到上傳頁面，清除暫存
```

#### 3.3.2 前端時長獲取方式

```javascript
// 方案 A：使用 Web Audio API (前端)
function getAudioDuration(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const audio = new Audio(url);
    audio.addEventListener('loadedmetadata', () => {
      resolve(audio.duration);
      URL.revokeObjectURL(url);
    });
    audio.addEventListener('error', reject);
  });
}

// 方案 B：先上傳再獲取（後端計算，前端等回應）
// 不建議，破壞 UX。用方案 A。
```

#### 3.3.3 檔案大小格式化

```javascript
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}
```

### 3.4 工具列 UI 規格（強化）

#### 3.4.1 按鈕佈局

```
[📂 新建項目] | 檔名顯示 | 時長 | 空白 | [🔁 翻譯] [🤖 AI報告] [📥 匯出 ▼] [✂ 切割]
```

| 按鈕 | 位置 | 行為 | 狀態 |
|------|------|------|------|
| 📂 新建項目 | 最左 | 確認對話框「清除當前項目？」→ 清理 cache + 回到上傳頁 | 正常/禁用 |
| 🔁 翻譯 | 右區 | 觸發整篇翻譯 | 三態：未翻譯/翻譯中/重新翻譯 |
| 🤖 AI 報告 | 右區 | 開啟 AI 報告 modal | 僅結果檢視時可用 |
| 📥 匯出 ▼ | 右區 | dropdown: TXT / DOCX | 僅有結果時可用 |
| ✂ 切割 | 最右 | 進入/退出切割模式 | toggle 按鈕，active 時高亮 |
| [下一步] | 視情況出現 | 開始批量 STT | 僅在切割完成或初始結果檢視時 |

#### 3.4.2 「新建項目」確認對話框

```
┌─────────────────────────────────┐
│          📂 新建項目              │
│                                  │
│  當前項目的所有資料將會被清除：     │
│  · 轉寫結果                      │
│  · 切割標註                      │
│  · 人名編輯                      │
│  · 書面語翻譯                    │
│                                  │
│      [取消]     [確定新建]         │
└─────────────────────────────────┘
```

---

## 4. 切割功能 UI 細節（解決問題 4）

### 4.1 切割模式入口與退出

| 操作 | 行為 |
|------|------|
| 點擊 `[✂ 切割]` | 進入切割模式，按鈕高亮（active），波形出現切割 UI |
| 再次點擊 `[✂ 切割]` | 退出切割模式，保留已標記的切割點（可恢復） |
| 點擊 `[✓ 確認切割]` | 正式執行切割，後端分割音檔 + 更新 segments |
| 點擊 `[✕ 取消切割]` | 清除所有切割標註，回到一般模式 |

### 4.2 切割點標註方式

```
切割模式下，波形區域變為：

┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ▄▃▂▁▁▂▃▄▅▆▇██▇▆▅▄▃▂▁│▁▂▃▄▅▆▇██│█▇▆▅▄▃▂▁▁▂▃▄▅▆▇│██▇▆▅▄▃▂▁   │
│                      ╳       ╳              ╳                  │
│                      切割點 A  切割點 B       切割點 C            │
│                      ═══      ═══            ═══               │
│                      上一步                      下一步          │
│                                                                  │
|  [撤銷最後切割點] [清除全部]              [✕ 取消切割] [✓ 確認切割] |
└─────────────────────────────────────────────────────────────────┘
```

**新增切割點的方式：**

| 方式 | 說明 |
|------|------|
| 點擊波形 | 在滑鼠點擊位置新增切割點 |
| 點擊段落時間戳 | 在該段落開始位置新增切割點 |
| 從段落列表右鍵選單 | 右鍵段落 →「在此處切割」 |

**切割點視覺：**

| 元素 | 樣式 |
|------|------|
| 切割線 | 紅色虛線 (2px, `#DC2626`, `dashed`) |
| 切割點標籤 | 圓形圖標 + 字母 A/B/C/D... |
| 拖動手柄 | 豎線兩端的小圓點，hover 時顯示 |
| 切割預覽 | 切割點之間的區域以淺色交替背景標示 |
| 當前拖動的切割點 | 高亮（紅色實線 + 放大標籤）|

### 4.3 拖動調整切割點

```
切割點 A 的拖動：

  滑鼠 hover 切割線 → 游標變為 col-resize
  mousedown → 開始拖動模式
    ↓
  左側? → 游標變為 ew-resize，移動時即時更新切割線位置
  右側? → 同上
    ↓
  mouseup → 鎖定新位置

邊界限制：
  - 不能小於前一切割點 + 1 秒
  - 不能大於後一切割點 - 1 秒
  - 不能小於 0
  - 不能大於音檔總時長
```

### 4.4 確認切割邏輯

```
用戶點擊 [✓ 確認切割]：

1. 前端收集所有切割時間點（秒，精確到小數點後 1 位）
2. 顯示最終確認對話框：

  ┌─────────────────────────────────────┐
  │       ✂ 確認音檔切割                  │
  │                                       │
  │  將切割為 4 段：                       │
  │                                       │
  │  段 1: 00:00:00 ~ 00:12:35 (12:35)   │
  │  段 2: 00:12:35 ~ 00:28:10 (15:35)   │
  │  段 3: 00:28:10 ~ 00:45:00 (16:50)   │
  │  段 4: 00:45:00 ~ 01:23:45 (38:45)   │
  │                                       │
  │  原始音檔將保留不變。                   │
  │                                       │
  │  [上一步]       [確認切割]              │
  └─────────────────────────────────────┘

3. 前端調用後端 API：

POST /v1/tasks/{task_id}/split
Body: { "cut_points": [755.0, 1690.0, 2700.0] }
Response: {
  "success": true,
  "segments": [
    { "id": 0, "start": 0, "end": 755.0, "path": ".../seg_0.wav" },
    { "id": 1, "start": 755.0, "end": 1690.0, "path": ".../seg_1.wav" },
    ...
  ]
}

4. 後端執行實際切割（audio_processor.py 新增 split_audio_by_points 函數）

5. 更新 task 結構：將原始 1 個 segment 改為 N 個 segment
   - 每個新 segment 保留原 speaker 標記（如果該段落在原有轉寫範圍內）
   - 清除原有 STT 文字（因為切割後需要重新 STT）
   - 標記狀態為 "awaiting_stt"

6. 前端更新：波形上顯示切割後的段落邊界
   - 波形分成不同顏色區塊
   - 每個區塊下方標示段號 (1/4, 2/4, 3/4, 4/4)
```

### 4.5 切割後資料結構變化

```
切割前:
  task.result.segments = [
    { id: 0, start: 0, end: 5025.3, text: "整段轉寫...", speaker: "人物 #1", ... }
  ]

切割後 (4 段, 文字清空):
  task.result.segments = [
    { id: 0, start: 0, end: 755.0, text: "[待 STT]", stt_status: "pending",
      segment_path: "tasks/upload_xxx/seg_0.wav" },
    { id: 1, start: 755.0, end: 1690.0, text: "[待 STT]", stt_status: "pending",
      segment_path: "tasks/upload_xxx/seg_1.wav" },
    { id: 2, start: 1690.0, end: 2700.0, text: "[待 STT]", stt_status: "pending",
      segment_path: "tasks/upload_xxx/seg_2.wav" },
    { id: 3, start: 2700.0, end: 5025.3, text: "[待 STT]", stt_status: "pending",
      segment_path: "tasks/upload_xxx/seg_3.wav" },
  ]

stt_status 枚舉: "pending" | "processing" | "completed" | "failed"
```

---

## 5. Cache 機制說明（解決問題 5）

### 5.1 核心原則

> 所有資料以 `tasks/` 目錄下的 JSON 檔案為真實來源（source of truth）。  
> 應用重啟時自動載入最新的 task，直到用戶明確點擊「新建項目」。

### 5.2 存什麼（Cache 內容）

| 資料 | 存儲位置 | 格式 | 何時寫入 |
|------|---------|------|---------|
| 任務狀態 + 結果 | `tasks/{task_id}.json` | JSON | 每次狀態變更、每段 STT 完成、每次編輯 |
| 上傳原始音檔 | `tasks/upload_{task_id}/original.*` | 原始格式 | 上傳時 |
| 轉換後 WAV | `tasks/upload_{task_id}/original_16k.wav` | 16kHz mono WAV | 首次轉換 |
| 切割後音檔 | `tasks/upload_{task_id}/seg_{N}.wav` | 16kHz mono WAV | 切割確認時 |
| 波形峰值 | `tasks/upload_{task_id}/waveform.json` | JSON | 首次請求時計算後快取 |
| 應用層狀態 | `tasks/_last_task.txt` | 純文字 (僅 task_id) | 每次 task 更新時 |

### 5.3 何時存（寫入時機）

```
每次寫入都同步保存到 tasks/{task_id}.json：

1. 任務狀態變更 (pending → processing → completed / failed)
2. 進度更新 (每 10% 或每段 STT 完成)
3. 切割完成
4. 批量 STT 每完成一段
5. 單段重新 STT 完成
6. 人名編輯
7. 書面語翻譯完成
8. 每次編輯觸發後 debounce 1 秒寫入
```

### 5.4 何時清理

| 觸發條件 | 清理內容 | 行為 |
|---------|---------|------|
| 用戶點擊「新建項目」→ 確認 | 整個 task json + upload dir + 切割音檔 | 刪除檔案，回到上傳頁 |
| 用戶關閉應用再開啟 | 不清理，自動載入 | 讀取 `_last_task.txt` → 載入最新 task |
| 應用崩潰後重啟 | 不清理，自動載入 | 同上，JSON 檔案仍是完整的 |
| 超過 7 天的任務 | 可選清理（P2 功能） | 啟動時檢查，提示用戶清理 |

### 5.5 重啟恢復流程

```
應用啟動
  │
  ▼
檢查 tasks/_last_task.txt
  │
  ├── 不存在 → 上傳頁面
  │
  └── 存在 → 讀取 tasks/{task_id}.json
       │
       ├── 檔案不存在/損壞 → 上傳頁面 + toast "上次任務已遺失"
       │
       └── 有效 → 根據 status 決定：
            │
            ├── "pending" / "processing" → 進入處理中頁面 + 重新開始輪詢
            │     (後端任務可能因重啟而中斷，需要重新提交或標記為 failed)
            │
            ├── "completed" → 進入 workspace，恢復所有資料
            │     (segments、speaker_map、編輯歷史完全恢復)
            │
            ├── "failed" → 顯示錯誤，提供 [重試] 或 [新建項目]
            │
            └── 包含 "segments" 且部分 stt_status="pending" →
                 進入 workspace，顯示哪些段落尚未 STT，繼續批量處理
```

### 5.6 `_last_task.txt` 更新邏輯

```python
# 每次 task 寫入時一併更新
def _update_last_task(task_id: str):
    last_task_path = settings.tasks_path / "_last_task.txt"
    last_task_path.write_text(task_id, encoding="utf-8")

# 在 task_store.save() 內部自動調用
```

### 5.7 前端 localStorage 輔助快取

除了後端 JSON，前端也保留以下快取：

```javascript
// localStorage keys
const CACHE_KEYS = {
  LAST_TASK_ID: 'canto_last_task_id',
  UI_STATE: 'canto_ui_state',       // 摺疊狀態、scroll 位置、檢視模式
  AUDIO_CURRENT_TIME: 'canto_audio_time',  // 最後播放位置（用於恢復）
};

// 寫入時機
// - navigate() 時保存
// - 離開頁面 (beforeunload) 時保存
// - 每 30 秒自動保存

// 恢復
// - 應用啟動時讀取 LAST_TASK_ID → 載入對應 task
// - 恢復 UI_STATE (折疊面板、scroll 位置)
// - 恢復 AUDIO_CURRENT_TIME (可選：跳到上次聽的位置)
```

### 5.8 崩潰容忍設計

```
情境：批量 STT 時軟件崩潰

確保：已完成的段落永不丟失。

實作：每段 STT 完成後立即寫入 task.json（同步寫入，非 debounce）。

崩潰後重啟 → 讀取 task.json → 發現部分段落 stt_status="completed"
                          → 部分段落 stt_status="pending"
                          → 顯示：
                            「已恢復上次工作。已完成 3/5 段，是否繼續處理剩餘 2 段？」
                            [從頭開始] [繼續]
```

---

## 6. 批量 STT 的進度與錯誤處理（解決問題 6）

### 6.1 流程設計

```
用戶在 Workspace（不論是否切割過）
        │
        ▼
點擊 [下一步：批量 STT]
        │
        ▼
┌─────────────────────────────────────────┐
│         批量 STT 開始                     │
│                                          │
│  將處理 5 段音頻                          │
│                                          │
│  ☐ 段 1/5 (00:00 ~ 12:35)   ⏳ 處理中   │
│  ☑ 段 2/5 (12:35 ~ 28:10)   ✅ 完成     │
│  ☑ 段 3/5 (28:10 ~ 45:00)   ✅ 完成     │
│  ☐ 段 4/5 (45:00 ~ 01:00:00) ⏳ 等待中  │
│  ☐ 段 5/5 (01:00:00 ~ 01:23:45) 等待中  │
│                                          │
│  整體進度: ████████░░░░ 40%              │
│                                          │
│  [暫停] [取消]                            │
└─────────────────────────────────────────┘
        │
        ▼
全部完成後自動切換到結果檢視（或點擊 [檢視結果]）
```

### 6.2 逐段處理 — 做一段存一段

```javascript
// 批量 STT 核心邏輯（前端）
async function batchStt(segments) {
  const total = segments.length;

  for (let i = 0; i < total; i++) {
    const seg = segments[i];

    // 跳過已經完成的
    if (seg.stt_status === 'completed' && seg.text && seg.text !== '[待 STT]') {
      updateProgress(i, total, 'skipped');
      continue;
    }

    // 更新狀態為 processing
    updateSegmentStatus(i, 'processing');
    saveTaskState();  // 立即寫入

    try {
      // 調用後端 STT（同步等待）
      // 注意：這裡需要一個同步 API 或非同步輪詢
      // 方案：後端提供 POST /v1/tasks/{task_id}/stt-segment
      //       接收一個 segment_id，返回轉寫結果

      const result = await api('POST', `/v1/tasks/${taskId}/stt-segment`, {
        segment_id: seg.id
      });

      // 更新段落文字
      segments[i].text = result.text;
      segments[i].speaker = result.speaker;  // 可選
      segments[i].stt_status = 'completed';

      // 立即寫入 task.json
      saveTaskState();

      updateProgress(i + 1, total, 'completed');

    } catch (err) {
      // 單段失敗，不影響其他段
      segments[i].stt_status = 'failed';
      segments[i].error = err.message;
      saveTaskState();
      updateProgress(i, total, 'failed');
      // 繼續下一段，或暫停等待用戶決定
    }
  }

  // 全部完成
  showCompletionSummary();
}
```

### 6.3 後端新增 API

```python
@app.post("/v1/tasks/{task_id}/stt-segment")
async def stt_segment(task_id: str, body: dict):
    """
    對指定 segment 執行 STT（用於批量逐段處理）
    Body: { "segment_id": 3 }
    """
    task = task_store.load(task_id)
    # ... 驗證 ...

    segment = next(s for s in task["result"]["segments"] if s["id"] == segment_id)
    seg_path = segment.get("segment_path") or task["_wav_path"]

    # 如果是切割後的段落，提取對應時間範圍
    if segment.get("segment_path") and Path(segment["segment_path"]).exists():
        # 直接使用已切割的獨立音檔
        audio_path = Path(segment["segment_path"])
    else:
        # 從原始音檔提取時間段
        audio_seg = extract_segment(Path(task["_wav_path"]), segment["start"], segment["end"])
        audio_path = save_audio_temp(audio_seg)

    # 執行 STT
    result = transcribe_audio(audio_path)

    # 更新段落
    text = result["segments"][0]["text"] if result["segments"] else ""
    segment["text"] = text
    segment["stt_status"] = "completed"
    segment["retranscribe_count"] = segment.get("retranscribe_count", 0) + 1

    # 保存
    task["updated_at"] = datetime.now().isoformat()
    task_store.save(task)
    _update_last_task(task["task_id"])

    return {"success": True, "text": text, "segment_id": segment_id}
```

### 6.4 用戶手動添加時間段

用戶可以在結果檢視中手動添加新的時間段：

```
位置：段落列表底部

[＋ 添加時間段]
│
▼
彈出對話框：

┌─────────────────────────────────┐
│      添加手動時間段                │
│                                  │
│  開始時間: [00:45:00 ▸]          │
│  結束時間: [00:48:30 ▸]          │
│                                  │
│  (可拖動波形上的範圍選擇器)        │
│                                  │
│  [取消]  [添加並 STT]             │
└─────────────────────────────────┘

添加後：
  - 新 segment 插入列表（按時間排序）
  - 自動觸發該段的 STT
  - 完成後插入對應位置
```

### 6.5 手動重新 STT 特定時間段

```
情境：用戶發現某段轉寫不準，想重新處理

操作方式 1：段落列表
  - 選取一個或多個段落（勾選框 / Ctrl+點擊）
  - 點擊出現的 [🔄 重新識別] 按鈕
  - (可選) 開啟 [🔊降噪] / [📢提音量]
  - 確認 → 後端提取音頻 → 重新 STT → 更新段落

操作方式 2：波形
  - 在波形上拖拽選擇範圍（shift+拖動）
  - 放開後彈出選單：
    [▶ 播放此範圍] [✂ 在此切割] [🔄 STT 此範圍]

重新 STT 的狀態管理：
  - 處理中 → 段落顯示 spinner
  - 完成 → 更新文字，清除 spinner
  - 失敗 → 段落右側出現紅色 ❌ + [重試]
```

### 6.6 進度 UI 規格

**批量 STT 專用進度頁（modal 或全頁）：**

```
┌──────────────────────────────────────────────────┐
│  🔄 STT 處理中 (5 段)                             │
│                                                   │
│  整體進度: ████████░░░░░░░░ 40%                   │
│                                                   │
│  段 1/5 [✅]  00:00 - 12:35  陳大明               │
│  段 2/5 [✅]  12:35 - 28:10  李小華               │
│  段 3/5 [⏳]  28:10 - 45:00  陳大明  ← 正在處理   │
│  段 4/5 [⏳]  45:00 - 60:00  王經理               │
│  段 5/5 [⏳]  60:00 - 83:45  討論環節             │
│                                                   │
│  當前段進度: ████████░░░░ 65%                     │
│  剩餘時間: 約 3 分鐘                              │
│                                                   │
│  [⏸ 暫停]  [✕ 取消 (保留已完成的)]                │
└──────────────────────────────────────────────────┘
```

### 6.7 錯誤處理策略

| 錯誤類型 | 系統行為 | UI 表現 |
|---------|---------|--------|
| 單段 STT 失敗 | 跳過該段，繼續下一段 | 該段標記紅色 ❌ + [重試] 按鈕 |
| 音檔片段遺失 | 無法提取音頻 | 該段標記 ⚠ 音檔不可用 |
| 網路錯誤（如果使用 API） | 重試 3 次，每次間隔 2 秒 | 顯示「重試中...」 |
| 硬碟空間不足 | 停止處理 | 全頁紅色錯誤提示 |
| 模型載入失敗 | 停止全部處理 | 顯示錯誤原因 + 回到 workspace |

**批量處理完成後的總結：**

```
┌──────────────────────────────────────────────────┐
│      批量 STT 完成                                │
│                                                   │
│  ✅ 成功: 4 段                                    │
│  ❌ 失敗: 1 段 (段 4: 音檔過短)                   │
│                                                   │
│  [重試失敗段落]  [跳過並檢視結果]                    │
└──────────────────────────────────────────────────┘
```

### 6.8 增量保存確保不丟失

```python
# 在 task_store.save() 內部
def save(self, task: dict):
    """原子化寫入，確保不損壞"""
    path = self._task_path(task["task_id"])
    temp_path = path.with_suffix(".tmp")

    # 先寫入暫存檔
    temp_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_path.flush()  # 強制寫入磁碟 (Python >= 3.10 可用 os.fsync)

    # 再 rename（原子操作）
    temp_path.rename(path)

    # 更新最後任務標記
    _update_last_task(task["task_id"])
```

### 6.9 手動添加時間段的後端驗證

```python
@app.post("/v1/tasks/{task_id}/segments")
async def add_segment(task_id: str, body: dict):
    """手動添加時間段"""
    task = task_store.load(task_id)
    # ... 驗證 ...

    start = body.get("start")
    end = body.get("end")

    # 驗證時間範圍
    if start < 0 or end > task["audio_duration_sec"]:
        raise HTTPException(400, "時間超出音檔範圍")
    if end - start < 0.5:
        raise HTTPException(400, "時間段過短（最少 0.5 秒）")

    # 檢查是否與現有 segment 重疊
    for seg in task["result"]["segments"]:
        if seg["stt_status"] != "deleted" and not (end <= seg["start"] or start >= seg["end"]):
            # 重疊
            raise HTTPException(400, f"與段落 #{seg['id']} ({seg['start']:.1f}-{seg['end']:.1f}) 重疊")

    # 建立新 segment
    new_id = max((s["id"] for s in task["result"]["segments"]), default=-1) + 1
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

    # 插入並保持排序
    task["result"]["segments"].append(new_seg)
    task["result"]["segments"].sort(key=lambda s: s["start"])

    # 重新分配 ID
    for i, s in enumerate(task["result"]["segments"]):
        s["id"] = i

    task_store.save(task)
    return {"success": True, "segment": new_seg}
```

---

## 附錄 A：修改檔案清單

實作上述設計需要修改/新增的檔案：

| 檔案 | 修改類型 | 說明 |
|------|---------|------|
| `frontend/index.html` | 大幅修改 | 新增波形 Canvas、切割 UI、確認對話框、批量 STT 進度、播放器重構、cache 恢復邏輯 |
| `app/api_server.py` | 新增端點 | `/v1/tasks/{id}/waveform`, `/v1/tasks/{id}/split`, `/v1/tasks/{id}/stt-segment`, `/v1/tasks/{id}/segments` (POST) |
| `app/audio_processor.py` | 新增函數 | `compute_waveform_peaks()`, `split_audio_by_points()`, `extract_segment_by_id()` |
| `app/config.py` | 無修改 | 現有配置足夠 |

---

## 附錄 B：開發優先序建議

| 優先級 | 功能 | 預估難度 | 依賴 |
|--------|------|---------|------|
| P0 | 播放器修復（問題 2）+ 時間線修正（問題 1 基礎） | 低-medium | 無 |
| P0 | 上傳確認對話框（問題 3） | 低 | 無 |
| P0 | Cache 機制（問題 5） | 低 | TaskStore 已有基礎 |
| P1 | 批量 STT 逐段處理 + 增量保存（問題 6） | medium | 需要後端新端點 |
| P1 | 波形顯示（問題 1 進階） | medium-hard | 後端 waveform API |
| P2 | 切割功能（問題 4） | hard | 波形完成 + split API |
| P2 | 手動添加/重新 STT 時間段（問題 6 進階） | medium | 切割完成後 |
