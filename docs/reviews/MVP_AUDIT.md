# MVP_AUDIT.md

審查對象：`game_mvp.py`（1026 行，repo 中唯一的程式檔），對照 `CLAUDE.md`、`文字RPG架構決策.md`、`DEVLOG.md`。
審查方式：靜態閱讀。沒有跑遊戲，因為 Ollama、Qdrant 和雲端 API 在審查環境裡都連不上。
引用格式：`game_mvp.py:行號`。凡是「需要實際執行才能確認」的說法，都明確標成「未驗證」。
本輪沒有修改任何既有檔案。

## 0. 先講盤點結果

- repo 內容只有 `game_mvp.py`、`CLAUDE.md`、`DEVLOG.md`、`文字RPG架構決策.md`、`終極願景.md`、空的 `README.md`（0 行）。
- **沒有任何測試檔**。DEVLOG 裡的「已驗證」全是手動或臨時腳本的實測紀錄，腳本沒有進版控，所以沒有任何回歸保護。
- **沒有 `.gitignore`，也沒有 `.env.example`**（`ls -a` 與 `git ls-files` 均確認）。`game_mvp.py:22-24` 的 docstring 與 `CLAUDE.md` 都說有這兩個檔案，實際不存在。
- 沒有 `requirements.txt`，沒有存檔／讀檔機制。

## 1. 現在真正已經實作的功能

| 功能 | 位置 | 備註 |
|---|---|---|
| 7 個場景 registry，4 種選項型別（`npc`／`scene`／`flavor`／`npc_scripted`） | `:298-512`、`:920-1016` | 有實作，運作方式與文件描述一致 |
| 6 個 NPC，核心事實寫死 | `:113-171` | |
| Call1 敘事 + Call2 好感度（enum -1/0/+1，`temperature:0, seed:42`） | `:772-850` | |
| `requires_flag` 選項過濾 | `:565-570` | |
| `flags_set` 白名單，`FLAG_WHITELIST` 與 `LLM_ASSIGNABLE_FLAGS` 分離 | `:201-209`、`:221-224`、`:808` | `LLM_ASSIGNABLE_FLAGS` 為空，Call1 實質上無法設旗標 |
| `npc_scripted` 機率判定，prowess 修正與解析解成長曲線 | `:239-256`、`:933-975` | Python 端擲骰，只把結果餵給 Call1 |
| 老王「被討債人纏上」鋪墊（`flavor_hint`、30% 擲骰） | `:985-1016` | |
| Qdrant + bge-m3 長期記憶，寫入與查詢，依 `npc_ids` 過濾 | `:581-668` | 只在 `delta != 0` 時寫入（`:870`） |
| 雲端選項文字改寫，三條 fallback | `:515-578` | |
| JSON 括號深度解析、`strip_residue` | `:77-109` | |
| CLI 迴圈與打字機效果 | `:853-1026` | |

## 2. 設計文件有寫、但目前沒有實作

1. **`affinity_hard` / `affinity_soft` 雙軌**（架構 4.6）。現在只有單一 `affinity`，而且門檻判斷直接用 Call2（LLM）寫出來的值，正好違反 4.6 的原則「只有 hard 參與門檻，soft 不觸發任何 flag」。詳見 §3-A。
2. **選項預生成／背景緩衝**（4.3、4.5）。完全沒有，每回合都是同步依序呼叫。
3. **自訂輸入格**（第 8 節整章）。隱藏觸發詞、NPC 別名表、意圖解析 Call A、unsupported 分支都不存在。
4. **MongoDB 與存檔**（5.4）。state 是記憶體 dict，沒有 `version`、沒有存檔。Qdrant 卻是持久的，兩者壽命不一致，見 §4-1。
5. **`npc_affinity_delta` 動態 key 結構與 Mongo 注入防護**。實作改成單一 `affinity_delta`，這條防護目前不需要（可視為合理偏離，但文件沒更新）。
6. **state 結構中的 `stats`／`inventory`／`status`／`last_seen_turn`**（5.2）。沒有實作，MVP 範圍內可接受。
7. **記憶寫入條件「`flags_set` 非空或 delta 非零」**（5.5）。實作只看 delta；而 `flags_set` 對 LLM 永遠是空的，所以旗標本身從不觸發寫入。`tags` 欄位永遠是 `[]`（`:633`）。
8. **無對象時的全域語意搜尋**（5.5）。`query_memories(..., npc_id=None)` 分支從沒被呼叫過（`:781-782` 一律帶 NPC）。
9. **recency 衰減**。文件明確標為待實測，不算缺漏。
10. **`SCENES[...]["npcs"]` 沒有被任何程式讀取**。CLAUDE.md 已承認，不重複。
11. **文件名稱漂移**。文件和註解仍有「`OPTIONS`」「`NPC_REGISTRY`」「`state_delta`」等舊名稱，實際分別是 `SCENES`、`NPCS`、`NARRATIVE_SCHEMA` + `AFFINITY_SCHEMA`。

## 3. 看似「LLM 只敘事、Python 決因果」，實際上 LLM 仍能間接影響 state

### A. Call2（LLM）的 delta → 好感度 → 關鍵旗標的成功率
- `npc` 型選項的好感度完全由 Call2 讀 narrative 決定（`:844`、`:1008-1016`）。
- 這個好感度再決定 `npc_scripted` 的基礎成功率 70/30（`:941-945`），而成功與否決定 `offered_help_ayue`／`helped_wang_debt` 旗標（`:963-964`）。
- 所以「關鍵旗標觸發」雖然由 Python 擲骰，但骰子的機率是 LLM 判定的好感度。「100% 由規則決定」只在擲骰那一步成立，不涵蓋輸入。
- DEVLOG 自己記錄過 Call2 對同一段敘事會判出不同結果（`DEVLOG.md:22`），目前用 `temperature:0` 與 `seed:42` 壓制，但沒有消除。
- 這就是 4.6 設計要避免的問題，只是現在把它降級成「機率偏移」而不是「直接觸發」。

### B. `mentioned_wang_debt` 的觸發取決於 Call2，且不驗證敘事有沒有真的提到
- `debt_mention_attempted and delta == 1`（`:1013`）：旗標由 Python 擲骰加 Call2 的 delta 共同決定。
- **沒有任何檢查 Call1 有沒有真的把 `flavor_hint` 寫進敘事**。Call1 如果忽略 hint，旗標照樣設定，玩家就看到選項「老王被討債的人纏上」憑空冒出來，這正是 `:340` 註解想避免的情況。
- 反方向也成立：hint 已寫進敘事，但 delta 不是 +1，旗標沒設，下一輪又重擲，可能重複提起。

### C. 記憶通道：Call1 的 `memory_note` → Qdrant → 下一輪 prompt
- `memory_note` 是 Call1 的自由文字（`:679-682`），只擋「看起來像 JSON dict」（`:614-617`）。
- 它被當成「你還記得的事」注入未來 prompt（`:728-731`），而且 prompt 明說「會自然影響你現在的反應」。
- `npc_scripted` 回合裡 Call1 不一定遵守 `scripted_outcome`（沒有任何比對）。例如規則判失敗（拒收），Call1 卻寫成收下，memory_note 就記下一個與 state 相反的「事實」。
- 這條記憶之後可以繞過 `FLAG_FACTS`／旗標的白名單機制，讓 NPC 在敘事上承認某件 state 裡沒發生的事，再經 Call2 影響好感度。**文件的「narrative 只能是 state 之後的產物」只被單向保證，沒有被驗證。**

### D. 雲端選項文字改寫直接變成玩家動作
- `render_options()`（`:573-578`）用雲端模型的輸出覆寫 `opt["text"]`，之後 `action = option["text"]`（`:935`、`:978`）直接當作「玩家的動作」餵給 Call1 並存進 history。
- 雲端模型被允許自由改寫，沒有任何語意檢查。例如把「偷偷塞錢」改成語氣強硬的句子，Call1 看到的動作語意就變了，但 `outcome` 仍是原本規則決定的。
- 這是比 LLM 輸出 JSON 更少被注意到的一條外部輸入。

### E. 這幾點是 Python 的設計缺口，不是 LLM 的問題，但同樣能破壞「規則決定因果」
- **`npc_scripted` 選項沒有「一次性」保護**（`:933-975`）：旗標設定後選項仍然可見、可重複選。
  - `wang_debtor_trouble` 成功是 +3 好感度（`:357`），可以無限刷到 +5 上限。
  - `ayue_secret_money` 成功時每次都 `grow_prowess`（`:335`），可以無限刷 prowess。
  - CLAUDE.md 稱這類轉換為「一次性、不可逆」，但程式只有「旗標設過」這個事實，沒有任何地方擋重複觸發。
  - 敘事上也會自相矛盾，例如「討債人纏上老王」演第二次。

## 4. 最容易出現記憶污染、錯誤旗標、好感度錯判、劇情矛盾的地方

1. **記憶跨局污染與靜默覆寫（嚴重）**
   - Qdrant point id 是 `state["turn_count"]`（`:625`），而 state 每次啟動都從 0 開始（`:174-192`），Qdrant 是持久的（NAS）。
   - 後果一：新局的第 1..N 回合會覆寫舊局相同 id 的記憶，舊記憶無聲消失。
   - 後果二：舊局 id 比較大的點會留下來，被新局撈到。新局 state 的旗標、好感度都是 0，卻讀到「你曾經幫過她」之類的舊局記憶，直接與 state 矛盾。
   - `ensure_memory_collection()`（`:585-598`）只建 collection，從不清空，也沒有 session 識別。
2. **Call2 失敗後的 history 汙染**
   - `call_narrative_llm()` 在回傳前就把 user／assistant 訊息寫進 `history`（`:809-818`）。
   - 一般 `npc` 路徑中，之後 `call_affinity_llm()` 若丟例外（逾時、解析失敗），main 印「生成失敗」後 `continue`（`:1001-1003`）。玩家從沒看過這段敘事，但它已經留在該 NPC 的對話歷史裡，並影響後續 prompt。
   - `option_counts` 也不一致（沒更新，但 history 已多一輪）。
3. **對話歷史無上限**
   - `conversation_history[npc_id]` 只增不減（`:287`、`:809-818`），每回合整包送進 Ollama，`num_ctx` 只有 8192（`:796`）。
   - 每輪約 300–500 tokens 的話，單一 NPC 十幾輪就可能逼近上限（估算，**未驗證**實際 token 數）。
   - 溢位時 Ollama 會截斷哪一段（system prompt 還是舊對話）**未驗證**。若截到 system prompt，核心事實會悄悄消失。
   - 長局下這是品質衰退的主要來源。
4. **`write_memory` 在 try 之外會讓整個遊戲崩掉**
   - `apply_turn_result()` 在 main 裡沒有 try 包覆（`:965`、`:1016`），而 `write_memory` 只攔 `RequestException`（`:641`）。
   - `embed_text` 回傳的 JSON 缺 `embeddings`、陣列為空，會丟 `KeyError`／`IndexError`（`:604`）→ 整個程式結束。
   - 此時 affinity 已被更新（`:866`），state 與記憶不一致。
5. **空敘事照樣套用好感度**
   - Call1 回傳 `narrative: ""`（或 `strip_residue` 之後變空）時，`result.get("narrative", default)` 取到的是 `""`，不是預設值（`:1005`），玩家看到空白，但 Call2 仍對這段空字串給出 delta 並寫入 state。沒有任何長度或內容檢查（80–150 字只存在 prompt 裡）。
6. **delta 型別驗證用 `in (-1,0,1)`**（`:839`、`:1009`）
   - `True`、`1.0` 都會通過，進入 `clamp` 後可能讓 affinity 變成 float（顯示 `3.0`）。
   - 在 Ollama grammar 約束下發生機率低，但這道「Python 側雙重保險」並沒有它宣稱的嚴謹。
7. **`mentioned_wang_debt` 的可見性問題**
   - 見 §3-B。這是目前最容易讓玩家覺得「選項憑空冒出」的路徑。
8. **cloud 選項順序錯位**
   - `zip(current_options, fresh_texts)`（`:577`）完全靠位置配對。只檢查數量（`:556`），不檢查語意。
   - 模型只要把兩句順序換掉（數量仍然對），玩家看到「走回街道」，執行的卻是 `ayue_secret_money`。結構沒壞，語意全錯，不會觸發 fallback。
9. **跨場景共用同一份 NPC 對話歷史**
   - 阿月在酒館與阿月家共用 `conversation_history["npc_ayue"]`。換場景後舊敘事（在酒館端酒）會被當作上下文，與 `scene_atmosphere` 競爭。
   - CLAUDE.md 已知並用場景氛圍壓制，但只靠 prompt，不是結構保證。
10. **affinity ↔ 敘事回饋迴路**
    - `affinity_tier` 餵給 Call1，Call1 的敘事再被 Call2 判成 delta，形成自我強化的閉環。CLAUDE.md 已知道並用鬆動措辭緩解，這是已接受的限制，列在此處只為完整。

## 5. 惡意／錯誤／「格式對但語意錯」的 JSON，現有防線與破口

### 擋得住的
| 攻擊 | 防線 |
|---|---|
| Call2 回傳 `affinity_delta: 99` 或字串 | `:839`／`:1009` 的白名單檢查 → 視為 0（但 `True`／`1.0` 會漏過，見 §4-6） |
| Call1 `flags_set` 塞任意旗標 | `:808` 用 `LLM_ASSIGNABLE_FLAGS`（空）過濾，再經 `apply_flags` 的 `FLAG_WHITELIST`；兩層都擋 |
| 在 JSON 外夾帶廢話、markdown | `parse_llm_json` 括號深度解析（`:86-109`）；格式殘渣用 `strip_residue` 擋 |
| JSON 內文夾帶 `{}` | `in_string` 狀態處理字串內的括號 |
| `memory_note` 偽裝成 dict 物件 | `:614-617` 擋掉 |
| 未知 NPC id 污染 state | 沒有動態 key；LLM 無法指定 NPC |
| LLM 無法塞數字欄位改 hp／gold | schema 無此欄位，state 也無此欄位 |

### 擋不住的（格式正確、語意錯誤）
1. **敘事與規則結果相反**：沒有任何機制檢查 Call1 是否照著 `scripted_outcome` 寫（§3-C）。
2. **narrative 內容本身**：可以是任何字串（含空、超長、非中文、含換行與控制字元），不檢查。
3. **`memory_note` 的內容真偽**：只擋 dict 形狀，不擋捏造事實（§3-C）。
4. **Call2 的語意誤判**：enum 合法但判錯方向，直接進 state（§3-A）。這是設計上刻意接受的隨機性，但它會進一步影響後續機率。
5. **非字串型別**：`narrative` 或 `memory_note` 若為 list／number，`strip_residue` 的 regex 會丟 `TypeError`，被通用 except 吃掉，變成「生成失敗」（失敗而不是被污染，算安全，但回合白白浪費）。`flags_set: null` 同理。
6. **雲端選項回傳**：`options` 若是長度剛好相同的字串，會被當成字元序列迭代，每個「選項」變成單一字元（`:555-559`，**未實測**）；內容、順序、長度均不檢查（§4-8）。
7. **空 enum 的相容性**：`NARRATIVE_SCHEMA` 的 `flags_set.items.enum` 是 `[]`（`:685`）。JSON Schema 規範通常要求 enum 至少一個元素。DEVLOG（`:622`）記錄當時實測 Ollama 能正常回 `[]`，但這是依賴 Ollama 目前版本的未文件化行為，升級後可能改變，**本次未能複驗**。

## 6. 最值得修的前 5 個問題（嚴重程度 × 修復成本）

| # | 問題 | 嚴重度 | 修復成本 | 建議方向（僅描述，這輪不動手） |
|---|---|---|---|---|
| 1 | **記憶 id 跨局碰撞與跨局污染**（§4-1） | 高：直接破壞專案核心賣點「記得玩家做過的事」，還會讓記憶與 state 矛盾 | 低 | 用 UUID／session 前綴產生 point id，並在 payload 加 `session_id`，查詢時過濾；或啟動時清空 collection。幾行改動 |
| 2 | **`npc_scripted` 可無限重複**（§3-E） | 高：好感度、prowess 可刷滿，直接破壞「一次性關鍵劇情」的設計前提 | 低 | 選項帶 `once: true`，旗標已設就從 `get_visible_options` 排除（機制已存在，擴充一個條件即可） |
| 3 | **缺 `.gitignore` 與 `.env.example`**，雲端 API 金鑰無保護 | 中高：`git add .` 就可能把金鑰推進版控 | 極低 | 新增 `.gitignore`（含 `.env`）、`.env.example`、README 基本啟動說明 |
| 4 | **Call2 失敗後 history 已寫入；對話歷史無上限**（§4-2、§4-3） | 中高：長局品質衰退，且玩家沒看過的敘事會影響後續 | 低到中 | 把 history 的 append 延後到整個回合成功之後；history 只保留最近 N 輪。不需新增系統 |
| 5 | **雲端選項文字與選項身分只靠位置配對，且無語意檢查**（§3-D、§4-8） | 中：畫面與實際動作不符；也是 LLM 輸出直接進入 prompt 的缺口 | 低 | 改要求雲端回傳帶 `id` 的物件並比對 id 集合；`scene`／`flavor` 型選項不送雲端改寫，只改寫 `npc`／`npc_scripted` 型 |

排序理由：#1、#2 同時符合「傷害直接而且重大」與「幾行就能改」；#3 成本趨近於零但屬於「出事就無法挽回」的類型；#4、#5 是品質與一致性問題，成本略高。

### 沒進前 5，但值得記住的
- `mentioned_wang_debt` 不驗證敘事有沒有提到（§3-B），修法需要偵測敘事內容，違反「不要做敘事一致性強制器」，建議維持現狀並接受。
- `write_memory` 的未攔截例外（§4-4）可併入 #4 一起處理，改成 `except Exception`。
- 空敘事視為失敗（§4-5）：一行檢查即可，建議順手併入 #4。
- `delta` 改用 `type(delta) is int`（§4-6）：一行。

## 7. 明確「不建議現在做」的事

依照本輪要求，以下都不建議為了未來願景現在加入：
- 雙軌好感度（`affinity_hard`／`soft`）全面重構。若 §3-A 的機率偏移之後在 playtest 中造成問題，再處理即可，現在不需要。
- MongoDB 與完整存檔系統。只需要先解決 §6-1 的 id 碰撞。
- 自訂輸入格、預生成緩衝、敘事一致性檢查器。
- 把 LLM 的 `memory_note` 改成經 Python 模板重寫：成本大，且與「抽象摘要」原則有拉扯，先不動。

## 8. 審查限制

- 沒有實際執行任何呼叫。凡涉及 Ollama 截斷行為、Qdrant upsert 語意、雲端模型實際輸出行為的結論，都標為推論或未驗證。
- DEVLOG 的實測數據只被當作證據引用，沒有重現。
- 沒有測試檔，因此無法評估「改動會不會破壞既有行為」；建議之後為 `apply_flags`、`get_visible_options`、`resolve_scripted_outcome`、`parse_llm_json` 這類純函式補最小單元測試（不需要 LLM 就能跑），這屬於修復的前置條件，不是新系統。
