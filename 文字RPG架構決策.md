# Ollama 本地文字 RPG — 架構決策文件

> 定稿日期：2026/07/11
> 核心目標：LLM 驅動的文字 RPG，選項有限(非全開放輸入)、少量自訂輸入格；核心賣點是「記得玩家做過的事」，架構設計圍繞這個賣點展開。
>
> **這份文件記的是完整架構藍圖，不是起跑門檻。** 真正要開始動手，只需要下面「0. 最小可玩版本」那一小塊，其餘每一節都是「之後撞到某個具體問題時才對應加上去的升級包」，不是現在就要一次做完的清單。

---

## 0. 最小可玩版本（MVP）— 先只做這些

**範圍刻意縮到最小，目標是「一個晚上到一個週末，能跟 Claude Code 一起摸出來」：**

- **1 個場景，2-3 個固定選項**——自訂輸入格、別名比對、隱藏觸發詞清單，全部不存在，之後再加
- **1 個 NPC，背景故事只寫 3-5 條事實**——不是「童年求學長大」全套，先寫「他怕黑」「他嘴硬心軟」這種程度就夠
- **State 存在記憶體裡的一個 Python dict**——不接 MongoDB，資料庫什麼時候接都來得及
- **完全不用 Qdrant／向量記憶**——NPC 記不記得你，先靠把最近幾句對話直接塞進 context 撐著
- **`affinity` 只留一個數字**——`hard`/`soft` 雙軌先不分
- **呈現層用 CLI**——一個 Python script 印文字、讀輸入即可，不用做網頁
- **模型設定**：`qwen3.5:9b`，`think: false` + `num_ctx: 8192`（已實測驗證，見第 3 節）
- **state_delta schema 最小版**：只要 `narrative` + 一個鎖 enum(-1/0/+1) 的好感度欄位，`flags_set`、白名單驗證都先不用

**這個版本做出來，你才會真正知道**：敘事讀起來順不順、`qwen3.5:9b` 演 NPC 演得像不像話——這些是玩出來的判斷，不是紙上設計能得到的。

**撞到問題了，再回來對照升級——不用預先讀，卡住哪塊才翻哪節：**

| 你會撞到的狀況 | 對應章節 |
|---|---|
| 想加自訂輸入文字框 | 第 8 節 |
| 玩家亂打字想搞笑/踩到你沒設計過的東西 | 第 8 節（unsupported 分支） |
| 想讓 LLM 生成的內容不要亂改數值 | 第 4.1 節（schema 鐵律）、第 9 節（踩坑紀錄） |
| NPC 記不住太久以前的事 | 第 5 節（資料儲存設計） |
| 想要好感度有「正式劇情」跟「隨口互動」兩種分開的影響力 | 第 4.6 節（好感度雙軌設計） |
| NPC 背景故事要先寫好還是用生的 | 第 4.7 節 |
| 筆電資源不夠、想搬去 NAS | 第 6 節 |
| 覺得選項反應卡頓 | 第 4.3、4.4 節（預生成、列印動畫） |
| 要做成網頁還是純文字介面 | 第 7 節 |

---

## 1. 硬體規格

| 項目 | 規格 |
|---|---|
| 機器 | MSI Katana 15(筆電) |
| GPU | NVIDIA RTX 4060 Laptop GPU，8GB VRAM |
| RAM | 48GB |
| Ollama 版本 | 0.31.1 |
| 實測背景底噪 | 約 1.9GB(瀏覽器/Discord 等常駐程式) |
| 實際可用 VRAM | 約 6GB 出頭 |
| NAS | 已有 Docker/MongoDB 常駐環境 |

---

## 2. 模型選型（已定案）

### 2.1 敘事生成模型：`qwen3.5:9b`（留在筆電）

**排除的選項與理由：**

| 候選 | 排除/降級理由 |
|---|---|
| Qwen2.5 系列 | 已被 Qwen3 全面超越，僅 Qwen2.5-Coder(純程式碼)、既有社群微調版仍有留用價值，不適用本專案 |
| 舊世代 Qwen3(如 `qwen3:8b`/`qwen3:14b`) | 同樣有 thinking mode 問題；長 context 下 KV cache 效率不如 Qwen3.5 的 Gated DeltaNet 架構；`qwen3:14b` 在本機 VRAM 下會溢出，速度會被拖慢 |
| `qwen3:30b-a3b`(MoE) | Ollama 上有已知 GPU 使用率 issue，實測 dense 模型現階段更穩，不採用 |
| GLM(`glm4:9b` / `glm-5.x:cloud`) | `glm-5.x` 為雲端限定，需帳號升級，資料會離開本機，直接排除；`glm4:9b` 為本地可跑選項但世代較舊(2024年)，指令遵循/效率不如 Qwen3.5，僅列為敘事風格比較用途，比完即刪 |
| Llama 4(Scout) | 社群評測分數與推理表現不如同硬體級距的 Qwen 系列，且原生 VRAM 需求也偏高 |

**確定原因：**
- 官方點名優化角色扮演/創意寫作/多輪對話
- Gated DeltaNet 混合注意力架構，長 context 下 KV cache 佔用小，對本專案的長期記憶場景是直接利多
- 純文字任務，內建視覺塔會固定吃 VRAM(「視覺稅」)，但本專案用不到讀圖，這塊目前只能接受，尚無法關閉
- **唯一一個必須留在筆電上的元件**：需要 GPU、需要低延遲，無法搬去 NAS(見第 6 節)

### 2.2 Embedding 模型：`bge-m3`（搬去 NAS）

- 568M 參數，MIT 授權，支援 100+ 語言，可同時做 dense/sparse/多向量檢索
- 排除 `nomic-embed-text`：雖是 Ollama 下載量最高的 embedding 模型，但英文優化，中文效果不如 bge-m3
- 下載大小約 1.2GB
- 單次前向運算、非自迴歸生成，CPU 跑就足夠，適合搬到 NAS 常駐（見第 6 節）

### 2.3 向量資料庫：Qdrant（部署在 NAS，尚未安裝）

- 排除 Chroma：metadata filter 能力較弱，本專案需要依 NPC/時間區段等條件篩選記憶，Qdrant 的 filter 系統更合適
- 單一 Docker container 即可起，符合現有 NAS/Docker 使用習慣
- 純 CPU 工作負載(ANN 相似度搜尋)，天生適合放 NAS，且資料庫體積只會隨遊玩時間增長，放 NAS 順便解決筆電空間問題

---

## 3. 必要執行設定（已實測驗證，`qwen3.5:9b`）

### 3.1 關閉 thinking 模式

Qwen3.5 系列預設開啟 thinking，會在正式回應前生成大量 `<think>...</think>` 推理內容，對結構化輸出管線是雜訊，必須關閉。

互動模式驗證指令：
```
ollama run qwen3.5:9b
>>> /set nothink
```

API 呼叫需在請求中帶：
```json
{ "think": false }
```

### 3.2 限制 context 長度

Ollama 預設會照模型原生上限(qwen3.5 為 262144)去預留 KV cache，即使實際對話很短也一樣，這是拖垮效能的主因。改成：

```
>>> /set parameter num_ctx 8192
```

API 呼叫對應：
```json
{ "options": { "num_ctx": 8192 } }
```

8192 對「system prompt + 少量最近對話 + RAG 撈回來的幾條記憶」這個場景綽綽有餘，之後若記憶注入量變大再往上調。

### 3.3 實測數據（同一句測試輸入 "說一句話"）

| 設定 | SIZE | PROCESSOR (CPU/GPU) | eval count | eval rate |
|---|---|---|---|---|
| 預設(thinking on, num_ctx=262144) | 16 GB | 66% / 34% | 2951 tokens | 10.31 tok/s |
| 關 thinking，num_ctx 未改 | 16 GB | 66% / 34%(未變) | 15 tokens | 11.84 tok/s |
| 關 thinking + num_ctx=8192 | **6.4 GB** | **14% / 86%** | 15 tokens | **32.53 tok/s** |

結論：thinking mode 決定「吐多少字」，`num_ctx` 決定「模型能不能塞進 VRAM、字吐多快」，兩者必須同時處理，缺一不可。

---

## 4. 遊戲邏輯架構決策（已定案）

### 4.1 數值判定與敘事生成徹底解離

**歸演算法管（不經過 LLM）：**
- 技能檢定、機率、傷害/數值計算
- 固定選項在當下狀態的可用性判斷（規則表查詢）
- 固定選項對應的數值效果

**歸 LLM 管：**
- 把演算法已判定好的結果講成故事（narrative）
- 解析低頻使用的「自訂輸入格」，將自由文字對應成可執行的動作意圖，交還演算法判定

**Schema 設計鐵律：**
- LLM 的 output schema 裡**不開放任何數字欄位**（hp/damage/gold 等），不是靠 prompt 講規矩，是結構上沒有位置可填
- 少數需要 LLM 給主觀判斷的項目（如 NPC 好感度浮動），收斂成 enum（如 -1/0/+1）並在 schema 層用型別鎖死允許值
- **`flags_set` 也比照辦理，鎖成 enum**（見 5.3），不接受開放字串——白名單式約束，不做「相似字串容錯/模糊比對」補丁（理由見第 9 節踩坑紀錄）
- UI 顯示的血條/數字一律直接讀遊戲 state，絕不從 LLM 生成的敘事文字裡解析數字回來套用
- narrative 永遠只能是「state 變化之後」的產物，不能反過來當作 state 變化的依據（不寫 regex 從文字抓數字這種代碼）

### 4.2 呼叫流程

因為選項是有限、固定規則表決定（非 LLM 生成），架構收斂為：

```
單一分支：
  Call（敘事）：
    輸入：system prompt + 當前 state + 玩家選的動作
    輸出：{ "narrative": "...", "state_delta": {...} }
    （state_delta 只含 schema 允許的有限欄位，數值類全部由演算法算好後才餵給這次呼叫當上下文，不是叫 LLM 自己生）

  選項本身與其效果：規則表查詢，不呼叫 LLM

  例外：玩家使用自訂輸入格時，多一次「意圖解析」呼叫（見第 8 節）
```

### 4.3 選項預生成（背景緩衝策略）

- 畫面顯示出 N 個選項的當下，背景依序（非強行並行，見 4.5）把每個選項對應的敘事結果都跑完
- 玩家「讀文字 + 決定要選哪個」的時間，就是背景生成的緩衝窗
- 玩家真正點下去時，結果已備好，顯示為瞬間
- **未被選中的分支**：其 narrative、state_delta 一律整批丟棄，不得寫入正式 state 或長期記憶（向量庫），避免平行分支污染「記得玩家做過什麼」這個核心賣點

### 4.4 顯示層設計

- 不做逐字真實 token streaming
- 後端完整生成完（敘事 + state_delta）後，前端用自己控制節奏的「列印動畫」顯示，把生成耗時的變異吸收掉，畫面永遠是穩定速度在「列印」
- 例外情況才需要真實等待畫面：開局第一輪（無背景預生成可用）、背景預生成尚未跑完但玩家已操作的邊界情況

### 4.5 硬體並發限制

- 不強開 `OLLAMA_NUM_PARALLEL` 多路平行，VRAM 有限，多一個並發請求就多一份 KV cache 佔用，容易擠爆
- 依序生成 N 個分支，只要「玩家閱讀+決定時間」>「N 次依序生成總時間」，體感上不會感覺到卡頓（本機實測 32.53 tok/s，短敘事分支這個等式成立）

### 4.6 好感度雙軌設計：`affinity_hard` / `affinity_soft`

**問題背景**：好感度有兩種來源——完成任務/正式劇情選擇（硬性、演算法可控）跟隨口互動戳中笑點（軟性、LLM 即興判斷）。混在同一個數字裡，設計者會無法精準控制「玩家到底做了什麼才解鎖某段劇情」；但完全不讓軟性互動有影響，又會讓 NPC 顯得死板。

**決定：兩者分開存，只有 `hard` 參與門檻判斷，`soft` 只影響敘事語氣，不觸發任何 flag。**

```json
"npcs": {
  "npc_x": {
    "affinity_hard": 3,   // 只有演算法(任務完成、正式劇情選擇)能寫
    "affinity_soft": 2,   // 只有 LLM 的 enum(-1/0/+1) 能寫，即興互動
    "status": "neutral",
    "last_seen_turn": 40
  }
}
```

- `affinity_soft` 必須設上下限（如 ±5），避免長期遊玩下靠純聊天堆量翻過原本要留給正式劇情的門檻
- **曾考慮過「hard + soft × 權重」混合成單一門檻值**，但否決：權重調一點點可能讓大批卡在門檻邊緣的玩家一次全翻過/掉下去，這種行為在沒有真實數據前無法調準；先解耦成「soft 完全不參與 gate」，等實測有數據分佈後，若有需要再回頭評估要不要混合
- 混合出來的數字（若未來真的要做）只能查詢當下即時計算，**不可另存成第三個欄位**，避免多處寫入邏輯漏同步導致資料不一致

**程式骨架（給 Claude Code 接手用的起點，非最終實作）：**

```python
# npc_state.py

NPC_SOFT_BOUND = 5  # affinity_soft 的上下限，數字可調，等實測調整

def clamp(value, lo, hi):
    return max(lo, min(hi, value))

def apply_affinity_delta(npc_state: dict, delta_source: str, delta: int):
    """
    delta_source: "hard"（演算法/正式劇情觸發）或 "soft"（LLM 即興判斷）
    delta: 必須是 schema 已鎖死範圍內的值，這裡只負責套用，不做合法性驗證
           （驗證應在更上游、餵進來之前就做完，見 4.1、9.1）
    """
    if delta_source == "hard":
        npc_state["affinity_hard"] = npc_state.get("affinity_hard", 0) + delta
    elif delta_source == "soft":
        current = npc_state.get("affinity_soft", 0)
        npc_state["affinity_soft"] = clamp(current + delta, -NPC_SOFT_BOUND, NPC_SOFT_BOUND)
    return npc_state


def check_hard_gate(npc_state: dict, threshold: int, flag_name: str, flags: dict) -> bool:
    """只看 affinity_hard，soft 完全不參與，且同一個 flag 只觸發一次"""
    if flags.get(flag_name):
        return False
    if npc_state.get("affinity_hard", 0) >= threshold:
        flags[flag_name] = True
        return True
    return False


def get_tone_hint(npc_state: dict) -> str | None:
    """soft 只用來給敘事語氣提示，不影響任何 gate 判斷"""
    soft = npc_state.get("affinity_soft", 0)
    if soft >= 3:
        return "warmer_than_usual"
    if soft <= -3:
        return "more_impatient_than_usual"
    return None
```

`threshold`、`flag_name`、觸發後要塞哪句 context 事實，是遊戲內容，留給實際開發時填（見第 10 節 TODO）。

### 4.7 NPC 背景故事設計原則

**決定：NPC 核心設定必須先寫好（寫死），不能用 LLM 即時生成。**

理由：一致性要求與即時生成互斥。玩家在第 5 回合與第 80 回合都可能聽到同一個 NPC 提起童年往事，兩者必須對得上——這正是「LLM 沒有真正記憶，只能靠外部組裝」的同一個根本問題，只是這次「記憶」的對象是人物背景而非玩家行為史。

**分工：**
```
NPC 核心檔案（先寫好，寫死，是「事實」）
  ├─ 基本背景：童年環境、求學經歷、關鍵轉折事件（條列式事實清單，不是敘事文章）
  ├─ 性格核心：幾條簡短描述（怕黑、嘴硬心軟、不擅表達感情）
  └─ 說話風格：口頭禪、語氣傾向

  ↓
敘事呼叫時（LLM 現場生成，是「演繹」）
  context 塞：核心檔案 + 玩家與此 NPC 的互動記憶（Qdrant 撈的，見 5.5）
  LLM 根據已寫死的事實去演，具體怎麼講、當下反應怎樣，交給它發揮
```

- 核心檔案顆粒度跟 NPC 別名表（第 8 節）、合法 flag 清單（第 10 節 TODO）同一類：內容創作，不是架構問題，可以逐步增補，不用一次寫滿才能開始測試
- LLM 可用於輔助擴寫初稿（把關鍵字/大綱擴成事實清單格式），但這是創作階段的草稿工具，跟遊戲運行時的即時演繹是不同階段/用途，不要混淆

---

## 5. 資料儲存設計（已定案）

### 5.1 兩層資料模型

```
「當前快照」(state)  — 小、快、隨時要能同步讀取 → MongoDB
「歷史流水」(記憶)   — 只增不減、量會一直長大 → Qdrant + embedding
```

規則引擎需要立即查得到的答案（NPC 現在對我什麼態度、有沒有某個道具）放快照；「三十回合前跟這個 NPC 說過什麼」這種內容放向量記憶，不塞進快照裡讓它越滾越大。

### 5.2 State 快照結構（範例）

```json
{
  "player": {
    "stats": { "hp": 80, "max_hp": 100, "gold": 150 },
    "flags": { "met_npc_x": true },
    "inventory": ["rusty_sword", "torch"],
    "location": "forest_entrance",
    "turn_count": 42
  },
  "npcs": {
    "npc_x": { "affinity_hard": 3, "affinity_soft": 2, "status": "neutral", "last_seen_turn": 40 }
  }
}
```

`npcs` 只放每個 NPC 的**當下狀態數值**，不放「發生過的事」——事實內容進 Qdrant，用 `npc_id` 當 metadata 篩選。

### 5.3 state_delta schema（LLM 每回合輸出）

```json
{
  "type": "object",
  "properties": {
    "narrative": { "type": "string" },
    "npc_affinity_delta": {
      "type": "object",
      "additionalProperties": { "type": "integer", "enum": [-1, 0, 1] }
    },
    "flags_set": {
      "type": "array",
      "items": { "type": "string", "enum": ["met_npc_x", "found_key", "__待補：完整合法 flag 清單__"] }
    },
    "memory_note": {
      "type": "string",
      "description": "一句話摘要，寫進向量記憶的候選內容，選填"
    }
  },
  "required": ["narrative"]
}
```

- 沒有 `hp`/`gold` 等數字欄位，模型碰不到
- `npc_affinity_delta`（套用時寫入 `affinity_soft`）、`flags_set` 皆用 enum 鎖死範圍
- `memory_note` 是否要每回合都存：用規則判斷（`flags_set` 非空或 `npc_affinity_delta` 非零時才存），不額外問模型「這回合值不值得記」，避免自由心證

### 5.4 資料庫選型：MongoDB（NAS 上既有服務，沿用）

- state 本質是單一巢狀 JSON 文件，整包讀寫，不是需要外鍵關聯的關聯式資料，天生適合文件資料庫
- atomicity 不是問題：沒有跨表交易需求，單一文件 `updateOne` 本身就是原子操作
- 沿用既有 Mongo 服務，邊際成本趨近於零，優於另外安裝一個沒用過的資料庫

**Collection 設計：**
```
game_state (collection)
  _id: "save_001"
  version: 3              // schema 版本號，之後改 state 形狀時判斷存檔新舊格式用
  player: { ... }
  npcs: { ... }
  updated_at: ISODate(...)
```

**安全性注意（LLM 生成內容導致的注入風險）：**
`npc_affinity_delta` 是動態 key 的物件，若套用邏輯把 key 直接組進 update 路徑，LLM 一旦吐出包含 `$` 或 `.` 的異常 key，可能觸發 Mongo operator injection。**套用 delta 前必須先驗證每個 key 是否存在於 NPC 白名單（規則表）中，不在白名單一律丟棄。**

### 5.5 長期記憶檢索設計（Qdrant）

**Collection 設計：**
```
collection: memories
  vector: bge-m3(memory_note 的 embedding)
  payload:
    turn_count: int
    npc_ids: [string]   // 這回合涉及哪些 NPC，環境事件可以是空陣列
    location: string
    tags: [string]      // 選填，對應 flags_set 內容
    text: string         // memory_note 原文，撈回來後直接塞進 prompt
```

**寫入時機**：與 5.3 一致，只有 `flags_set` 非空或 `npc_affinity_delta` 非零的回合才寫，寫入量天生被規則篩過一輪，不會每回合塞瑣碎內容。

**查詢邏輯（NPC 個別記憶與世界記憶是同一份資料，差在要不要加 filter）：**
```
每回合生成敘事之前：
  query_text = 玩家這次選的動作 + 最近1-2回合的敘事
  query_vector = bge-m3(query_text)

  if 這個動作有明確對象(某個 npc_x):
    用 payload filter：npc_ids contains "npc_x"，優先撈這個 NPC 的相關記憶
  else:
    不加 filter，全域語意搜尋

  取 top-k(先抓 3-5 條)，把 text 塞進這次敘事呼叫的 context 裡
```

**暫不做**：階層式摘要（把多條 memory 壓縮成更高層摘要）——YAGNI，寫入量已被規則篩過、成長可控，除非玩到量體真的大到檢索開始撈出雜訊，不然不需要現在疊加這層複雜度。

**待實測調整**：純語意相似度排序可能讓「很久以前但語意相似」的記憶排到「剛發生但語意普通」的前面，這在敘事上有時反直覺。常見解法是混入 recency 時間衰減係數，但衰減曲線怎麼調需要餵真實情境測試後才能決定，先用純語意相似度做最簡版本。

---

## 6. NAS / 筆電分工（已定案）

```
NAS（常駐）
  ├─ 遊戲主程式（state 讀寫、規則判定、orchestrator）
  ├─ MongoDB（state 快照）
  ├─ Qdrant（長期記憶）
  ├─ Ollama + bge-m3（embedding，CPU 跑）
  └─ 需要敘事時 → 跨網路呼叫 →

筆電（只有要玩的時候才需要開機）
  └─ Ollama + qwen3.5:9b（narrative 生成，吃 GPU）
```

- 分工原則：只有「需要 GPU、需要低延遲」的敘事生成留在筆電，其餘常駐服務都在 NAS
- 筆電不開機時：可查歷史記憶、看存檔，但無法生成新的一回合
- 部署細節：Ollama 預設只綁 `localhost`，需設 `OLLAMA_HOST=0.0.0.0` 讓 NAS 連得到，Windows 防火牆需放行 11434 port

---

## 7. 呈現層技術選型（已定案）

**決定：CLI 先行（MVP 階段），Web 後續（完整體驗），Pygame 排除。**

**Pygame 排除理由**：Pygame 為即時圖形/精靈/物理設計，文字排版能力陽春（無自動換行、可捲動文字區塊等現成機制，需自己手刻）。本專案的核心體驗是大量文字、逐行印出、可捲動歷史紀錄、選項卡片——這正是 HTML/CSS 天生擅長、Pygame 天生不擅長的內容型態。這款遊戲本質是文字閱讀器，不是圖形渲染器，工具要挑對內容型態。

**CLI 與 Web 不是二選一，後端架構完全不受影響**：orchestrator、記憶系統已定案放在 NAS 上（第 6 節），CLI 或 Web 都只是呼叫同一支 API 的不同客戶端。

- **MVP 階段：CLI**——零 UI 投資，直接驗證「敘事讀起來順不順、qwen3.5:9b 演 NPC 演得像不像話」，這個判斷跟畫面漂不漂亮無關。CLI 呼叫 NAS API 的邏輯，之後幾乎能直接搬到 Web 版的後端呼叫層，不是白做工。
- **驗證過後：Web**——最初的收據視覺雛形（逐行印、鋸齒紙邊、列印動畫）本來就是 HTML/CSS 做的，等於直接把那套設計接上真正的後端。Web 天生擅長非同步邏輯（`fetch` 天生 async），跟第 4.3/4.4 節的背景預生成、緩衝窗設計完全對得上。

---

## 8. 自訂輸入格完整設計（已定案）

**核心思路**：自訂輸入格不是另開一條路，是幫固定選項那條路多加一個入口，最終走向同一條下游管線（規則引擎判定 → LLM 敘事），不用為它另外設計一套 state_delta 邏輯。

### 8.1 完整判斷流程（依優先序）

```
玩家打字
  ↓
① 隱藏觸發詞比對（暗語清單，精確字串/pattern 比對，非公開於選項UI）
  命中 → 視為正常有效動作，state_delta 照套用
  ↓ 沒命中才繼續
② NPC 別名精確比對（找當前場景在場的目標實體）
  命中 1 個 → 直接解析成功，走正常管線
  命中 2+ 個 → 消歧選單（借用固定選項的 UI 呈現："你是指哪一位？"），不呼叫 LLM
  ↓ 命中 0 個才繼續
③ Call A（LLM 意圖解析，低溫、schema 約束）
  能對應到已知 action_type → 走正常管線
  對應不到 → unsupported
  ↓
④ unsupported → 走一次敘事呼叫（Call B），state_delta 部分丟棄（見 8.3）
```

### 8.2 NPC 別名表與意圖解析 schema

別名表掛在既有的 NPC 白名單規則表上，多一個欄位：

```python
NPC_REGISTRY = {
  "npc_x": {
    "display_name": "王大夫",
    "aliases": ["老王", "王哥", "那個老頭", "大夫"]
    # 核心事實清單（見 4.7）也掛在同一份資料上
  },
}
```

Call A 的 schema（`target` 的 enum 內容需依當前場景動態組出，不能是全遊戲 NPC 清單，避免選到不在場的實體）：

```json
{
  "type": "object",
  "properties": {
    "action_type": {
      "type": "string",
      "enum": ["attack", "talk", "search", "use_item", "move", "unsupported"]
    },
    "target": {
      "type": "string",
      "enum": ["__當前場景實際在場的實體ID，執行時動態生成__"]
    }
  },
  "required": ["action_type"]
}
```

命中失敗或有衝突時才交給 Call A，且要把「當前場景有哪些 NPC、各自別名」餵進 prompt context，讓模型做的是「查表比對」而非「憑空推理」，對小模型更友善。

### 8.3 unsupported 分支：接住玩家的胡鬧，但鎖死破壞力

**問題背景**：玩家自訂輸入不只是「規則對不上需要防呆」，也有大量「純粹想看你會不會接梗」的胡鬧輸入（跟 NPC 跳舞、問 NPC 今天吃了什麼）。前者該用安全、平淡的處理，後者是「沒有標準答案」的敘事創作機會，值得放手讓 LLM 發揮（呼應 4.1 節：有標準答案的不給模型碰，沒有標準答案的講錯也無傷大雅）。

**決定**：`unsupported` 不是寫死的罐頭回應，仍走一次敘事呼叫，只是嚴格限制它能造成的 state 影響：

```
命中 unsupported → Call B 敘事，system prompt 附加：
  「玩家做了一件遊戲規則沒有定義的事，用符合場景氣氛的方式輕鬆回應」
→ state_delta 回來後，分欄位處理，不是整包留或整包丟：
    flags_set          → 強制丟棄（硬事實不該靠即興生出來）
    npc_affinity_delta → 允許通過（軟性、可逆、鎖在 ±1，即興互動本該能影響它，見 4.6）
```

`npc_affinity_delta` 允許通過的安全性：它從頭到尾鎖在 enum(-1/0/+1)，不管觸發它的是正式判定還是一句胡鬧，最大偏差就是 ±1，且只寫入 `affinity_soft`（4.6），不會動到 `affinity_hard`，翻不了設計者精心設計的正式門檻。

判準的準確度會隨 NPC 記憶系統成熟（5.5）自然變好——context 裡有這個 NPC 的個性事實（4.7）越完整，「戳中笑點」的判斷會越準，不用一步到位。

---

## 9. 經驗教訓（源自舊專案 `ai-novel-generator` 的踩坑紀錄）

> 舊專案是用雲端 API（SiliconFlow）做多模型分工的長篇小說生成器（Architect=GLM-4／Writer=Qwen2.5-7B／Editor=GLM-4，DeepSeek R1 測試後未採用），非本地 Ollama，跟本專案技術棧不同，但踩過的坑是可直接遷移的教訓。

### 9.1 黑名單式糾錯打不贏，白名單才是解

舊專案曾試圖「事後偵測敘事輸出哪裡不對勁再修正」，結果是：修好一種錯誤，又冒出沒見過的新錯誤；為了堵漏洞，過濾條件越收越緊，連正常輸出也一起被誤殺。

**根本原因**：黑名單邏輯必須窮舉「什麼是壞的」，但模型能出錯的方式是無窮的，永遠追不完；門檻調鬆會漏抓，調緊會誤殺，兩個代價無法同時消除。

**本專案的因應**：全面採用白名單（schema + enum），只定義「什麼是允許的」，其餘一律拒絕，不需要窮舉壞情況。`npc_affinity_delta`、`flags_set` 皆採此模式（見 4.1、5.3）。

**明確排除的方案**：「相似字串模糊比對、容錯自動修正」——這在我們的 flag 命名模式下（entity ID 常在字尾，如 `met_npc_x` vs `met_npc_y`）特別危險，模糊比對可能把 A 的事件誤套用到指涉完全不同的 B 身上，是「悄悄套用到錯誤對象」而非單純漏記，傷害等級更高。此方案已評估並否決，不採用。NPC 別名表（第 8 節）不是這條路的例外——別名表是事先窮舉、精確比對的白名單，跟模糊相似度演算法是完全不同的類別。

### 9.2 敘事一致性不能用強制規則框，NPC 記憶要餵事實不要餵劇本

舊專案的 `character_arc_enforcer.py`（角色弧線強制器）用規則硬性框住角色行為以防止跑題（起因是 Qwen2.5 容易離題），代價是角色弧光變得「罐頭化」、失去生命力。

**本專案的因應**：數值判定與敘事生成已徹底解離（4.1），從未設計任何「敘事一致性強制器」去規範 narrative 文字本身怎麼寫，天生避開此坑。

**設計時要主動提醒自己的原則**：NPC 記憶檢索（5.5）餵給模型的必須是**事實**（這個 NPC 上次跟你吵過架、你欠他錢），不能是**劇本**（這個 NPC 現在必須用某種固定語氣回話）。前者給模型素材讓它自己演繹，後者等於重蹈舊專案的覆轍，只是換了包裝。

### 9.3 自動一致性檢查／評分機制，優先度降到最低

舊專案「常常需要修」的經驗證明：自動偵測矛盾或評分的機制，誤判率天生偏高，會變成需要人工持續維護的假自動化。

**因應**：「未來若需要可加一層一致性檢查」正式降級為「除非真的被逼到牆角，不然不做」，不預先規劃、不預先開發。

### 9.4 可重用技術：JSON 容錯解析

舊專案 `utils/json_parser.py` 的 5 層 cascading 解析策略（標準 JSON → 抓 ```json``` 區塊 → 抓任意 ``` ``` 區塊 → 暴力抓 `{...}` → 暴力抓 `[...]`）是自成一體的文字處理工具，不依賴專案其他部分是否成熟，風險低，**值得直接搬進本專案 state_delta 的解析層當 schema validation 之外的第一道防線**。

---

## 10. 尚待設計 / 待補內容（下一輪或開發時處理）

**純執行/內容創作類（不是設計問題，等開發到那一步再填）：**
- [ ] Qdrant / MongoDB 實際安裝與連線設定
- [ ] state schema 版本遷移腳本（`version` 欄位如何驅動遷移邏輯）
- [ ] 制定完整合法 flag 清單（`flags_set` enum 的實際內容）
- [ ] NPC 別名表、隱藏觸發詞清單的實際內容（第 8 節）
- [ ] 各 NPC 核心事實清單（背景、性格、說話風格，見 4.7）的實際內容
- [ ] 移植舊專案 `json_parser.py` 的 5 層 cascading 解析邏輯進本專案

**需要實測數據才能調準的參數（先寫死合理猜測，playtest 後回頭調）：**
- [ ] `affinity_soft` 上下限（暫定 ±5）
- [ ] 各 NPC 好感度門檻 `threshold` 數字
- [ ] 長期記憶檢索是否要疊加 recency 時間衰減、衰減曲線怎麼調（5.5）

---

## 11. 本地/NAS 資源清單

**筆電（僅保留必要項目）：**
- `qwen3.5:9b`（6.6GB 下載 / 實測運行 6.4GB）— 專案主力，唯一必須留在本機的模型
- `qwen2.5-coder:7b`（既有，非本專案用途，不動）

**待搬遷/清理：**
- `bge-m3`（1.2GB）→ 搬去 NAS 後本機可 `ollama rm bge-m3`
- `glm4:9b`（5.5GB）→ 敘事風格比較用途，比完即刪，不建議常駐（純 CPU 生成速度不可用）

**NAS（新增）：**
- MongoDB：新增 `game_state` collection（沿用既有服務）
- Qdrant：待安裝（Docker container），新增 `memories` collection
- Ollama + `bge-m3`：待部署
