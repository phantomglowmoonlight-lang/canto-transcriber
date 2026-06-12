# QA 第三輪最終審查報告：CantoTranscriber

**審查日期：** 2026-06-11  
**審查範圍：** `frontend/index.html` / `app/api_server.py` / `app/exporter.py` / `app/diarizer.py`  
**審查方式：** 程式碼閱讀 + 三輪完整回歸驗證 + 邊界情況分析  
**目的：** 確認專案已可正式使用，或列出最後阻塞項目

---

## 修復驗證總表

### 第 2 輪發現 + 第 3 輪指派修復 — 9 項

| 編號 | 問題 | 驗證 | 證據 |
|------|------|------|------|
| P0-3 | JSON 備份路徑不匹配 | ✅ **已修復** | `save()` 寫入 `.tmp`，`load()` 恢復也讀 `.tmp`，兩者一致 |
| P1-6 | `diarize_task` 排序缺 try/except | ✅ **已修復** | `_safe_key()` 內建 try/except，非標準格式回傳 9999 |
| P2-7 | 切割按鈕監聽器疊加 | ✅ **已修復** | `toggleCutMode()` 僅切顯示狀態，事件綁定在 `wireToolbar()` 一次性處理 |
| P2-8 | `reSttSelected` 逐個發送 API | ✅ **已修復** | 一次傳入全部 `segment_ids: ids`，後端批量處理，僅一次 reload |
| P2-9 | TXT 匯出無載入狀態 | ✅ **已修復** | `doExport()` 開頭 disabled 按鈕 + 顯示「匯出中...」，完成後恢復 |
| P2-10 | 鍵盤監聽器疊加 | ✅ **已修復** | `keydown` 監聽器移至全域 `init()` 註冊一次，`setupAudio()` 內已移除 |
| P2-11 | DOCX CJK 字型未生效 | ✅ **已修復** | `exporter.py` 加入 `w:eastAsia` 屬性設定，包含 try/except 向後相容 |
| S-6 | Diarize 後多餘 GET | ✅ **已修復** | 保留一次完整 reload（結構上必要），無多餘請求 |
| S-7 | `stt_segment` 無 `segment_id` 驗證 | ✅ **已修復** | 明確 `if segment_id is None: raise HTTPException(400)` |

### 第 1 輪修復重驗證 — 11 項（全部通過）

| 編號 | 修復內容 | 驗證 |
|------|----------|------|
| P0-1 | 匯出 blob 處理 (`res.blob()`) | ✅ |
| P0-2 | Workspace 模板語法（CSS 脫離 JS 插值） | ✅ |
| P1-1 | Batch STT 後自動呼叫 diarize | ✅ |
| P1-2 | 波形事件雙重觸發（area 監聽器已移除） | ✅ |
| P1-5 | `_safe_speaker_key` 用於 `_process_transcription` | ✅ |
| P2-1 | 翻譯按鈕 spinner 載入狀態 | ✅ |
| P2-2 | 音檔 error 事件處理器 | ✅ |
| P2-3 | 重新 STT 前清除選取 | ✅ |
| P2-4 | Batch STT 無多餘 reload | ✅ |
| P2-5 | Export endpoint 正確初始化 SpeakerRegistry | ✅ |
| S-5 | JSON 損壞保護 | ✅（P0-3 修復後功能正常） |

---

## 第 1 輪未修復問題（第 3 輪仍存在）

這兩項已在第 1 輪標記，第 2 輪和第 3 輪均未指派修復。

### P1-3：前端未使用 `POST /v1/transcribe` 端點

**狀態：** ❌ 未修復（3 輪持續存在）

`confirmUpload()` 始終呼叫 `POST /v1/upload`（`no_stt=true`），完全繞過 `/v1/transcribe` 的自動 diarization + STT 鏈。用戶上傳大檔案後必須手動切割 → 批量 STT → diarize。

**Impact：** 中等。核心功能鏈完整可運作，但缺少「一鍵轉寫」的便捷入口。

### P1-4：`retranscribe` 段落分配邏輯粗糙

**狀態：** ❌ 未修復（3 輪持續存在）

按時間比例映射未改變：
```python
ratio = nseg_mid / (new_segs[-1]["end"] or 0.001)
orig_idx = min(int(ratio * original_count), original_count - 1)
```

`new_segs[-1]["end"]` 為 0 時 ratio 極大，全部塞到最後一個原始段落。

**Impact：** 低。情境較少出現（STT 通常回傳合理時間戳），但仍是潛在 bug。

---

## 新增發現

### P2-12：匯出選單雙重點擊註冊（回歸）

**位置：** `frontend/index.html` → `wireToolbar()` 第 570~572 行與第 577~579 行

**嚴重性：** **P2 功能缺失**

**問題：**  
`btn-export` 的 click 事件監聽器被註冊了兩次：

```javascript
// 第 570~572 行 — 第一次註冊
document.getElementById('btn-export')?.addEventListener('click', () => {
    document.getElementById('export-menu').classList.toggle('hidden');
});

// 第 574~576 行 — 第二次註冊
document.getElementById('btn-export')?.addEventListener('click', () => {
    document.getElementById('export-menu').classList.toggle('hidden');
});
```

兩個獨立的箭頭函數（即使程式碼相同）被視為不同的監聽器。點擊「匯出 ▾」按鈕時：
1. 第一個監聽器：`toggle('hidden')` → 選單顯示
2. 第二個監聽器：`toggle('hidden')` → 選單隱藏

結果：**匯出下拉選單從不出現**。用戶無法透過點擊工具列的「匯出」按鈕觸發 TXT 或 DOCX 匯出。

**再現步驟：**
1. 進入 Workspace（有已完成 STT 的段落）
2. 點擊工具列「匯出 ▾」按鈕
3. 預期：顯示包含 TXT / DOCX 的下拉選單
4. 實際：選單閃現後立即消失，或完全不出現

**嚴重性評估：**
- 功能影響：用戶仍可透過程式碼路徑（無）使用匯出？沒有替代入口
- 實際上 `openExportModal('docx')` 和 `doExport('txt')` 分別是綁在 `exp-txt` 和 `exp-docx` 按鈕上的，但這些按鈕在 `export-menu` 內，而 `export-menu` 預設是 `hidden` 且無法透過點擊展開
- 所以匯出功能在此 bug 下**完全無法從 UI 觸發**

**Root Cause：** 程式碼合併時遺留了重複片段。第 569~574 行是正常的 export → menu 綁定，第 576~579 行是註解為「Wire export menu toggle」的重複區塊。應移除第 576~579 行的重複程式碼。

**修復方向：** 移除第 576~579 行（從 `// Wire export menu toggle` 開始的整個區塊）。

---

## 完整流程追蹤

### 流程 1：上傳 → 確認 → Workspace → 切割 → 批量 STT → diarize → 翻譯 → 匯出

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 上傳音檔（drag/click） | ✅ | |
| 顯示檔案資訊 | ✅ | 時長、大小、格式 |
| 確認上傳 | ✅ | 呼叫 POST /v1/upload |
| 顯示 Workspace | ✅ | P0-2 已修復 |
| 波形繪製 | ✅ | 單一 canvas click，無雙重觸發 |
| 切割模式 | ✅ | 監聽器單次綁定，無疊加 |
| 波形點擊加切割點 | ✅ | |
| 拖曳調整切割點 | ✅ | |
| 確認切割 | ✅ | 單次 API 呼叫 |
| 批量 STT | ✅ | 含進度條、暫停、取消 |
| 自動說話人分離（diarize） | ✅ | Batch STT 完成後自動觸發 |
| 說話人面板顯示 | ✅ | speaker_map 正確 |
| 重新識別選取段落 | ✅ | 批量傳入，僅一次 reload |
| 書面語翻譯 | ✅ | 有 spinner 載入狀態 |
| **點擊匯出 ▾** | ❌ | **P2-12：選單不出現** |
| 直接呼叫 `doExport('txt')` | ✅ | 按鈕有 disabled + 文字回饋 |
| DOCX 匯出設定字型 | ✅ | CJK eastAsia 屬性已設定 |
| 下載 TXT/DOCX | ✅ | P0-1 已修復，blob 正確 |

### 流程 2：崩潰恢復

| 步驟 | 狀態 | 備註 |
|------|------|------|
| 異常關機後重啟 | ✅ | |
| 偵測 last_task | ✅ | |
| 恢復提示 dialog | ✅ | |
| 載入任務資料 | ✅ | |
| JSON 損壞恢復 | ✅ | P0-3 修復後 .tmp 備份可正確讀取 |

### 流程 3：邊界情況

| 情況 | 狀態 | 備註 |
|------|------|------|
| 空檔案（0 bytes） | ✅ | validate_audio_file 拒絕 |
| 過短（< 1 秒） | ✅ | 同上 |
| 不支援格式 | ✅ | 副檔名過濾 |
| 無語音內容 | ✅ | check_for_speech 偵測 |
| 音檔損壞（轉換時） | ✅ | pydub 拋出，前端 toast 顯示 |
| 後端崩潰 | ✅ | 前端 toast 錯誤提示 |
| JSON 檔案損壞 | ✅ | S-5 + P0-3 聯合保護 |
| 異常 speaker_id 格式 | ✅ | _safe_key / _safe_speaker_key 保護 |

---

## 最終評價

### 已修復總數

| 輪次 | P0 | P1 | P2 | 建議 | 小計 |
|------|----|----|----|------|------|
| 第 1 輪發現 | 2 | 5 | 6 | 5 | **18** |
| 第 2 輪新發現 | 1 | 1 | 5 | 2 | **9** |
| 第 3 輪新發現 | 0 | 0 | 1 | 0 | **1** |
| **合計** | **3** | **6** | **12** | **7** | **28** |

| 類別 | 數量 |
|------|------|
| 已修復（P0/P1/P2） | 21 |
| 已修復（建議） | 3 |
| 未修復（P1-3, P1-4） | 2 |
| 未實作（S-1~S-4） | 4 |
| **本次新增（P2-12）** | **1** |

### P0/P1/P2 殘留

| 編號 | 等級 | 說明 | 影響 |
|------|------|------|------|
| P1-3 | P1 功能缺陷 | 前端未使用 `/v1/transcribe` | 缺少一鍵轉寫入口，但手動流程完整可運作 |
| P1-4 | P1 功能缺陷 | retranscribe 段落分配粗糙 | 邊界情況下的潛在 bug，觸發頻率低 |
| P2-12 | P2 功能缺失 | 匯出選單雙重點擊導致永遠不顯示 | **阻斷工具列匯出入口**，需立即修復 |

### 綜合判定

**核心流程（上傳→切割→STT→diarize→翻譯→匯出）**  
✅ 功能完整、無崩潰風險

**異常處理**  
✅ JSON 損壞恢復、音檔遺失、API 錯誤、異常 speaker_id → 均有保護

**阻斷問題**  
⚠️ **P2-12**：匯出選單雙重綁定導致 UI 無法觸發匯出。這是一個回歸 bug（第 2 輪報告時不存在，在第 3 輪程式碼中引入）。雖然底層匯出邏輯正確，但從工具列點擊「匯出 ▾」無法展開選單，用戶無法使用此入口匯出。

**結論：專案已達到接近可用的狀態，但 P2-12（匯出選單不顯示）需要在正式使用前修復。**

---

## 建議修復順序

1. **P2-12**（匯出選單雙重綁定）— 移除 3 行程式碼即可修復，阻斷 UI 功能
2. **P1-3**（一鍵轉寫入口）— 功能增強，非阻塞
3. **P1-4**（retranscribe 分配邏輯）— 邊界情況保護，非緊急

---

*報告結束。*
