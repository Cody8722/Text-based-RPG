# OPUS_INDEPENDENT_REVIEW.md

第二意見審查。對象是工作目錄目前的 `game_mvp.py`（1098 行，含未 commit 的第二、三輪修復）與 `tests/` 的 53 個測試。
既有的 `MVP_AUDIT.md`、`CAUSALITY_ATTACK_REPORT.md`、`CURRENT_ARCHITECTURE.md`、`TEST_COVERAGE_MAP.md` 只當參考，**每一條結論都重新對照程式碼，或用臨時 mock 腳本實測**。
臨時腳本放在 session scratchpad，**沒有進 repo**；本輪沒有修改任何檔案，只新增這份文件。下面每個發現都附了可重現的做法。

---

## 1. 獨立重建的 data flow

我逐行追過 `main()`（`:955-1090`）。結論與 `CURRENT_ARCHITECTURE.md` §2 **基本一致**；以下只列那份文件沒寫清楚、或我認為說錯的地方。

```
input() ──► choice.isdigit() ──► int(choice) ──► display_options[i]        :970-980
   │            （isdigit 接受 ²、① 等，int() 會拋 ValueError → 程式結束，見 O4）
   ▼
display_options = render_options()                                           :607
   └─ 雲端失敗時直接回傳 SCENES 裡的同一批 dict（不是副本）；成功時是 {**opt, display_text}
   ▼
[npc]       debt 擲骰 → call_llm(Call1 → Call2) ─(例外)─► continue（全部作廢）
            → print_typewriter(narrative)      ← 在 try 之外（見 O4）
            → commit_turn_history(原始 memory_note，未淨化，見 O5)
            → apply_flags → apply_turn_result
[scripted]  resolve_scripted_outcome（擲骰）→ try Call1 except Exception → 備援敘事
            → print_typewriter(narrative)      ← 在 try 之外
            → commit_turn_history(Python note) → apply_flags → apply_turn_result
apply_turn_result（:923）的寫入順序：
   option_counts → affinity → turn_count → write_memory(Qdrant，可能拋出未攔截的例外)
   → 好感度訊息 → prowess 成長 → 狀態列
```

**authoritative state 的來源**（全檔 grep 確認，只有這些寫入點）：
`location`（`:984`，靜態 target）、`turn_count`（`:985`、`:992`、`:930`）、`flags`（`:224`，白名單）、`prowess_growth_count`（`:947`，靜態 `grow_prowess`）、`affinity`／`option_counts`（`:928-929`）。
沒有任何一個寫入點直接讀 LLM 字串。LLM 進入 state 只有兩條路：Call2 的 `delta`，以及 `delta==1` 對 `mentioned_wang_debt` 的放行。這兩條都屬於既定的設計通道。

**既有文件沒有寫的一點**：架構裡存在**第三種 state：Qdrant**。它是持久的，而且會在下一輪被當成 NPC 的記憶注入 system prompt。但它的生命週期與 `state` 完全脫鉤（見 O1）。文件把它歸類為「不影響 state 的呈現層」，**單一 session 內是對的，跨 process 就不對了**。

---

## 2. 發現（最多 10 個）

嚴重度依「在目前設計範圍內，實際破壞了什麼」評定。刻意接受的通道（Call2 的 ±1、affinity 影響 scripted 機率）不列為漏洞。

### O1 — 重啟後，Python 自己寫的記憶與 Python 的 state 互相矛盾（跨 session 記憶復活）　**High**
- **攻擊情境**（不需要惡意 LLM，正常遊玩就會發生）：
  1. 第一局成功「偷偷塞錢」，於是 `offered_help_ayue` 成立，Qdrant 寫入一筆 Python 撰寫的事實：「玩家…塞了一筆錢給阿月…阿月坦然收下了」。
  2. 關掉程式後重開：`state` 歸零、旗標消失、選項重新出現；Qdrant 原封不動。
  3. 第二局跟阿月打招呼，system prompt 的「【你還記得的一些事】」裡就是上一局的成功事件。
  4. 第二局第 1 回合寫入的記憶，又會以 point id `1` **覆寫**舊局的第 1 筆，而舊局 id 較大的記憶照常保留。結果記憶集合取決於兩局各走了多遠，是不可預測的混合。
- **程式路徑**：`state` 只存在記憶體（`:174`）；`write_memory` 以 `turn_count` 為 point id（`:659` 起）；`query_memories` 只用 `npc_ids` 過濾（`:698`）；沒有任何 session 識別。
- **實測**（mock）：用同一個假 Qdrant 跑兩局，中間重置 `state`。結果第二局 `flags == {}`、`ayue_secret_money` 仍在選單上，但 prompt 含上一局的成功 hint。另以預存的 id 1、5 開新局，id 1 被覆寫、id 5 保留。
- **為什麼既有測試抓不到**：每個測試都建立新的 `FakeServices()`，從來不模擬「state 重置、Qdrant 保留」。
- **與既有文件的差異**：`MVP_AUDIT`／`CURRENT_ARCHITECTURE` 把它記成「point id 碰撞」（F1）。真正的問題比較嚴重：**A7 的修復讓殘留記憶變成 Python 的權威措辭**。過去殘留的是 LLM 的轉述，現在殘留的是 Python 自己的結論，卻與 Python 目前的 state 矛盾。這直接違反 A7 自己的要求「memory 必須反映 Python 已確認發生的結果」，只是發生在 process 邊界上。
- **純 mock 可重現**：是。
- **最小修復方向**：每次啟動產生一個 `session_id`（例如 `uuid4`）寫進 payload，查詢時一併過濾，point id 改用 UUID。MVP 也可以退而求其次，在啟動時清空 collection。兩者都只是十行以內的修改。
- **值得現在修嗎**：**是**。否則真實 E2E 每跑一次，就會污染下一次的結果。

### O2 — 「一次性」測試觀察的是輔助函式，不是玩家實際看到的選單　**High（false confidence）**
- **問題**：`run_main_choosing`／`AttackCase.play` 決定「選第幾個」與「選項還在不在」時，用的是 `get_visible_options(SCENES[...])`，**不是 `main()` 實際持有、實際印出的 `display_options`**；而 `print` 又被全域 mock 掉。也就是說，測試的 oracle 本身就預設答案是對的。
- **實測**：把 `render_options` 換成「不過濾已完成選項」（模擬 production bug：選單會重新列出已完成的 scripted 選項，玩家可以再選），結果 `ScriptedOneShotTests` 與 A6 共 **9/9 全部通過**。
- **連帶的設計問題**：一次性保護只有一層，就在 `render_options` → `get_visible_options`；`main()` 的 scripted 分支（`:996`）本身不檢查是否已完成。任何讓選單過期的改動（例如之後新增某個 `continue` 路徑時忘了重新 render）都會在測試全綠的情況下，讓 `MVP_AUDIT.md` §3-E 的重刷漏洞（重複 +3 好感度、重複成長 prowess）復活。
- **純 mock 可重現**：是。
- **最小修復方向**：測試從 `render_options()` 的回傳值（包一層記錄器即可）或印出的選單取得選項列表，不要用輔助函式當 oracle。production 端可再加一行防禦：scripted 分支開頭若 `is_scripted_option_completed(option)` 就 `continue`。
- **值得現在修嗎**：**是**（主要是測試的修改，成本很低）。

### O3 — 沒有任何測試驗證 Call1 被告知的是「正確的」結果　**Medium-High（false confidence）**
- **問題**：scripted 的核心承諾是「Python 決定結果，Call1 照著講」。但 state 正確、卻把相反的 hint 交給 Call1，這種 bug 完全沒有測試會失敗。現有斷言 `assertIn("偷偷塞了一筆錢", system_prompt)` 同時符合成功與失敗兩個 hint（兩句開頭相同）。
- **實測**：把 `call_narrative_llm` 包一層，讓 `scripted_outcome` 換成另一側的 hint，所有涉及 scripted 的測試類別共 **44 個全部通過**。
- **影響**：真實遊玩時，玩家會看到「阿月收下了」，但旗標和好感度都是失敗的結果；而這段敘事會進入 history（R5）。
- **純 mock 可重現**：是。
- **最小修復方向**：在成功和失敗兩條路徑上，各斷言 `outcome_above/below["hint"]` 完整出現在 Call1 的 system prompt。測試只需加兩行。
- **值得現在修嗎**：**是**。

### O4 — `try` 之外的例外會直接殺掉 process；而 state 在記憶體裡，所以一次崩潰＝整局全失　**Medium（E2E 前必看）**
新的攻擊類別是「**把 process 弄死，就等於把 state 回滾到零**」，而 Qdrant 不會跟著回滾（因此會餵給 O1）。實測可觸發的路徑：

| 觸發 | 路徑 | 實測 |
|---|---|---|
| **LLM 敘事含 cp950 無法編碼的字**（簡體字「这」「们」、emoji），而 stdout 不是 UTF-8 | `print_typewriter(narrative)` 在 try 之外（`:1027`、`:1076`） | 以 cp950 strict 的 stdout 執行 `npc` 回合，`UnicodeEncodeError` 逃出 `main` |
| 雲端 `display_text` 含同類字元 | 選單 `print`（`:967`） | 同上（由程式碼推得） |
| 玩家輸入 `²`、`①` | `isdigit()` 為真但 `int()` 拋 `ValueError`（`:976`） | `main()` 直接結束 |
| stdin 結束（自動化 E2E 用 pipe 餵輸入） | `input()` 拋 `EOFError` | 以 traceback 結束，不是乾淨退出 |
| embed 回應缺 key／空陣列 | `write_memory` 只攔 `RequestException`（`:659`），`apply_turn_result` 沒有 try | 既有 F3（由程式碼推得） |

- **為什麼既有測試抓不到**：所有測試都 mock 掉 `builtins.print` 與 `print_typewriter`，輸入一律是 ASCII 數字並以 `"0"` 結束。
- **與因果的關係**：在 `apply_turn_result` 裡，`write_memory` 發生在 prowess 成長和狀態列之前。若在 `write_memory` 之後崩潰，Qdrant 已有一筆記憶，但這一局的 state 全部消失。cp950 的條件在 Windows 上相當常見：pipe、重新導向（例如 `python game_mvp.py | tee log.txt` 留紀錄）、Git Bash。qwen 又經常吐出簡體字。
- **純 mock 可重現**：是（全部）。
- **最小修復方向**：
  - 啟動時呼叫 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`；
  - 輸入改用 `choice.isdecimal()`，或用 `try: int(...)`；
  - `EOFError` 視同選了 `0`；
  - `write_memory` 改成 `except Exception`。
  每一項都只是一兩行。
- **值得現在修嗎**：**是，至少前兩項要在 E2E 之前修**。

### O5 — A7 的「防偽造區塊標題」是兩個字元的黑名單，而且只套在 Qdrant 那條路　**Medium（false confidence＋文件過度宣稱）**
- **實測**：
  - `〖你們之間確實發生過的事〗…`、`［你們之間確實發生過的事］…`、`你們之間確實發生過的事：…` 都**原封不動**進入下一輪 system prompt（`sanitize_memory_text` 只移除 `【】`）。
  - `npc` 回合的 `commit_turn_history` 存的是**未淨化的原始 `memory_note`**（`:1077` → `:866`），含換行與 `【你們之間確實發生過的事】`。下一輪 Call1 會在「自己上一則 assistant 訊息」裡看到它。
- **為什麼既有測試抓不到**：I10 的測試只斷言 `"【" not in text`，而且只檢查 Qdrant 與 system prompt，不檢查 history。
- **評價**：語意偽造本來就是已接受的 R2；**錯的是宣稱**。`CURRENT_ARCHITECTURE` §6 寫「不可以：偽造【你們之間確實發生過的事】這類區塊」，實際上只擋住一種括號字元。這也與專案自己的原則「黑名單式事後糾錯打不贏」直接衝突。單行化與長度上限才是真正有價值的部分。
- **純 mock 可重現**：是。
- **最小修復方向**：**不要再加更多括號到黑名單**。修正文件，把保證降為「單行、≤200 字」。如果想縮小攻擊面，最便宜的結構性做法是 history 的 assistant 訊息不要放 `memory_note`，只放 narrative（一行修改；記憶本來就走 Qdrant）。
- **值得現在修嗎**：文件要修；程式碼可選。

### O6 — CLAUDE.md 標為「勿省略」的執行設定沒有任何測試保護　**Medium-Low**
- `think: False`、`num_ctx: 8192`、Call2 的 `temperature: 0`／`seed: 42`、`format` schema：假服務對 payload 完全不檢查，`grep` 測試檔也找不到 `think`／`num_ctx`。任何重構只要拿掉其中一個，53 個測試仍然全綠；而 CLAUDE.md 記錄的實測顯示，這些設定一缺就會讓輸出管線或效能崩壞。
- **純 mock 可重現**：是（檢查假服務收到的 payload 即可）。
- **最小修復方向**：寫一個測試，斷言兩種呼叫的 payload 都帶這些欄位。
- **值得現在修嗎**：是，成本極低，而且能讓 E2E 的基準條件保持固定。

### O7 — delta 的型別強制轉換範圍比 XFAIL 寫的更大　**Low**
- **實測**：`NaN`、`Infinity` 會變成 0（安全，因為 `json.loads` 接受它們，但 `in (-1,0,1)` 為假）；`true` 變成 int 1（無害）；**`-0.0`、`1e0` 會讓 affinity 變成 float**。F7 的 XFAIL 只測了 `1.0`。
- **影響**：只會污染型別，數值語意不變。
- **最小修復方向**：與 F7 同一行，改成 `type(delta) is int`。
- **值得現在修嗎**：順手修即可。

### O8 — 對既有分析的修正：`npc` 路徑的「選擇性中止」（F4）並不是漏洞　**Low（重新分類）**
- Call2 本來就可以合法輸出 0 或 +1；用中止來「避開 −1」的效果，嚴格來說比直接輸出 0 還弱（同時放棄了 +1 與記憶寫入）。Call1 中止唯一多出來的效果，是重擲那 30% 的鋪墊嘗試；而這個嘗試最後是否成立，本來就由 Call2 的 +1 決定，LLM 早就能控制。
- **結論**：沒有超出設計通道的能力。scripted 路徑的 A6 是真的漏洞（當時 Python 已擲好骰），`npc` 路徑沒有對應的問題。**建議從待修清單移除 F4**，不要為它建立新語意。

### O9 — 弱斷言、恆真測試與假服務的保真度　**Low（false confidence）**
- `test_call2_failure_leaves_history_untouched` 直接呼叫 `call_llm`。第二輪之後 `call_llm` 依設計就不碰 history，所以這個測試**恆真**，不管 `main()` 的行為如何都會通過（真正的保護是 #2、#4）。
- `test_failed_attempt_can_be_retried` 只斷言「oracle 選了 2 次」，沒有斷言 `option_counts==2` 或 affinity 被扣兩次。
- A6 的 `RollCounter` 只計算 `random.randint` 的呼叫次數；如果 production 改用其他亂數 API 重擲，測試看不出來。
- 假 Qdrant 用 3 維向量（真實 collection 是 1024 維，真實 Qdrant 會拒收），而且不做相似度排序。記憶的寫入與檢索在真實環境的行為完全沒有被驗證。
- **值得現在修嗎**：等下次修改測試時一起處理。

### O10 — scripted 的 `except Exception` 會把程式 bug 偽裝成「正常的備援敘事」　**Low**
- **實測**：讓 `build_system_prompt` 拋出 `NameError`。這次測試**有抓到**（`test_successful_call1_path_is_unchanged` 失敗，`npc` 路徑的測試出錯），所以測試面沒問題。
- **真正的風險在 E2E**：如果 Ollama 拒收 `enum: []` 的 schema，或 payload 有其他問題，**每一次** scripted 回合都會「正常完成」並顯示 Python 的第三人稱 hint。旗標、好感度照樣變化，遊戲看起來能玩，實際上 Call1 從來沒成功過。
- **最小修復方向**：保留這個 catch，但讓失敗可被量測，例如記錄例外類型並累計次數；E2E 時把「[敘事生成失敗」出現的次數當成必看指標。
- **值得現在修嗎**：程式碼不必急著改；E2E 的觀察清單一定要列入。

---

## 3. Verdict

### A. 目前架構是否真的達到「LLM narrator / Python authoritative」？
**在單一 process 內：是。跨 process：否。**
- 單一 session 內，我找不到 LLM 能越過設計通道（Call2 ±1、affinity 影響機率）去改變 `flags`／`prowess`／`location`／scripted 結果的路徑。A6 的修復確實關閉了 scripted 的重擲；數值邊界（NaN、Infinity、bool）也守得住，只有 float 型別污染。
- 但 Qdrant 是第三種 state，壽命比 `state` 長。重啟後，Python 自己寫下的結論會與 Python 當下的 state 矛盾（O1）。另外，Call1 敘事與 Python 結果是否一致，**完全沒有被測試驗證**（O3）。

### B. Sonnet 已修掉的東西，有沒有修錯或過度修復？
沒有修錯的。有兩處副作用和一處過度宣稱：
- **A7 的副作用**：把 scripted 記憶改成 Python 措辭本身是對的，但在沒有 session 隔離的情況下，反而讓跨局殘留變成「權威事實」（O1 的加重因素）。
- **A7 的過度宣稱**：括號黑名單被描述成「無法偽造區塊標題」；實際上可輕易繞過，而且 history 那條路根本沒有淨化（O5）。
- **A6 的副作用**：`except Exception` 加上 Ollama 斷線時照常推進，方向正確，但會讓 Call1 完全壞掉的情況看起來像遊戲正常（O10）。這是可觀測性問題，不是修錯。
- **一次性修復**：正確但只有一層，而測試沒有觀察那一層（O2）。
- **F4 被高估**，不應該修（O8）。
- A11 的 id 協定是實質改進。我沒有發現過度修復；唯一的小代價是內部 option id（例如 `wang_debtor_trouble`）會送給雲端模型，影響可忽略。

### C. 最值得修的前三個
1. **O1 跨 session 記憶**：加 `session_id` 過濾（或啟動時清空）。不修的話，真實 E2E 的結果無法解讀。
2. **O4 process 被殺的路徑**：至少修 stdout 編碼和輸入轉換（兩行）。這是 Windows 上 E2E 最可能直接撞到的崩潰。
3. **O3＋O2 測試 oracle**：斷言 Call1 收到正確的 hint，並且從實際選單取得選項。兩者都只改測試，能讓「一次性」與「敘事順著結果寫」這兩個核心承諾真正受到保護。

（O6 的 payload 設定測試成本更低，建議一起做。）

### D. 如果現在直接開始真實 Ollama＋Qdrant＋cloud 的 E2E，我最擔心看到什麼？
1. **在 Windows 上、輸出被 pipe 或 tee 留紀錄時，第一個含簡體字的敘事就讓遊戲崩潰**（O4）。很容易被誤判成「Ollama 不穩」。
2. **Call1 全面失敗，但 scripted 看起來一切正常**：例如 Ollama 拒收 `enum: []`，`npc` 回合全部顯示「生成失敗」，scripted 回合卻全部用備援 hint「成功推進」（O10）。必須統計「[敘事生成失敗」的出現次數。
3. **第二次以後的 E2E 被上一次的記憶污染**：NPC「記得」這一局沒發生過的事，或是記憶時有時無（O1）。每次跑之前都必須清空 collection。
4. **雲端選項幾乎每輪都 fallback**：新的 `{"id","text"}` 格式沒有用真實模型驗證過，再加上最長 30 秒的 timeout，會讓每一輪都卡頓。
5. **長局之後 history 超過 `num_ctx` 8192**：品質衰退的原因會很難判斷（Ollama 截斷了哪一段沒有驗證過）。
6. **自動化 harness 用 pipe 餵輸入時，結尾變成 `EOFError` traceback**（O4），容易被誤讀成測試失敗。

---

## 4. 本審查的限制
- 全部是靜態閱讀加 mock 實測，沒有真實外部服務。cp950 崩潰是以 `TextIOWrapper(encoding="cp950")` 模擬的 stdout 重現；真實 Windows 主控台（非 pipe）在 Python 3.13 下以 UTF-16 輸出，**不會**觸發。
- Ollama 在 context 溢位時保留哪些訊息，**未驗證**。
- 實驗腳本只在 session scratchpad，沒有加入 repo（依本輪限制）。需要的話，可以把 O1～O3、O6 轉成正式的 regression test。
