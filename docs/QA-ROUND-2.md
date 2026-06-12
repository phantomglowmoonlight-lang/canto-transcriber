# QA 第二輪審查報告：CantoTranscriber

**審查日期：** 2026-06-11  
**審查範圍：** `frontend/index.html` / `app/api_server.py` / `app/speaker_registry.py` / `app/diarizer.py` / `app/exporter.py` / `app/text_processor.py` / `app/translator.py` / `app/audio_processor.py`  
**審查方式：** 程式碼閱讀 + 第一輪修復驗證 + 完整流程邏輯追蹤  

---

## 修復驗證

### P0-1 匯出損壞 → ✅ 已修復

`doExport()` 與 `openExportModal()` 現在都使用：
```javascript
const res = await api('POST', ...);
const blob = await res.blob();
const url = URL.createObjectURL(blob);
```
`api()` 對非 JSON 回應回傳原始 `Response` 物件，前端正確呼叫 `res.blob()` 後再傳給 `createObjectURL`。匯出流程可正常觸發下載。

---

### P0-2 Workspace 模板語法 → ✅ 已修復

`btn-batch-stt` 的 style 屬性從：
```html
style="${allSttDone()?'display:none':'';font-size:14px;padding:8px 20px;}"
```
改為：
```html
style="font-size:14px;padding:8px 20px;${allSttDone()?'display:none':''}"
```
CSS 聲明脫離了 JS 運算範圍，不再有語法錯誤。Workspace 可正常渲染。

---

### P1-1 批次 STT 無說話人分離 → ✅ 已修復

後端新增端點 `POST /v1/tasks/{id}/diarize`，執行完整 VAD diarization → speaker assignment → merge → speaker_map 重建。前端 `runBatchStt()` 在所有段落處理完畢後自動呼叫此端點。

---

### P1-2 波形雙重點擊 → ✅ 已修復

`initZoomControls()` 只剩 `waveform-canvas` 的 click 監聽器，`waveform-area` 上的第二個監聽器已移除。點擊 Canvas 只觸發一次。

---

### P1-5 speaker_map 排序崩潰 → ✅ 已修復

`_process_transcription()` 新增 `_safe_speaker_key()` 函數：
```python
def _safe_speaker_key(sid: str) -> int:
    try:
        return int(sid.replace("人物 #", "").split()[0])
    except (ValueError, IndexError):
        return 9999
```
非標準格式將會排到最後，不再崩潰。

---

### P2-1 翻譯無載入狀態 → ✅ 已修復

點擊翻譯按鈕後：
```javascript
btn.disabled = true;
btn.innerHTML = '翻譯中 <span class="spinner"></span>';
```
完成後恢復。用戶可以清楚知道系統正在處理。

---

### P2-2 音檔錯誤無提示 → ✅ 已修復

`setupAudio()` 加入 error 處理器：
```javascript
S.audioEl.addEventListener('error', () => {
  toast('音檔載入失敗，請檢查原始檔案是否存在', 'err');
  S.audioReady = false;
});
```

---

### P2-3 重新識別後選取未清除 → ✅ 已修復

`reSttSelected()` 在遍歷前執行 `S.selected.clear()`。

---

### P2-4 批次 STT 多餘 reload → ✅ 已修復

`runBatchStt()` 不再對每個 segment 呼叫 `GET /v1/tasks/{id}`，改用本地狀態更新。

---

### P2-5 匯出 speaker name 未生效 → ✅ 已修復

匯出端點現在正確初始化 `SpeakerRegistry`：
```python
registry = SpeakerRegistry({sid: info.get("count", 0) for sid, info in speaker_map.items()})
```
`_map` 字典有內容，`set_name()` 可以正常生效。

---

### S-5 損壞 JSON 保護 → ⚠️ 路徑錯誤（見新發現 P0-3）

`TaskStore.load()` 加入了 try/except 和 `.tmp` 備份恢復，但備份檔案路徑不匹配（見下方 **P0-3**）。

---

## 第 1 輪未修復問題（仍存在）

### P1-3：前端完全未使用 `POST /v1/transcribe` 端點

**位置：** `frontend/index.html` → `confirmUpload()`

**狀態：** ❌ **未修復**  
**說明：** 前端仍然只呼叫 `POST /v1/upload`（`no_stt=true`），完全繞過 `/v1/transcribe` 的自動 diarization + STT 鏈。用戶上傳大檔案後必須手動切割→批量 STT→diarize。

**影響：** 與 P1-1 不同，P1-1 是批次 STT 缺 diarize（已修復），P1-3 是缺少一個完整的「一鍵轉寫」入口。

---

### P1-4：`retranscribe` 段落分配邏輯粗糙

**位置：** `app/api_server.py` → `retranscribe()`

**狀態：** ❌ **未修復**  
**說明：** 新 STT 回傳的段落數量 ≠ 原始段落數量時，按時間比例映射仍然可能：
- 多個新段落映射到同一個原始段落（後者覆蓋前者）
- 部分原始段落被跳過
- 當 `new_segs[-1]["end"]` 為 0 時 ratio 極大，全部塞到最後一個

---

### P2-6：`toggleCutMode()` 事件監聽器疊加（詳見下方新發現）

**狀態：** ⚠️ 未修復，且本輪增強為更嚴重的問題

---

### S-1 ~ S-4 建議

全部未實作。

---

## 新發現問題

### P0-3：備份檔案路徑不匹配→JSON 損壞恢復完全失效

**位置：** `app/api_server.py` → `TaskStore.save()` vs `TaskStore.load()`  

**嚴重性：** **P0 阻塞**

**問題：**  
`save()` 寫入的暫存檔案路徑與 `load()` 恢復時尋找的路徑不同：

```python
# save() 中：
temp_path = path.with_suffix(".tmp")
# 對於 task_id.json → task_id.tmp

# load() 中：
tmp_path = path.with_suffix(".json.tmp")
# 對於 task_id.json → task_id.json.tmp  ← 錯誤！
```

`path.with_suffix(".tmp")` 會將最後一個後綴 `.json` 替換為 `.tmp`，得到 `task_id.tmp`。  
`path.with_suffix(".json.tmp")` 會將最後一個後綴 `.json` 替換為 `.json.tmp`，得到 `task_id.json.tmp`。

兩個路徑指向不同的檔案。S-5 的「防損壞保護」形同虛設——當主 JSON 損壞時，永遠找不到備份檔案，還是會回傳 `None`。

**修復方向：** 將 `load()` 中的 `path.with_suffix(".json.tmp")` 改為 `path.with_suffix(".tmp")`。

**影響路徑：** 任何異常關機後，任務 JSON 如果損壞 → 備份找不到 → 任務遺失。

---

### P1-6（New）：`diarize_task()` 端點 speaker_map 排序不安全

**位置：** `app/api_server.py` → `diarize_task()`  

**嚴重性：** **P1 功能缺陷**

**問題：**  
`_process_transcription()` 使用 `_safe_speaker_key()`（try/except 保護），但 `diarize_task()` 直接使用未保護的 lambda：

```python
sorted(speaker_counts.items(), key=lambda x: (
    int(x[0].replace("人物 #", "")) if "人物 #" in x[0] else 9999
))
```

如果 speaker_id 包含 `"人物 #"` 但後接非數字（如 `"人物 #abc"`），`int()` 會拋出 `ValueError`，整個端點返回 500。

**對比：** `_process_transcription()` 的 `_safe_speaker_key()` 有完整保護，`diarize_task()` 應使用相同函數。

**影響：** 批量 STT → diarize 鏈中的說話人排序可能崩潰。

---

### P2-7（New）：`toggleCutMode()` 事件監聽器嚴重疊加

**位置：** `frontend/index.html` → `toggleCutMode()`

**嚴重性：** **P2 體驗問題**

**問題：**  
每次調用 `toggleCutMode()` 都會為 `btn-cancel-cut` 和 `btn-confirm-cut` 註冊新的 click 監聽器。與第 1 輪分析的 P2-6 不同（當時認為 DOM 重建會清除），現在確認：

1. `toggleCutMode()` 不重建 DOM，僅切換顯示狀態
2. 連續切換切割模式開/關多次後，監聽器成倍堆疊
3. 點擊「取消」時，多個監聽器輪流呼叫 `toggleCutMode()`，導致狀態反覆翻轉
4. 點擊「確認切割」時，`confirmCut()` 被呼叫多次，會發送多個重複的切割請求

**再現步驟：**
1. 進入 Workspace
2. 點「切割」（開啟切割模式）→ `toggleCutMode()` 添加 2 個監聽器
3. 點「取消」（關閉切割模式）→ 第 2 次調用 `toggleCutMode()`，再添加 2 個監聽器（累計 4 個）
4. 重複步驟 2~3 多次 → 監聽器數量飆升
5. 點「確認切割」→ `confirmCut()` 被呼叫 N 次

**修復方向：** 使用一次性綁定（`{once: true}`）、或在綁定前先 `removeEventListener`、或將監聽器註冊移到 `renderWorkspace()` 的 `wireToolbar()` 中。

---

### P2-8（New）：`reSttSelected()` 逐個 ID 發送 API

**位置：** `frontend/index.html` → `reSttSelected()`

**嚴重性：** **P2 體驗問題**

**問題：**  
用戶選取多個段落時，程式碼對每個 ID 分別發送一次 API 請求，並在每次請求後重新載入完整任務資料：

```javascript
for (const id of ids) {
  await api('POST', `/tasks/${S.taskId}/retranscribe`, { segment_ids: [id], ... });
  const task = await api('GET', `/tasks/${S.taskId}`);  // 每次 reload
  ...
}
```

後端 `retranscribe` 端點本身支援批量（接受 `segment_ids` 陣列），將它們合併為一個時間範圍處理。前端卻逐個發送，浪費 N 次 API 和 N-1 次全任務 reload。

**影響：** 選取 5 個段落 → 5 次 API + 5 次全 reload（應為 1 次 API + 0 次 reload）。

**修復方向：** 將所有 `ids` 一次傳入：
```javascript
await api('POST', ..., { segment_ids: ids });
```

---

### P2-9（New）：TXT 匯出無任何載入指示

**位置：** `frontend/index.html` → `doExport()`

**嚴重性：** **P2 體驗問題**

**問題：**  
`openExportModal('docx')` 有 `disabled` + `匯出中...` 的載入狀態，但 `doExport('txt')`（工具列→匯出→TXT 純文字）完全沒有：

```javascript
async function doExport(fmt) {
  try {
    const res = await api('POST', ...);
    ...
  } catch (e) { toast(e.message, 'err'); }
}
```

雖然 TXT 匯出通常很快（無需生成 DOCX），但如果在大型檔案（上千個 segments）或後端負載高時，用戶點擊後沒有任何反饋，可能重複點擊。

---

### P2-10（New）：鍵盤快捷鍵監聽器重複註冊

**位置：** `frontend/index.html` → `setupAudio()`

**嚴重性：** **P2 體驗問題**

**問題：**  
`setupAudio()` 每次被調用（每次 renderWorkspace）都會執行：
```javascript
document.addEventListener('keydown', onKeyboard);
```
`onKeyboard` 是具名函數，但 `addEventListener` 不會自動去重。每次進入 Workspace 就疊加一個監聽器。當按空白鍵或方向鍵時，`onKeyboard` 被調用多次：

```javascript
if (e.key === ' ') { e.preventDefault(); togglePlay(); }
if (e.key === 'ArrowLeft' && S.audioEl) { S.audioEl.currentTime = ...; }
```

**影響：** 按空白鍵 → `togglePlay()` 調用多次 → 播放/暫停狀態反覆翻轉。按方向鍵 → 跳轉多次。

**修復方向：** 將 `keydown` 監聽器移到全域初始化階段（`init()`）或使用 `{ once: true }` / `removeEventListener`。

---

### P2-11（New）：DOCX 匯出時 `font_name` 在 docx 中未正確應用

**位置：** `app/exporter.py` → `export_docx()`

**嚴重性：** **P2 體驗問題**

**問題：**  
程式碼設定全域 Normal 樣式的字型為 `font_name`，但在後續內容段落中未明確應用。`python-docx` 的 `style.font.name` 對東亞字型（CJK）不完全生效——CJK 字符會回退到瀏覽器/檢視器預設字型，而不是 `font_name`。

```python
style = doc.styles["Normal"]
font = style.font
font.name = font_name  # 對 CJK 字符不完全生效
```

需要同時設定 `style.element.rPr.rFonts` 的 `eastAsia` 屬性：
```python
from docx.oxml.ns import qn
style.element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
```

**影響：** 用戶在匯出選項中選擇的字型（如 Noto Sans TC）可能對繁體中文字符無效，輸出文件顯示的字型與設定不一致。

---

## 建議改進

### S-6：批量 STT 完成後去除多餘 GET 請求

`runBatchStt()` 在 diarize 後執行：
```javascript
const diRes = await api('POST', `/tasks/${S.taskId}/diarize`);
const task = await api('GET', `/tasks/${S.taskId}`);
S.segments = task.result?.segments || [];
S.spkMap = task.result?.speaker_map || {};
```

`diRes` 的回應直接被忽略，緊接著又 GET 一次完整任務。diarize 回應已經包含 `speaker_map` 和更新後的 `segment_count`，可以直接使用（或讓端點回傳完整 segments），節省一次 API 呼叫。

---

### S-7：`stt_segment()` 端點加入簡單參數驗證

目前 `body.get("segment_id")` 如果為 `None`，後續的 `next(...)` 會拋出 `StopIteration`（由於 `generator` 沒有預設值）。應該加入明確的 None 檢查並回傳 400。

---

### S-8：切割後不丟失已完成的 STT 結果

當前 `split` 端點無論現有 segments 是否有已完成的 STT 結果，都直接清空重建。如果用戶先做了部分 STT 後想再細分某段落，已完成的結果會被丟棄。可以考慮保留時間範圍對應的 text 資料（進階功能）。

---

## 優先修復順序建議

1. **P0-3**（備份路徑不匹配）— 一行修復，影響重大
2. **P2-7**（切換監聽器疊加）— 影響切割體驗，修復簡單
3. **P2-10**（鍵盤監聽器疊加）— 影響播放控制，修復簡單
4. **P1-6**（diarize 排序不安全）— 與已修復的 P1-5 一致
5. **P2-8**（reSTT 逐個發送）— 效率問題
6. **P2-9/P2-11**（匯出體驗）— 體驗一致性和品質

---

## 關鍵使用者流程測試結果（第 2 輪）

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 上傳音檔 | ✅ | |
| 顯示檔案資訊 | ✅ | |
| 確認上傳 → Workspace | ✅ | P0-2 修復 |
| 波形繪製 | ✅ | |
| 切割模式 | ⚠️ | P2-7 監聽器疊加 |
| 確認切割 | ⚠️ | 同上，可能發送多次 |
| 批量 STT | ✅ | P1-1 修復，diarize 自動執行 |
| 說話人顯示 | ✅ | diarize 後 speaker_map 正確 |
| 重新 STT | ⚠️ | P2-8 逐個發送 |
| 書面語翻譯 | ✅ | P2-1 修復，有 spinner |
| 匯出 TXT/DOCX | ✅ | P0-1 修復，可正常下載 |
| 修改說話人名稱→匯出 | ✅ | P2-5 修復 |
| JSON 損壞恢復 | ❌ | P0-3 備份路徑不匹配 |
| 崩潰恢復（正常 JSON） | ✅ | |

---

## 總結

**第 1 輪 17 項問題中，11 項修復已驗證正確**，其餘 6 項（P1-3/P1-4/P2-6 + 3 項建議）未處理。本輪發現 **1 項 P0（實際是 S-5 修復本身的 bug）**、**1 項 P1**、**5 項 P2**、**3 項建議**。

整體專案品質較第 1 輪有顯著提升，核心流程（上傳→切割→STT→diarize→翻譯→匯出）已可正常運作。主要殘留風險是 P0-3（備份恢復形同虛設）和 P2-7/P2-10（事件監聽器疊加導致行為異常）。

---

*報告結束。*
