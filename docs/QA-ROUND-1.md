# QA 第一輪審查報告：CantoTranscriber

**審查日期：** 2026-06-11  
**審查範圍：** 前端 index.html / 後端 11 個 Python 模組  
**審查方式：** 程式碼閱讀 + 邏輯推理追蹤所有分支  

---

## 發現摘要

| 等級 | 數量 | 說明 |
|------|------|------|
| P0 阻塞 | 2 | 流程中斷或崩潰 |
| P1 功能缺陷 | 5 | 功能不完整或行為錯誤 |
| P2 體驗問題 | 6 | UI 不一致、提示不明確 |
| 建議改進 | 5 | 非必要但值得做 |

---

## P0 阻塞問題

### P0-1：匯出功能完全損壞（Export 按鈕點了沒反應）

**位置：** `frontend/index.html` → `doExport()` 與 `openExportModal()`

**問題：**
前端 `api()` 函數對非 JSON 回應直接回傳 `Response` 物件（而非 `Blob`），而 `doExport()` 和 `openExportModal()` 將這個 `Response` 物件直接傳給 `URL.createObjectURL()`，這會拋出 `TypeError`（`createObjectURL` 接收的必須是 `Blob` 或 `File`，不能是 `Response`）。

```javascript
// api() returns `res` (a Response object) for non-JSON responses
const blob = await api('POST', `/tasks/${S.taskId}/export`, { format: fmt, ... });
const url = URL.createObjectURL(blob);  // TypeError here
```

**影響路徑：**
- 工具列 → 匯出 → TXT（直接崩潰）
- 工具列 → 匯出 → DOCX → 任何選項 → 匯出下載（直接崩潰）

**修復方向：** 改為 `const res = await api(...); const blob = await res.blob();`

---

### P0-2：Workspace 渲染時模板字串語法錯誤（JS 執行期錯誤）

**位置：** `frontend/index.html`，`renderWorkspace()` 中的 `btn-batch-stt` 行

**問題：**
`style` 屬性的模板插值包含了無效的 JavaScript 表達式：

```html
<button id="btn-batch-stt" class="primary"
  style="${allSttDone()?'display:none':'';font-size:14px;padding:8px 20px;}">
```

`${}` 內的 `font-size:14px;padding:8px 20px;` 不是合法的 JavaScript 表達式：
- `font-size` 被解析為 `font - size`（變數減法），兩個變數皆未定義，回傳 `NaN`
- `NaN:14px` 嘗試創建標籤，且 `14px` 不是合法表達式

當 `allSttDone()` 回傳 `false` 時，模板插值結果為 `;NaN:14px;padding:8px 20px;` → **執行期錯誤**，`innerHTML` 賦值中斷，整個 Workspace 頁面空白。

**條件：** 只要進入 Workspace 頁面就會觸發，無論是否有已完成的 STT 段落。

**修復方向：** 將 CSS 拆出插值範圍：
```html
style="display:${allSttDone()?'none':''};font-size:14px;padding:8px 20px"
```

或改用內聯樣式 + className 切換：
```html
class="primary ${allSttDone()?'hidden':''}"
```

---

## P1 功能缺陷

### P1-1：批次 STT 完全缺乏說話人分離

**位置：** `app/api_server.py` → `stt_segment()` 端點

**問題：**
`_process_transcription()`（自動 STT 背景任務）包含完整的處理鏈：切割 → STT → **diarization** → 合併同說話人 → speaker_map。但批次 STT 調用的 `stt_segment()` 端點完全跳過了說話人分離：

```python
# stt_segment() 中的 speaker 賦值：
target["speaker"] = target.get("speaker", "") or f"人物 #{segment_id}"
```

這只是根據 segment ID 隨便分配一個標籤，沒有任何語音分析。這意味著所有透過「批量 STT」流程處理的結果，**說話人欄位都是假的**。

**影響：** 整個批量 STT 流程（目前前端唯一使用的路線）無法正確識別說話人。

**對比：** `POST /v1/transcribe` 端點有 diarization，但前端從未使用這個端點（它總是調用 `/v1/upload`）。

---

### P1-2：波形點擊事件雙重觸發

**位置：** `frontend/index.html` → `initZoomControls()`

**問題：**
`initZoomControls()` 為 `waveform-canvas` 和 `waveform-area` 各註冊了一個 `click` 事件監聽器，兩個都會呼叫 `onWaveformClick()`：

```javascript
// 監聽器 1：直接綁在 canvas 上
document.getElementById('waveform-canvas')?.addEventListener('click', onWaveformClick);

// 監聽器 2：綁在 area 上，但 event.target 包含 canvas
document.getElementById('waveform-area')?.addEventListener('click', (e) => {
  if (e.target.id === 'waveform-area' || e.target.id === 'waveform-canvas') {
    onWaveformClick(e);
  }
});
```

點擊 Canvas 時，事件從 canvas 冒泡到 area，兩個監聽器都被觸發。切割模式下會添加兩個切割點（間距 < 1ms），普通模式下 seek 會被調兩次。

---

### P1-3：前端完全未使用 `POST /v1/transcribe` 端點

**位置：** `frontend/index.html` → `confirmUpload()`

**問題：**
前端上傳時始終調用 `POST /v1/upload`（`no_stt=true`），從未使用 `POST /v1/transcribe`。這代表：

1. 自動音檔切割（`split_audio()` — 超過 10 分鐘的自動分段）在前端流程中從未觸發
2. 完整 diarization + speaker merging 鏈只存在於背景任務中，但背景任務只綁在無人使用的 `/transcribe` 端點
3. 用戶必須手動切割或使用「自動分段（每 10 分鐘）」按鈕，然後逐段（或批量）呼叫 STT

**影響：**
- 單一大檔案上傳後，如果用戶直接點「批量 STT」，整個大檔案送進 faster-whisper，沒有切割步驟，可能導致 OOM
- 說話人分離在所有正常使用路徑上失效（同 P1-1）

---

### P1-4：`retranscribe` 段落分配邏輯粗糙

**位置：** `app/api_server.py` → `retranscribe()`

**問題：**
當 STT 回傳的新段落數量不等於原始選取段落數量時，分配邏輯僅按時間比例映射：

```python
nseg_mid = (nseg["start"] + nseg["end"]) / 2
ratio = nseg_mid / (new_segs[-1]["end"] or 0.001)
orig_idx = min(int(ratio * original_count), original_count - 1)
selected[orig_idx]["text"] = nseg["text"]
```

這會導致：
- 多個新段落映射到同一個原始段落（後一個覆蓋前一個的文字）
- 部分原始段落永遠得不到更新（被跳過）
- `speaker`、`audio_processing` 等欄位只對「最後映射到的段落」有效

**邊界情況：** 當 `new_segs[-1]["end"]` 為 0 時，使用 0.001 作為分母，ratio 極大，`orig_idx` 永遠是 `original_count - 1`，所有新段落都填到最後一個原始段落。

---

### P1-5：`_process_transcription` 中 speaker_map 排序可能崩潰

**位置：** `app/api_server.py` → `_process_transcription()`

**問題：**
speaker_map 排序 key 為：
```python
key=lambda x: int(x[0].replace("人物 #", ""))
```

這假設所有 speaker_id 都是「人物 #N」格式。但如果 pyannote diarization 產生非標準格式的 ID（如 `SPEAKER_00`），或者 `assign_speakers_to_stt_segments` 因為某些原因保留了原始 ID，`int("SPEAKER_00")` 會拋出 `ValueError`，**整個背景轉寫任務崩潰**。

實際上 `_diarize_pyannote` 有自己的映射確保輸出 `"人物 #N"` 格式，但這層防護在異常情況下可能失效。

---

## P2 體驗問題

### P2-1：書面語翻譯無載入狀態

**位置：** `frontend/index.html` → `wireToolbar()` → 翻譯按鈕

**問題：**
點擊「書面語翻譯」後，按鈕沒有任何 loading 指示。對於大型會議錄音（數百個 segments），BART 模型翻譯可能需要 10~30 秒，用戶無法知道系統是否仍在運作。按鈕也沒有被 disabled，用戶可能重複點擊發送多個請求。

**對比：** AI 報告功能有完善的 loading spinner（生成中狀態），翻譯沒有。

---

### P2-2：音檔載入失敗無使用者回饋

**位置：** `frontend/index.html` → `setupAudio()`

**問題：**
`S.audioEl` 只註冊了 `timeupdate`、`loadedmetadata`、`ended` 事件，沒有註冊 `error` 事件處理器。當：

- 後端音檔檔案遺失（返回 404）
- 格式瀏覽器不支援
- 網路中斷

使用者點播放按鈕時沒有任何錯誤提示，只會靜默失敗。

---

### P2-3：重新識別後選取未清除

**位置：** `frontend/index.html` → `reSttSelected()`

**問題：**
執行重新 STT 後，`S.selected` 沒有被清除，選取框仍然是勾選狀態。用戶可能在無意間對同一段落再次點擊「重新識別」，造成不必要的重複 API 呼叫。

```javascript
async function reSttSelected() {
  const ids = Array.from(S.selected);
  // ... 處理完畢後沒有 S.selected.clear()
  renderSegments();
  renderSpeakers();
}
```

---

### P2-4：批次 STT 每段完成後額外 reload 整個任務

**位置：** `frontend/index.html` → `runBatchStt()`

**問題：**
每完成一個 segment 的 STT，就重新請求一次 `GET /v1/tasks/{task_id}`：

```javascript
try {
  const task = await api('GET', `/tasks/${S.taskId}`);
  S.spkMap = task.result?.speaker_map || {};
} catch {}
```

如果有 50 個段落，就需要額外 50 次 API 查詢。可以改為累積更新 `S.spkMap` 而非每次 reload。這在大檔案時會顯著影響批次 STT 的整體速度。

---

### P2-5：文件匯出時 speaker 名稱可能未正確應用

**位置：** `app/api_server.py` → `export()` 端點

**問題：**
匯出端點從 `task["result"]["speaker_map"]` 重建 `SpeakerRegistry`，但遍歷 speaker_map 時只檢查 `info.get("name")`：

```python
registry = SpeakerRegistry()
for sid, info in speaker_map.items():
    if info.get("name"):
        registry.set_name(sid, info["name"])
```

但 `SpeakerRegistry.__init__()` 需要透過 `speaker_counts` 參數初始化 `_map`，否則所有 `get_name()` 呼叫都會回傳原始 speaker_id。由於 `export()` 建立的是空 registry，`registry.set_name()` 永遠回傳 `False`（`speaker_id not in self._map`）。**實際上用戶設定的 speaker name 完全沒有被應用到匯出文件。**

---

### P2-6：切割模式切換時事件監聽器重複註冊

**位置：** `frontend/index.html` → `toggleCutMode()`

**問題：**
每次進入切割模式，`toggleCutMode()` 都會為 `btn-cancel-cut` 和 `btn-confirm-cut` 註冊新的事件監聽器。雖然因為 DOM 重建（via `renderWorkspace()`）不會導致記憶體洩漏，但如果多次切換切割模式而不重新渲染頁面（例如透過其他操作觸發），監聽器會疊加。

實際上 `renderWorkspace()` 每次都會重建 DOM，所以問題不大，但值得注意的程式碼風格問題。

---

## 建議改進

### S-1：`stt-segment` 端點加入可選的說話人分離

批次 STT 的 `stt_segment()` 端點可以接受一個 `run_diarization` 參數（預設 `false` 保持向後相容），當為 `true` 時對該段落執行 VAD 說話人分離。這可以讓批次流程也獲得說話人標籤。

### S-2：上傳階段加入檔案格式魔術字節檢查

當前 `validate_audio_file()` 只檢查副檔名和 pydub 能否讀取。惡意檔案（如 `.mp3` 偽裝的 `.exe`）可以通過檢查。可以加入檔案魔術字節（magic bytes）檢查增強安全性。

### S-3：API 端點參數驗證（Pydantic model）

當前多個端點使用 `body: dict` 作為參數類型（如 `retranscribe`、`translate`、`add_segment`），沒有 schema 驗證。改用 Pydantic `BaseModel` 可以自動驗證必填欄位、類型、範圍。

### S-4：匯出時顯示下載進度

大型會議文件的 DOCX 匯出（特別是包含完整翻譯的）可能需要數秒。可以考慮加入下載進度提示或生成中的狀態。

### S-5：task JSON 檔案讀取加入防損壞保護

`TaskStore.load()` 直接執行 `json.loads()`，如果 JSON 檔案因異常關機而損壞（例如寫入一半時斷電），會拋出 `json.JSONDecodeError` 導致 500。可以加入 try/except，返回 `None`（等同任務不存在）或自動嘗試修復。

---

## API 端點清單總檢

| # | 端點 | 方法 | 參數驗證 | 500 風險 | 備註 |
|---|------|------|----------|----------|------|
| 1 | `/v1/health` | GET | N/A | 低 | |
| 2 | `/v1/transcribe` | POST | Form (FastAPI) | 中 | ffmpeg 檢查可能 false negative |
| 3 | `/v1/upload` | POST | Form (FastAPI) | 中 | 同上 |
| 4 | `/v1/tasks/{task_id}` | GET | 路徑參數 | 中 | corrupted JSON → 500 |
| 5 | `/v1/tasks/{task_id}` | DELETE | 路徑參數 | 中 | 同 4 |
| 6 | `/v1/last-task` | GET | N/A | 中 | 同 4 |
| 7 | `/v1/tasks` | GET | N/A | 低 | 有 try/except |
| 8 | `/v1/tasks/{task_id}/translate` | POST | body: dict | 低 | translate_segments_builtin 有保護 |
| 9 | `/v1/tasks/{task_id}/speakers` | PUT | body: dict | 低 | 遍歷無檢查 |
| 10 | `/v1/tasks/{task_id}/retranscribe` | POST | body: dict | 中 | 段落分配邊界情況 |
| 11 | `/v1/tasks/{task_id}/export` | POST | body: dict | 中 | export_docx 可能拋出 |
| 12 | `/v1/tasks/{task_id}/report` | POST | body: dict | 低 | 有 try/except |
| 13 | `/v1/tasks/{task_id}/audio` | GET | 路徑參數 | 低 | |
| 14 | `/v1/tasks/{task_id}/waveform` | GET | Query params | 低 | |
| 15 | `/v1/tasks/{task_id}/split` | POST | body: dict | 中 | cut_points 邊界檢查 |
| 16 | `/v1/tasks/{task_id}/stt-segment` | POST | body: dict | 中 | 音檔不可用時拋出 |
| 17 | `/v1/tasks/{task_id}/stt-status` | GET | 路徑參數 | 低 | |
| 18 | `/v1/tasks/{task_id}/segments` | POST | body: dict | 中 | 重疊檢查 |
| 19 | `/` (Root) | GET | N/A | 低 | 靜態檔案 |

---

## 關鍵使用者流程測試結果

### 流程 1：上傳 → 確認 → Workspace → 切割 → 批量 STT → 翻譯 → 匯出

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 拖入音檔 | ✅ | |
| 顯示檔案資訊 | ✅ | |
| 確認上傳 | ✅ | |
| 顯示 Workspace | ❌ | **P0-2：JS 語法錯誤導致空白頁面** |
| 波形繪製 | ✅ | （假設 P0-2 修復後） |
| 切割模式 | ✅ | |
| 確認切割 | ✅ | |
| 批量 STT | ⚠️ | **P1-1：無說話人分離** |
| 書面語翻譯 | ✅ | （但無 loading 狀態） |
| 匯出 TXT/DOCX | ❌ | **P0-1：createObjectURL 錯誤** |

### 流程 2：崩潰恢復

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 重啟後檢查 last-task | ✅ | |
| 恢復提示 | ✅ | |
| 載入任務資料 | ✅ | |
| 繼續操作 | ✅ | 任務狀態正確保留 |

### 流程 3：邊界情況

| 情況 | 狀態 | 備註 |
|------|------|------|
| 空檔案 (0 bytes) | ✅ | validate_audio_file 拒絕 |
| 過短 (< 1 秒) | ✅ | 同上 |
| 過長 (> 10 小時) | ⚠️ | 檢查前需完整載入，可能 OOM |
| 不支援格式 | ✅ | |
| 無語音內容 | ⚠️ | check_for_speech 在 -60dB，極敏感 |
| 後端當機 | ⚠️ | 前端 toast 提示，無重試機制 |
| 音檔損壞 | ⚠️ | 初始驗證通過後在 convert_to_wav 才失敗 → 500 |
| JSON 檔案損壞 | ❌ | **S-5：500 崩潰** |

---

## 優先修復順序建議

1. **P0-2**（Workspace 空白）— 修最簡單，影響最大，無法進行任何操作
2. **P0-1**（匯出錯誤）— 次簡單，阻斷最終輸出
3. **P1-1**（批次 STT 無說話人分離）— 核心功能缺失
4. **P2-5**（匯出 speaker name 未生效）— 使用者設定遺失
5. **P1-2**（雙重點擊）— 體驗問題兼行為錯誤
6. 其餘依序處理

---

*報告結束。*
