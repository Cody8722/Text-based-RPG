# TEST_COVERAGE_MAP.md

對象：`tests/` 下 3 個檔案、**53 個測試**（`python3 -m unittest discover -s tests` → `OK (expected failures=3)`）。
本文件只做盤點，沒有修改任何測試或 production code。對應的行為描述見 `CURRENT_ARCHITECTURE.md`（下稱 CA）。

## 0. 先講總體事實

1. **沒有任何測試碰網路。** Ollama（chat＋embed）、Qdrant、雲端 API 全部被 `requests.post/put` 的 mock 取代。所以「mock external service」不是一個子類別，而是**全部 53 個測試的共同前提**。
   這份表真正區分的是：測試結果**是否取決於 mock 的語意**（尤其是假 Qdrant，標記 `Q`）。
2. 53 個測試中，**有 43 個是從 `main()` 的輸入迴圈打進去**（用腳本化的 `input`），走的是真實的 production 分支；其餘 10 個直接呼叫 production 函式（`call_llm`、`get_visible_options`、`render_options`）。沒有任何測試對 production 函式用手寫的替身重新實作邏輯。
3. 沒有測試涵蓋真實模型的行為，也不驗證 Ollama 是否強制 `format` schema（測試故意送出違反 schema 的內容）。

## 1. 圖例

| 欄位 | 值 |
|---|---|
| **類型** | **P** = 測 production 行為／state 流（結果是 state、history、記憶、輸出的變化） · **V** = 主要測 parser／validation 的拒絕行為 · **R** = residual 特徵測試（攻擊**成功**，記錄現況，通過＝仍然脆弱） · **X** = 預期失敗（`expectedFailure`，攻擊成功且尚未修復） |
| **攻** | ● = 攻擊 reproducer（模擬惡意／異常 LLM 或雲端輸出） |
| **入口** | `main` = 經由 `main()` 迴圈 · `fn` = 直接呼叫 production 函式 |
| **Mock** | `O` = Ollama · `C` = 雲端選項 API · `Q` = **有狀態的假 Qdrant＋embed，且結果取決於它的行為** · `rnd` = 對 `random.randint` 注入固定值 |
| **I#** | 對應 CA §11 的 invariant 編號 |

## 2. 總覽

| 分類 | 數量 | 說明 |
|---|---|---|
| P　production 行為 | 32 | 其中 14 個是 round-3 修復的回歸 |
| V　parser／validation | 14 | |
| R　residual（攻擊成功、現況特徵測試） | 4 | |
| X　預期失敗（尚未修復） | 3 | |
| 合計 | **53** | |
| 其中攻擊 reproducer（●） | 35 | |
| 其中依賴假 Qdrant 語意（Q） | 10 | |

## 3. 逐測試對照（依檔案）

### 3.1 `tests/test_regressions.py`（9）— 第二輪修復的回歸

| # | 測試 | 保護的 invariant | 類型 | 攻 | 入口 | Mock | I# |
|---|---|---|---|---|---|---|---|
| 1 | `HistoryOnFailure.test_call2_failure_leaves_history_untouched` | Call2 失敗 ⇒ history 不留未經歷的敘事 | P | | fn(`call_llm`) | O | I3 |
| 2 | `HistoryOnFailure.test_main_call2_failure_does_not_pollute_context` | 同上，且 option_counts／affinity 不動 | P | | main | O | I3 |
| 3 | `HistoryOnFailure.test_successful_turn_is_recorded_once_as_user_and_assistant` | 成功回合 history 恰一組 user＋assistant，內容正確 | P | | main | O | I4 |
| 4 | `HistoryOnFailure.test_failed_turn_then_retry_records_only_the_successful_one` | 失敗後重試只留成功那次 | P | | main | O | I3 |
| 5 | `HistoryOnFailure.test_scripted_call1_failure_still_commits_the_fallback_narration_the_player_saw` | scripted＋Call1 失敗：history 記的是玩家看到的備援敘事，且結果套用 | P | | main | O, rnd | I7 |
| 6 | `ScriptedOneShot.test_wang_debtor_trouble_cannot_succeed_twice` | 一次性：不會重複 +3 | P | | main | O, rnd | I5 |
| 7 | `ScriptedOneShot.test_ayue_secret_money_cannot_grow_prowess_twice` | 一次性：prowess 只成長一次 | P | | main | O, rnd | I5 |
| 8 | `ScriptedOneShot.test_failed_attempt_can_be_retried` | 失敗不設旗標、選項保留可重試 | P | | main | O, rnd | I5 |
| 9 | `ScriptedOneShot.test_completed_scripted_option_hidden_but_unlock_option_stays` | 完成後 scripted 選項隱藏，`goto_ayue_home` 不受影響 | P | | fn(`get_visible_options`) | — | I5 |

### 3.2 `tests/test_causality_attacks.py`（24）— 第三輪攻擊報告的 reproducer

| # | 測試 | 保護／記錄的內容 | 類型 | 攻 | 入口 | Mock | I# |
|---|---|---|---|---|---|---|---|
| 10 | `Call1.DEFENDED_flags_set_cannot_set_any_flag` | 四種 `flags_set` 形狀都設不了旗標 | V | ● | main | O | I1 |
| 11 | `Call1.DEFENDED_extra_keys_in_call1_are_ignored` | `affinity_delta`／`grow_prowess`／`location`… 被忽略 | V | ● | main | O | I1 |
| 12 | `Call1.DEFENDED_wrong_types_abort_turn_without_state_change` | 型別錯／非 JSON／截斷 ⇒ `npc` 回合作廢，state／history／turn_count 不變 | V | ● | main | O | I1 |
| 13 | `Call1.VULN_empty_object_prefix_yields_blank_narrative_that_still_mutates_state` | **X**：`{}` 前綴 ⇒ 空敘事仍改 affinity、寫入 history | X | ● | main | O | F5 |
| 14 | `Call1.VULN_narrative_can_forge_ui_lines_and_terminal_escapes` | **X**：敘事可含換行／`\x1b` 偽造 UI | X | ● | main | O | F6 |
| 15 | `Call2.DEFENDED_out_of_range_or_wrong_type_delta_is_zero` | 2、−2、99、"1"、[1]、dict、null ⇒ 0 | V | ● | main | O | I2 |
| 16 | `Call2.DEFENDED_call2_cannot_set_flags_or_prowess` | Call2 多塞 key 無效 | V | ● | main | O | I2 |
| 17 | `Call2.RESIDUAL_llm_owns_pm1_per_npc_turn_and_that_moves_scripted_base_rate` | **R**：一次 +1 ⇒ scripted 基礎成功率 70（僅斷言 affinity>0 這一側） | R | ● | main | O, rnd | R1 |
| 18 | `Call2.VULN_float_delta_passes_validation_and_makes_affinity_a_float` | **X**：`1.0` 通過驗證，affinity 變 float | X | ● | main | O | F7 |
| 19 | `Scripted.DEFENDED_narration_cannot_flip_a_rolled_failure` | 敘事寫反也不改失敗結果；Call2 不被呼叫 | P | ● | main | O, rnd | I6 |
| 20 | `Scripted.DEFENDED_narration_cannot_flip_a_rolled_success` | 同上，成功側 | P | ● | main | O, rnd | I6 |
| 21 | `Scripted.DEFENDED_llm_cannot_veto_a_rolled_failure_by_aborting` | A6：只在失敗時中止得不到免費重擲 | P | ● | main | O, rnd | I7 |
| 22 | `Scripted.DEFENDED_llm_cannot_force_the_mention_roll_nor_the_flag` | 骰沒中 ⇒ 塞旗標＋Call2 +1 都設不了 `mentioned_wang_debt` | P | ● | main | O, rnd | I12 |
| 23 | `Scripted.RESIDUAL_mention_flag_is_set_even_if_narrative_ignores_the_hint` | **R**：骰中＋Call2 +1 ⇒ 旗標設定，即使敘事沒提 | R | ● | main | O, rnd | R3 |
| 24 | `Memory.RESIDUAL_forged_note_becomes_a_remembered_fact_in_the_next_prompt_but_not_a_flag` | **R**：偽造 note 進下一輪 prompt，但旗標／prowess 不變 | R | ● | main | O, **Q** | R2 |
| 25 | `Memory.RESIDUAL_assistant_history_also_carries_the_forged_note` | **R**：`npc` 回合 note 也在 history（不需 Qdrant） | R | ● | main | O | R2 |
| 26 | `Memory.DEFENDED_scripted_turn_stores_python_outcome_not_llm_note` | A7：scripted 記憶＝Python 版 | P | ● | main | O, **Q**, rnd | I9 |
| 27 | `Memory.DEFENDED_memory_note_cannot_forge_a_prompt_section_header` | A7：note 內的 `【…】` 區塊標題無法進 prompt | P | ● | main | O, **Q** | I10 |
| 28 | `Memory.DEFENDED_memory_is_scoped_to_the_target_npc` | 阿月的記憶不出現在老王 prompt | P | ● | main | O, **Q**, rnd | I11 |
| 29 | `Cloud.DEFENDED_cloud_cannot_add_remove_or_retype_options` | 數量錯 ⇒ fallback；數量對時只多 `display_text` | V | ● | fn(`render_options`) | C | I13 |
| 30 | `Cloud.DEFENDED_reordered_or_swapped_cloud_texts_never_change_python_options` | 文字互換不改 Python 選項身分 | V | ● | fn | C | I14 |
| 31 | `Cloud.DEFENDED_rewritten_scripted_text_never_reaches_call1` | 改寫的意圖不進 Call1 | P | ● | main | O, C, rnd | I14 |
| 32 | `Cloud.DEFENDED_cloud_text_with_newlines_cannot_smuggle_instructions` | 夾帶指令不進 Call1／history | P | ● | main | O, C | I14 |
| 33 | `Cloud.DEFENDED_options_given_as_a_string_falls_back` | 字串型 `options` ⇒ fallback | V | ● | fn | C | I13 |

### 3.3 `tests/test_round3_fixes.py`（20）— 第三輪修復（A6／A7／A11）的回歸

| # | 測試 | 保護的 invariant | 類型 | 攻 | 入口 | Mock | I# |
|---|---|---|---|---|---|---|---|
| 34 | `A6.test_success_roll_plus_call1_failure_still_applies_success` | 8 種 Call1 失敗 × 成功骰：好感度／旗標／prowess／計次／turn_count 全套用，顯示備援敘事 | P | ● | main | O, rnd | I7 |
| 35 | `A6.test_failure_roll_plus_call1_failure_still_applies_failure` | 8 種 Call1 失敗 × 失敗骰：−1、無旗標、無 prowess、已計次 | P | ● | main | O, rnd | I7 |
| 36 | `A6.test_one_interaction_rolls_exactly_once_even_if_call1_fails` | 每次互動恰擲一次，失敗結果被消耗（−1） | P | ● | main | O, rnd(計數) | I7 |
| 37 | `A6.test_llm_that_aborts_only_on_failures_gains_nothing` | 對手策略：失敗才中止 ⇒ −1、−1、+1＝−1 | P | ● | main | O, rnd | I7 |
| 38 | `A6.test_successful_call1_path_is_unchanged` | Call1 成功時玩家讀到 LLM 敘事、不用備援 | P | | main | O, rnd | I8 |
| 39 | `A7.test_success_memory_matches_success` | 成功的記憶＝成功 hint（即使 Call1 寫「拒絕」） | P | | main | O, **Q**, rnd | I9 |
| 40 | `A7.test_failure_memory_matches_failure` | 失敗的記憶＝失敗 hint（即使 Call1 寫「收下」） | P | | main | O, **Q**, rnd | I9 |
| 41 | `A7.test_malicious_call1_note_never_overrides_the_authoritative_outcome` | 惡意 note（矛盾＋偽區塊標題）不進 Qdrant、下一輪 prompt、history；成功／失敗兩側 | P | ● | main | O, **Q**, rnd | I9, I10 |
| 42 | `A7.test_scripted_history_does_not_carry_the_llm_note` | history 的 `memory_note` 是 Python 版 | P | | main | O, rnd | I9 |
| 43 | `A7.test_memory_does_not_leak_across_npcs` | 寫入的 `npc_ids` 只有目標 NPC；老王 prompt 沒有阿月的記憶 | P | | main | O, **Q**, rnd | I11 |
| 44 | `A7.test_npc_turn_memory_is_single_line_and_cannot_forge_section_headers` | `npc` 回合記憶單行、無【】 | P | ● | main | O, **Q** | I10 |
| 45 | `A7.test_legacy_multiline_memory_already_in_qdrant_is_sanitized_when_read` | 舊資料在讀取端也被淨化 | V | | main | O, **Q** | I10 |
| 46 | `A11.test_cloud_options_reorder_does_not_change_python_intent` | 陣列倒序（id 保留）依 id 對回；文字互換不改選項身分 | V | ● | fn | C | I14 |
| 47 | `A11.test_player_index_still_selects_the_python_option_after_reorder` | 文字互換後，玩家選的 index 仍執行 Python 的選項 | P | ● | main | O, C, rnd | I14 |
| 48 | `A11.test_contradicting_wording_does_not_change_python_intent` | 「走回街道」式措辭不會移動 `location`，意圖不變 | P | ● | main | O, C, rnd | I14 |
| 49 | `A11.test_prompt_injection_in_wording_cannot_change_behaviour` | 雲端夾帶的指令不進 Call1／history，affinity／旗標不變 | P | ● | main | O, C | I14 |
| 50 | `A11.test_display_text_is_what_the_menu_prints_and_text_is_the_action` | `display_text` 與 `text` 分工 | V | | fn | C | I15 |
| 51 | `A11.test_malformed_cloud_responses_fall_back_to_python_wording` | 14 種異常回傳全部 fallback | V | ● | fn | C | I13 |
| 52 | `A11.test_cloud_request_failure_falls_back` | 請求逾時 ⇒ fallback | V | | fn | C | I13 |
| 53 | `A11.test_display_text_is_single_line` | 顯示文字收斂成單行 | V | | fn | C | I13 |

## 4. 依 invariant 反查

| Invariant（CA §11） | 測試 # |
|---|---|
| I1 Call1 無法設旗標／額外 key 無效／壞 JSON 作廢 | 10, 11, 12 |
| I2 Call2 範圍／型別驗證、不能設旗標 | 15, 16 |
| I3 `npc` 回合 Call2 失敗不污染 history | 1, 2, 4 |
| I4 成功回合 history 正確 | 3 |
| I5 scripted 一次性＋失敗可重試 | 6, 7, 8, 9 |
| I6 敘事不能翻轉骰結果 | 19, 20 |
| I7 scripted 結果在 Call1 失敗下仍套用、不重擲 | 5, 21, 34, 35, 36, 37 |
| I8 Call1 成功時行為不變 | 38 |
| I9 scripted 記憶／history note 為 Python 版 | 26, 39, 40, 41, 42 |
| I10 記憶單行、無偽區塊、讀取端淨化 | 27, 41, 44, 45 |
| I11 記憶不跨 NPC | 28, 43 |
| I12 `mentioned_wang_debt` 骰沒中則不可能設 | 22 |
| I13 雲端結構異常 fallback | 29, 33, 51, 52, 53 |
| I14 雲端措辭不改行為、不進 Call1／history | 30, 31, 32, 46, 47, 48, 49 |
| I15 `display_text`／`text` 分工 | 50 |
| 殘留 R1／R2／R3（特徵測試） | 17／24, 25／23 |
| 未修復 F5／F6／F7（XFAIL） | 13／14／18 |

## 5. 沒有任何（或只有間接）測試的區域

| 區域 | 現況 |
|---|---|
| `scene`／`flavor` 選項的導覽 | 沒有測試斷言「選了 scene 選項後 `location` 變成 target、intro 被印出、可以走回」。僅 #28 經過 `goto_street`（為了別的目的），#48 斷言 `location` 沒被亂移。**`flavor` 型零測試**。導覽圖（酒館↔街道↔市集／客棧／鎮口／武館／阿月家）全無回歸保護 |
| Qdrant point id 跨局碰撞（F1） | 無測試。假 Qdrant 以 id 為 key，其實可以重現，但沒寫 |
| 記憶失敗路徑 | `ensure_memory_collection` 失敗、`embed_text`／`query_memories` 失敗、`write_memory` 的 dict 形 note 檢查、空 note、非 `RequestException`（F3）：全未測；所有測試預設 `MEMORY_ENABLED=False` 或用永遠成功的假服務 |
| `npc` 路徑的選擇性中止（F4） | 無測試 |
| `FLAG_FACTS` → prompt（旗標存在時 `【你們之間確實發生過的事】` 真的出現） | 只測過「沒有旗標時不出現」，**沒有正向測試** |
| `scene_atmosphere`、`repeat_hint`、`flavor_hint` 的具體注入 | 僅 #22／#23 檢查 hint 的有無 |
| 數值規則本身 | `prowess_at`、`PROWESS_BONUS_PER_POINT`、`resolve_scripted_outcome` 的 5～95 clamp、`affinity_tier` 邊界、`clamp(±5)` 都沒有直接測試；#17 只覆蓋「affinity>0 ⇒ 70」一側，≤0 ⇒ 30 與 prowess 修正未斷言 |
| 解析器 | `parse_llm_json`（括號深度、字串內括號）與 `strip_residue` 沒有單元測試，只靠壞輸入間接觸發 |
| 輸入處理 | 無效數字、非數字輸入的重新提示；只用過 `0` 離開 |
| 輸出格式 | `builtins.print` 與 `print_typewriter` 被全域 mock，選單、狀態列格式不受保護 |
| `load_dotenv` | 無測試 |

## 6. 測試之間的重複與設計矛盾（只記錄，未修改）

**重複／被取代：**
1. **#21 與 #37 幾乎一模一樣**（同樣的骰序 `[100,100,1]`、同樣的 Call1 觸發條件、同樣斷言 affinity＝−1）。
2. **#29、#30、#31、#32、#33（`CloudAttacks`）被 `test_round3_fixes` 的 A11 類別完全涵蓋**：#29⊂#46／#51、#30≈#46、#31≈#48、#32≈#49、#33⊂#51（`options_is_string`）。
3. #26 被 #39／#40／#41 涵蓋。
4. #27 被 #44 涵蓋（#44 更強）。
5. #28 與 #43 同題；#28 做法較脆弱（兩次呼叫 `play()`，中途手動改 `g.state["location"]`，patch 疊兩層）。

**語意不一致／可能誤導：**
6. **類別名稱與內容相反**：`test_regressions.HistoryOnFailureTests` 內的 #5 斷言的是「失敗時 history *有*寫入備援敘事」，與類別名（失敗時 history 保持乾淨）及同類別 #1／#2／#4 的語意相反。實際上並不矛盾（#1／#2／#4 是 `npc` 路徑，#5 是 scripted 路徑，是第三輪刻意的不對稱），但單看測試名稱無法知道，應在某處明說。
7. **#12 的名稱 `…abort_turn_without_state_change` 只對 `npc` 路徑成立**；scripted 路徑的對應行為相反（#34～#37）。這個不對稱是設計，但沒有任何一個測試把它當成同一件事的兩面來斷言。
8. **三種「通過」的極性並存**：`DEFENDED`（通過＝已修復）、`RESIDUAL`（通過＝**仍然脆弱**）、`VULN`/XFAIL（通過＝**仍未修復**）。將來有人修好 R1～R3 時，#17／#23／#24／#25 會**變紅**，卻看不出這其實是好消息；而 XFAIL 修好則會變成 "unexpected success"（有明確訊號）。慣例不一致。
9. **`expectedFailure` 會吞掉任何例外**：#13／#14／#18 如果將來因為測試工具本身壞掉（例外）而失敗，仍會顯示為「預期失敗」。我在撰寫時逐一暫時拿掉標記驗證過它們是因斷言而失敗，但這個保障不在測試套件裡。
10. **#5 以 `SCENES["tavern"]["options"][6]` 取 hint**，與選項順序耦合；調整選單順序會讓它以難懂的方式失敗。

**隔離／決定性：**
11. **重置 state 的方式不一致**：基底 `setUp` 用 `deepcopy(_INITIAL_STATE)`；迴圈內改用 `json.loads(json.dumps(...))`；round3 的 subTest 迴圈直接再呼叫 `self.setUp()`（每次再疊一層 patch，等到 cleanup 才一起還原）。#15 的迴圈只重置 `state`、沒有重置 `conversation_history`（目前不影響斷言）。
12. **非決定性**：#2、#3、#4 選的是 `wang_business`，沒有 patch `random.randint`，所以「老王鋪墊擲骰」每次真的有 30% 機率發生（hint 注入、甚至設 `mentioned_wang_debt`）。目前斷言與它無關，所以不會閃爍，但這是未固定的隨機性。
13. **假 Qdrant 的保真度有限**：`/points/search` 回傳該 NPC 所有記憶（最多 `limit`），不做相似度排序；因此測不到「檢索排序／top-k 取捨」問題。PUT 以 id 覆寫，與真實 upsert 行為一致。
14. **假 Ollama 不強制 schema**：測試刻意送出違反 schema 的內容，這正是目的；但也代表「Ollama 的結構化輸出確實擋住了什麼」沒有被測，防線全靠 Python 側。

## 7. 一句話結論

測試對**因果邊界**（誰能改 state、scripted 結果是否不可撤銷、記憶與雲端文字是否只是呈現）保護得相當扎實，且大多走真實的 `main()` 路徑；
弱點在於**一般功能與導覽**（scene／flavor、數值公式、旗標進 prompt）幾乎沒有回歸保護，以及**所有外部服務的真實行為**完全未被驗證。
