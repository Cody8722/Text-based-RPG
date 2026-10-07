# CURRENT_ARCHITECTURE.md

這份文件描述 **目前工作目錄裡實際存在的 `game_mvp.py`（1098 行）**，是此刻的「架構真相」。
與其他文件衝突時，以本文件為準，因為：

- `CLAUDE.md`、`文字RPG架構決策.md` 是設計意圖，沒有跟著第二、三輪修復更新（例如仍寫著雲端選項「數量對不上才 fallback」）。
- `MVP_AUDIT.md`、`CAUSALITY_ATTACK_REPORT.md` 是**修復前的快照**，裡面列的 A6／A7／A11、「scripted 可重複」「history 汙染」現在都已修復，別把它們當成現況。
- 本文件的每一個斷言都來自 `game_mvp.py` 或可由測試重現；少數屬於推論的地方有標明。

行號引用格式：`game_mvp.py:行號`。

> 註：本文件撰寫時，工作目錄的修復（`game_mvp.py`、`tests/`、`.gitignore`、`.env.example`）全部**尚未 commit**。

---

## 1. 目前實際存在的 state 欄位

### 1.1 遊戲 state（`state`，`:174`，純記憶體 dict，沒有存檔／讀檔）

| 欄位 | 型別 | 寫入者（全檔只有這些寫入點） |
|---|---|---|
| `turn_count` | int | `scene` 分支 `:985`、`flavor` 分支 `:992`、`apply_turn_result` `:930` |
| `location` | str（`SCENES` 的 key） | 只有 `scene` 分支 `:984`，值來自靜態 `option["target"]` |
| `player.flags` | dict[str, True] | 只有 `apply_flags` `:221`（輸入需通過 `FLAG_WHITELIST`） |
| `player.prowess_growth_count` | int | 只有 `apply_turn_result` `:947`，且僅在選項靜態資料帶 `grow_prowess: True` 時 |
| `npcs[id].affinity` | int（實務上；float 見 §12） | 只有 `apply_turn_result` `:929`，clamp 在 ±5 |
| `npcs[id].option_counts[option_id]` | int | 只有 `apply_turn_result` `:928`（只在回合完整成功後才寫） |

六個 NPC：`npc_wang`、`npc_ayue`、`npc_ayue_mother`、`npc_debtor`、`npc_vendor`、`npc_innkeeper`。目前合法旗標三個：`offered_help_ayue`、`helped_wang_debt`、`mentioned_wang_debt`。

### 1.2 即時算出、不存的值
- `current_prowess()`：由 `prowess_growth_count` 用解析解算出（`:239-245`）。
- `get_visible_options()`：由 `flags` 算出選單可見性（`requires_flag`＋「scripted 已完成」過濾，`:588-604`）。
- `affinity_tier()`：由 affinity 算出餵給 Call1 的分級描述（`:274`）。

### 1.3 非 state 的執行期資料
- `conversation_history[npc_id]`（`:287`）：每個 NPC 的 user／assistant 訊息串，**無上限**，只在回合完整成功後才寫入（`commit_turn_history` `:866`）。這是 **LLM context，不是 state**，但一部分內容是 LLM 產生的。
- `MEMORY_ENABLED`（`:618`）：開場連線檢查失敗就關掉。
- Qdrant `memories` collection：**外部、跨局持久**，而 state 每次啟動都重置（兩者壽命不一致，見 §12）。

### 1.4 靜態資料（Python 權威，執行期不變）
`NPCS`（核心事實）、`SCENES`（場景、氛圍、選項、`outcome_above/below`、成功率、`hint`）、`FLAG_WHITELIST`、`LLM_ASSIGNABLE_FLAGS`（空）、`FLAG_FACTS`、各種常數。

---

## 2. 四種 option type 的完整 data flow

所有流程共同的前置與後置：

```
display_options = render_options()          # :607  Python 選項 + (可選)雲端 display_text
input → 驗證 1 ≤ idx ≤ len(display_options)   # :976
option = display_options[idx-1]              # Python 原選項物件；id/type/target/text 皆為 Python 值
… 依 type 分支 …
display_options = render_options()           # 下一回合選單
```

### 2.1 `scene`（`:983-988`）
```
state["location"] = option["target"]        # 靜態值
state["turn_count"] += 1
print 新場景 intro（靜態）
```
沒有任何 LLM 呼叫（雲端選單改寫除外，發生在 `render_options`）。

### 2.2 `flavor`（`:990-994`）
```
print option["response"]（靜態）
state["turn_count"] += 1
```
沒有 LLM 呼叫。

### 2.3 `npc`（`:1048-1090`）— 唯一讓 LLM 判斷產生 state 變化的路徑
```
action = option["text"]                      # Python 原意圖文字（不是雲端措辭）
ask_count = option_counts[id] + 1
[僅老王] debt_mention_attempted = 未鋪墊 ∧ 未完成 ∧ random.randint(1,100) ≤ 30   # Python 擲骰，在 Call1 之前
call_llm():
  Call1  call_narrative_llm
         query_memories(action + 最近 2 段敘事, npc_id)   # embed → Qdrant search，filter npc_ids ∋ target
         build_system_prompt: 核心事實 + 場景氛圍 + affinity_tier + 重複提示
                              + 記憶(sanitize, ≤4 條) + FLAG_FACTS + flavor_hint
         Ollama chat（含該 NPC 的 history，schema 鎖 narrative/memory_note/flags_set）
         parse_llm_json → strip_residue → flags_set 只留 ∈ LLM_ASSIGNABLE_FLAGS(空) ⇒ 恆為 []
  Call2  call_affinity_llm(narrative)     # 只看 narrative；temperature 0, seed 42；schema enum(-1,0,1)
         delta ∈ (-1,0,1) 否則 0
任何例外 → 印訊息 → continue（整回合作廢：state、history、option_counts 都不動）
print narrative
commit_turn_history                          # 玩家看到之後才進 history
delta 再次檢查 ∈ (-1,0,1)
flags: result.flags_set(恆空) + (debt_mention_attempted ∧ delta==1 ? "mentioned_wang_debt")
apply_flags → apply_turn_result:
   option_counts[id]=ask_count; affinity=clamp(+delta); turn_count+=1
   if delta≠0: write_memory(turn, npc, memory_note[LLM, 經 sanitize])
```

### 2.4 `npc_scripted`（`:996-1046`）— 結果由 Python 決定，LLM 只講故事
```
base_rate = option.base_rate_above/below（依 affinity > success_threshold）
prowess_bonus = (current_prowess() − 5) × 4
success = resolve_scripted_outcome(base_rate, bonus)   # clamp 5..95，random.randint 擲骰，每次互動恰好一次
outcome = outcome_above | outcome_below                # 靜態資料：delta / flag / hint / grow_prowess
try:  Call1(scripted_outcome = outcome.hint) ; 空敘事 → ValueError
except Exception:  narrative = outcome.hint            # Python 備援敘事；結果照常套用，不重擲、不作廢
print narrative
memory_note = scripted_memory_note(outcome)            # 由 Python 依 outcome 建立，Call1 的 memory_note 被丟棄
commit_turn_history(narrative, memory_note)            # history 裡的 memory_note 也是 Python 版
if outcome.flag: apply_flags([flag])
apply_turn_result(delta=outcome.delta, memory_note, prowess_growth=outcome.grow_prowess)
```
- **不呼叫 Call2**。
- 成功後選項從選單消失（`is_scripted_option_completed` `:588`：`outcome_above["flag"]` 已設）；失敗不設旗標，選項保留、可再次嘗試（每次重新擲骰，且失敗會被扣 −1）。

---

## 3. Call1 可以影響什麼

**Call1 = `qwen3.5:9b` 寫敘事**（`:825`）。

可以：
| 能力 | 範圍 / 限制 |
|---|---|
| 玩家讀到的敘事文字 | 任意字串（無長度／字元檢查，見 §12） |
| `history` 的 assistant 訊息內容 | 敘事＋memory_note（`flags_set` 恆為 `[]`） |
| **經由 Call2 間接決定 `npc` 回合的 affinity ±1** | Call2 唯一的輸入就是這段敘事，兩者同一個模型 |
| `npc` 回合的 Qdrant 記憶文字 | 僅在 delta≠0 時寫入；經 `sanitize_memory_text`（單行、去【】、≤200 字）；`npc_ids`／`location`／point id 由 Python 決定 |
| 下一輪檢索哪些記憶 | `query_text` 含最近兩段敘事 |
| 讓 `npc` 回合整個作廢 | 回傳非法輸出 ⇒ 例外 ⇒ 整回合無 state 變化（無 Python 已決定的結果可被否決） |

不可以（有 Python 實際 enforcement）：
- 設任何旗標（`:862` 用空的 `LLM_ASSIGNABLE_FLAGS` 過濾；`apply_flags` 另有 `FLAG_WHITELIST`）。
- 改 affinity（直接）、prowess、location、option_counts、turn_count、其他 NPC 的 state。
- 改變 `npc_scripted` 的成功／失敗、delta、flag、prowess 成長：這些來自靜態 `outcome`，且**Call1 失敗也不能讓它消失**。
- 讓 `npc_scripted` 回合的永久記憶或 history 的 `memory_note` 是它寫的內容。
- 額外的 JSON key（`affinity_delta`、`grow_prowess`…）一律被忽略（只讀三個 key）。

---

## 4. Call2 可以影響什麼

**Call2 = 好感度判定**（`:885`），輸入只有 Call1 的 `narrative`。

可以：
- `npc` 型回合中，目標 NPC 的 affinity −1／0／+1（驗證：`delta in (-1,0,1)`）。
- 以此間接影響：①該 NPC 的 `affinity_tier` 描述；②`npc_scripted` 的基礎成功率 30↔70；③`mentioned_wang_debt` 能否在擲骰命中時觸發（需 `delta==1`）；④是否寫入 `npc` 回合記憶（需 `delta≠0`）。
- 讓 `npc` 回合整個作廢（例外 ⇒ 無 state 變化）。這代表 Call2 可以**選擇性**作廢自己不想要的判定（例如只讓正向結果通過）。**沒有針對這點的測試**，見 §12。

不可以：設旗標、prowess、location；影響 `npc_scripted` 回合（根本不被呼叫）；影響非目標 NPC；超出 ±1／回合與 ±5 上限。
已知漏縫：`True`／`1.0` 會通過 `in (-1,0,1)`，affinity 可能變 float（有 expected-failure 測試）。

---

## 5. Cloud option generator 可以影響什麼

**雲端（OpenAI 相容 API，`:558`）只回傳每個選項的顯示措辭。**

可以：
- 選單上每一行的 `display_text`（`:967`）。僅此而已。

不可以：
- 選項的 `id`／`type`／`target`／`text`（意圖）、數量、順序、可見性。`render_options` 只新增 `display_text` 欄位（`:613`）；`main` 的 `action`、history、Call1 prompt 一律讀 Python 的 `option["text"]`。
- 玩家選的 index 對應的永遠是 Python 的第 N 個可見選項。
- 結構異常的回傳（非 list、數量不符、id 不齊／重複／未知、非字串、空字串、>120 字、非 JSON、請求失敗）一律整份 fallback 回 Python 原文（`parse_cloud_options` `:537`）。
- 回傳的文字會被收斂成單行。

仍然可以（無法由結構驗證擋住）：把 A 選項的措辭貼到 B 選項上（id 都在、各自唯一，但文字互換），玩家看到的選單會誤導，但按下去執行的仍是 Python 的選項（有測試）。

雲端 prompt 會收到：場景名、各選項的 id、原意圖文字、對象 NPC 的 `affinity_tier`。（單向：state 的分級描述 → 雲端。）

---

## 6. Qdrant memory 可以影響什麼

**記憶只通往一個地方：下一輪 Call1 的 system prompt**（`query_memories` 唯一呼叫點是 `call_narrative_llm` `:836`，已 grep 確認）。沒有任何程式碼讀記憶去改 state、旗標或機率。

寫入（`write_memory` `:659`）：
- 時機：`apply_turn_result` 中 `delta != 0`（`:933`）。`npc_scripted` 的 delta 恆非零，所以 scripted 回合一定寫入。
- 內容：`npc` 回合＝Call1 的 `memory_note`（LLM 自由文字，經 sanitize）；`npc_scripted` 回合＝Python 由 outcome 的 `hint` 建立。
- payload 由 Python 填：`npc_ids=[target]`、`location`、`turn_count`；point id = `turn_count`（**跨局會碰撞**，見 §12）。

讀取：
- 以目標 NPC 的 `npc_ids` 過濾，top 4，每條經 `sanitize_memory_text` 後放入 `【你還記得的一些事】`。已有測試證明不會跨 NPC。
- 效果：只影響 Call1 的敘事語氣與內容，進而經 Call2 影響 affinity（同 §3 的間接通道）。

不可以：設旗標／prowess／location；偽造 `【你們之間確實發生過的事】` 這類只應由旗標產生的 prompt 區塊（寫入端與讀取端都淨化）；讓 scripted 事件的記憶與 Python 結果不符。

可以（接受的殘留）：`npc` 回合的記憶是 LLM 對事件的轉述，可能與實際事件不符；跨局時舊記憶會與全新 state 矛盾。

---

## 7. Authoritative Python state

由 Python 規則（靜態資料＋擲骰＋驗證）決定，LLM 不能直接寫入的東西：

- `state.location`、`state.turn_count`、`option_counts`
- `player.flags`（含 `mentioned_wang_debt` 的「是否嘗試」擲骰；**但旗標確認需要 Call2 的 +1**，見 §8）
- `prowess_growth_count`（只在靜態 outcome 帶 `grow_prowess` 的 scripted 成功時 +1；每個選項成功後即從選單消失，所以總量有上限）
- `npc_scripted` 的 success／failure、delta、flag、記憶文字、備援敘事
- 選單：選項集合、順序、型別、意圖文字、可見性、玩家 index→選項的對應
- 所有靜態資料（NPC 事實、場景、成功率、hint）
- 每個回合是否「發生」（回合只有完整成功才計入 history／option_counts）

## 8. LLM-derived，但一旦套用就是 authoritative 的東西（灰色地帶）

這是架構上唯一「LLM 判斷變成真值」的地方，必須明確列出：

1. **`npc` 回合的 affinity delta**（Call2 ±1）。Python 只驗範圍，不驗語意。
2. **`mentioned_wang_debt` 的最後確認**：Python 決定「是否嘗試」（30% 擲骰，Call1 之前），但是否真的設旗標取決於 Call2 的 +1，且**不檢查敘事有沒有真的提到討債**。
3. **affinity → scripted 基礎成功率**：#1 的結果被 Python 規則用來選 30%／70%。骰子仍是 Python 的。

## 9. 純 LLM 產生的呈現層（presentation）

- Call1 的敘事文字（玩家看到的、history 裡的）
- 雲端的 `display_text`
- `npc` 回合的 `memory_note` 與其在 Qdrant 的內容、之後被檢索到的樣子
- history 裡 assistant 訊息中的 narrative／`memory_note`（scripted 回合的 `memory_note` 欄位是 Python 版，narrative 是 LLM 版或備援版）

---

## 10. 一個完整 turn：從 player input 到 state mutation

```
1.  main 迴圈印出 display_options（Python 選項，文字取 display_text 或原 text）
2.  玩家輸入數字 → 範圍檢查 → option = display_options[i]   # Python 物件，LLM 無法改動
3.  依 option["type"] 分支（§2）
    ├ scene / flavor：純 Python，更新 location / turn_count
    ├ npc:
    │   a. [老王] Python 擲骰決定是否帶鋪墊 hint
    │   b. Call1（含 Qdrant 檢索、history、flavor_hint）→ 解析 → 過濾 flags
    │   c. Call2（僅 narrative）→ delta 驗證
    │   d. 任一步失敗 ⇒ 整回合作廢，state/history 不動
    │   e. 印敘事 → commit history → 套用 flags → apply_turn_result（option_counts / affinity / turn_count / 記憶）
    └ npc_scripted:
        a. Python 擲骰 → outcome（authoritative）
        b. Call1 嘗試敘事；失敗/空 ⇒ 備援敘事（hint）
        c. 印敘事 → commit history(Python memory_note) → 套用 flag → apply_turn_result（delta / prowess / 記憶[Python]）
4.  apply_turn_result 內：delta≠0 ⇒ write_memory（embed → Qdrant PUT）
5.  render_options()：呼叫雲端換措辭（失敗 ⇒ 預設）→ 回到 1
```
哪些步驟**會讓整回合作廢**：只有 `npc` 路徑的 Call1／Call2 失敗。`npc_scripted` 路徑沒有任何 LLM 失敗可以作廢結果。

---

## 11. 已被 regression tests 保證的 invariants

（測試對應見 `TEST_COVERAGE_MAP.md`；所有測試以 mock 取代 Ollama／Qdrant／雲端，無網路）

| # | Invariant |
|---|---|
| I1 | Call1 無法設任何旗標（四種形狀的 `flags_set`）；額外 key 被忽略；型別錯誤／非法 JSON ⇒ 回合作廢且 state/history/turn_count 不變 |
| I2 | Call2 回傳範圍外／錯誤型別的 delta ⇒ 視為 0；Call2 不能設旗標或 prowess |
| I3 | `npc` 回合 Call2 失敗 ⇒ history、option_counts、affinity 都不變；重試後 history 只有成功那次 |
| I4 | 成功回合的 history 恰為一組 user＋assistant，且寫入內容與 `get_recent_narratives` 一致 |
| I5 | `npc_scripted` 成功後選項隱藏（`wang_debtor_trouble` 好感度不會重複 +3、`ayue_secret_money` prowess 不會重複成長）；失敗後選項保留可重試；`goto_ayue_home` 不受影響 |
| I6 | scripted 結果由骰決定，敘事寫反（失敗寫成收下／成功寫成拒絕）也不改變 state |
| I7 | **A6**：scripted 回合在 Call1 的八種失敗（亂碼、截斷、型別錯、null、`{}`、空白敘事、逾時、連線錯誤）下，成功／失敗結果都照常套用（好感度、旗標、prowess、option_counts、turn_count），玩家看到的是備援敘事；每次互動恰擲骰一次；「只在失敗時中止」的對手得不到任何好處（−1、−1、+1＝−1） |
| I8 | Call1 成功時 scripted 路徑行為不變（玩家讀到 LLM 敘事，備援不被使用） |
| I9 | **A7**：scripted 成功／失敗的 Qdrant 記憶、history 的 `memory_note` 恰為 Python 由 outcome 建立的版本；Call1 的惡意 memory_note 不會進 Qdrant、下一輪 prompt 或 history |
| I10 | 記憶單行、無【】，`npc` 回合的惡意 note 無法偽造 `【你們之間確實發生過的事】`；已存在 Qdrant 的舊多行資料在讀取時也被淨化 |
| I11 | 記憶不跨 NPC（Qdrant `npc_ids` 過濾；阿月的記憶不出現在老王的 prompt） |
| I12 | `mentioned_wang_debt`：擲骰沒中時，Call1 塞旗標、Call2 給 +1 都無法設旗標，hint 也不會注入 |
| I13 | **A11**：雲端不能新增／刪除／retype 選項；數量錯、id 錯／重複／未知、型別錯、空、過長、非 JSON、請求失敗、字串 `options` 全部 fallback；文字被收斂成單行 |
| I14 | 雲端改寫的措辭（含換行與假指令、與意圖矛盾的措辭、prompt injection）不會進入 Call1 prompt 或 history；玩家選的 index 即使在文字被換位後仍執行 Python 的選項，`location` 不變 |
| I15 | `display_text` 是菜單顯示文字，`text` 保持 Python 意圖 |

## 12. 目前仍存在、但「刻意接受」的風險

| 風險 | 為何接受 | 上界／現況 |
|---|---|---|
| **R1 好感度通道**：同一個模型寫敘事又判敘事，所以每個 `npc` 回合它實質能自選 ±1，進而把 scripted 成功率從 30% 推到 70% | 要根治必須做 `affinity_hard/soft` 分軌，是明確排除的大改動 | 骰子仍是 Python 的；±5 clamp；有 characterization 測試 |
| **R2 `npc` 回合記憶是 LLM 的轉述**，可能捏造或與事件不符 | Python 無法驗證語意；沒有任何邏輯讀記憶；已淨化結構 | 只影響敘事語氣，經 R1 間接影響 affinity |
| **R3 `mentioned_wang_debt` 不檢查敘事是否真的提到討債** | 檢查需要偵測敘事內容，違反「不做敘事一致性強制器」 | 仍受 30% Python 擲骰約束 |
| **R4 雲端措辭互換造成選單誤導** | 結構上無法偵測語意；行為不受影響 | 按下去執行的永遠是 Python 的選項 |
| **R5 scripted 回合的 history 保留 LLM 寫的 narrative**（可能與結果不符） | 顯示用，且 outcome 已由 Python 定案 | 下一輪 Call1 可能讀到矛盾上下文 |
| **R6 Ollama 離線時 scripted 選項仍會完成**（備援敘事） | 這是「結果由 Python 決定」的直接後果 | `npc` 型仍會因連線失敗而作廢 |
| **R7 state 只在記憶體**；Qdrant 持久 | MVP 範圍，MongoDB 尚未做 | 見 F1 |
| **R8 所有行為驗證都是 mock** | 本環境連不上外部服務 | 見 §14 |

## 13. 目前仍存在、但值得未來處理的問題

按「嚴重度 × 修復成本」粗排（只列已驗證存在、且不需要大型重構的）：

| # | 問題 | 位置 | 備註 |
|---|---|---|---|
| F1 | **Qdrant point id＝`turn_count`**，每次啟動從 0 開始：新局覆寫舊局同號記憶，同時舊局較大號的記憶保留，與全新 state 矛盾 | `:659` 起 | 影響核心賣點；`MVP_AUDIT.md` #1，**沒有測試**（FakeServices 以 id 為 key，會重現但目前沒寫） |
| F2 | **`conversation_history` 無上限**，每輪全送 `num_ctx=8192` 的 Ollama | `:833`、`:866` | 長局品質衰退；Ollama 超長時截哪一段**未驗證** |
| F3 | **`write_memory` 只攔 `RequestException`**；embed 回應缺 key 或空陣列（`KeyError`/`IndexError`）會逃出，`apply_turn_result` 在 `main` 內沒有 try，整個遊戲崩潰，且此時 affinity 已更新、history 已寫入 | `:659`、`:934` | 一行 `except Exception` 即可 |
| F4 | **Call2／Call1 對 `npc` 回合的選擇性中止**：任一方可在不想要的判定上拋錯，讓整回合作廢（只讓正向結果通過）。scripted 已修；`npc` 路徑沒有對應保護 | `:1067-1074` | 推論自程式碼，**無 reproducer 測試**；修法需決定 Call2 失敗時的語意（例如視為 delta 0 並仍記錄回合）|
| F5 | `npc` 回合：Call1 回 `{}` 前綴 ⇒ 空敘事，Call2 仍給 delta、空敘事被寫進 history | `:856-858`、`:1076-1088` | **有 XFAIL 測試** |
| F6 | 敘事含換行／`\x1b` 可偽造 UI 狀態列、清畫面 | `print_typewriter` | **有 XFAIL 測試** |
| F7 | `True`／`1.0` 通過 delta 驗證，affinity 變 float | `:902`、`:1081` | **有 XFAIL 測試** |
| F8 | `is_scripted_option_completed` 依賴 `outcome_above["flag"]`；若將來新增沒有 flag 的 scripted 選項，它會永遠不「完成」，一次性保護無聲失效 | `:588-595` | 目前三個 scripted 選項都有 flag，是潛伏條件，非現存 bug |
| F9 | 文件漂移：`CLAUDE.md`、`文字RPG架構決策.md` 未反映第二、三輪的行為（history 寫入時機、scripted 備援、`display_text`、雲端 id 格式） | — | 以本文件為準 |
| F10 | 場景／旗標導覽圖、`flavor`、`affinity_tier`、`prowess` 公式、記憶連線失敗路徑等幾乎沒有測試 | — | 見 `TEST_COVERAGE_MAP.md` §5 |

## 14. 本文件的限制

- 沒有真實 Ollama／Qdrant／雲端 API 的端到端驗證；所有「LLM 會這樣做」都是假設型（對手模型），不是觀察。
- 雲端 prompt 在第三輪改成要求 `{"id","text"}` 物件陣列，真實雲端模型是否照做**未驗證**；不照做的後果是每輪 fallback 回預設選項，遊戲照常可玩。
- `LLM_ASSIGNABLE_FLAGS = []` 造成 schema 的 `enum: []`，DEVLOG 記錄當時 Ollama 接受；升級後是否仍接受**未驗證**（Python 側過濾不依賴它）。
