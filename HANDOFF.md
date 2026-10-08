# HANDOFF — 青石鎮（文字 RPG）

給接手的 AI／開發者／測試者。這份文件只說**系統怎麼運作**，刻意不說**遊戲裡會發生什麼**。

> ⚠️ **劇透警告（給還沒玩過的人）**：`rpg/content/npcs.py`、`rpg/genes.py` 裡是人物設定與隱藏設定的原始資料。
> 第一次遊玩前不要打開它們，也不要用 `RPG_DEBUG=1` 或 `python -m rpg.cli sim`——那些會把整個世界攤開來。

---

## 1. 專案目前狀態

- 2026-10 從「單場景 Call1/Call2 技術 MVP」整個改寫成**世界因果模擬 + 網頁介面**的可玩版本。
- 遊戲在一個小鎮裡進行。世界有時間（一天六個時辰），NPC 有作息、需要、性格與彼此的關係，會自己行動；
  事件依白盒規則發生、互相引發；消息在人與人之間流傳、會走樣；玩家只是其中一個行動者。
- 每個世界開局時會抽一組隱藏設定（基因池），而且在玩家抵達前，世界已經自己運轉了幾天——所以每局的人際網、恩怨與起點都不同。
- LLM（本機 Ollama）是**可選的說書人**：只潤飾已經確定的結果。沒有 LLM 時遊戲完整可玩（內建模板敘事）。
- 舊的 MVP（`game_mvp.py` 與它的 53 個測試）搬到 `legacy/`，仍可執行，但不再是主程式。
- 歷次審查文件（MVP_AUDIT、CAUSALITY_ATTACK_REPORT、OPUS_INDEPENDENT_REVIEW 等）搬到 `docs/reviews/`，描述的是**舊 MVP**。

## 2. 如何啟動

需求：Python 3.10 以上。**不需要安裝任何套件。**

```bash
python -m rpg              # 開本機網頁伺服器並自動打開瀏覽器（http://127.0.0.1:8765/）
python -m rpg --no-browser --port 9000
```

- 只綁 `127.0.0.1`。要給區網其他裝置連，自己加 `--host 192.168.x.x`（明確綁定，不要綁 0.0.0.0——見 CLAUDE.md 的網路原則）。
- 存檔自動寫在 `saves/autosave.json`（已 gitignore），開始畫面會出現「繼續上次的旅程」。改位置：`RPG_SAVE_DIR`。
- 備用終端機介面：`python -m rpg.cli play`。

### 接上說書人（可選）

預設會自動偵測本機 Ollama（`http://localhost:11434`，模型 `qwen3.5:9b`）。偵測不到就用內建敘事，不會報錯。

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `RPG_LLM` | `auto` | `auto`（偵測）／`ollama`（強制）／`off`（關閉） |
| `RPG_OLLAMA_URL` | `http://localhost:11434` | Ollama 位址 |
| `RPG_MODEL` | `qwen3.5:9b` | 模型名稱 |
| `RPG_SAVE_DIR` | `./saves` | 存檔資料夾 |
| `RPG_DEBUG` | `0` | `1` 開啟除錯端點（會劇透） |

呼叫一律帶 `think: false` 與 `num_ctx: 8192`（CLAUDE.md 的實測結論）。

## 3. 如何遊玩（基本操作）

- 開始新的旅程 → 從三個出身裡選一個。
- 畫面左邊是故事，下面是你現在能做的事；右邊側欄有「此地／見聞錄／人物／足跡／行囊」。
- 數字鍵 1–9 可以直接選前幾個動作。跟人交談時，可以在輸入框打一句話（會被對應到既有的談話意圖）。
- 每做一件事都會花時間；時間一過，鎮上的人照自己的日子行動。
- 有些時刻會需要你當場決定要不要介入。
- 沒有任務清單，也沒有「正確答案」。你知道的事都記在見聞錄；你做過的事記在足跡——鎮上的人也會記得。

## 4. 必要依賴

| 用途 | 依賴 |
|---|---|
| 遊玩 | Python 3.10+（只用標準庫） |
| 說書人（可選） | 本機 Ollama + `qwen3.5:9b` |
| 瀏覽器端到端測試（可選） | node + `playwright` 套件 + Chromium（沒有就自動跳過） |

字體從 Google Fonts 載入；離線時退回系統襯線字體，不影響遊玩。

## 5. 主要架構入口

```
rpg/
  __main__.py     python -m rpg 的入口 → server.main()
  server.py       標準庫 HTTP 伺服器：/api/*、靜態檔、除錯端點
  game.py         遊戲 session：開局、繼續、動作、自動存檔、交辦說書
  world.py        World：唯一的 authoritative state（全部 JSON 原生型別）＋ seed RNG ＋ 事實/知識/借貸 ＋ 開局與預熱
  genes.py        世界基因池（開局隨機抽的隱藏設定）            ← 劇透
  sim.py          時間推進、作息、每日規則（經濟、租金、催收、病情、辦案、行商、調皮事件、新面孔）
  behaviors.py    NPC 自主行為的白盒權重表（八卦、借錢、偷、幫忙、動手、報官、揣測……）
  reactions.py    任何人「得知一件事」之後的白盒反應；捕頭的懷疑分數
  player.py       玩家：出身、可做的動作（伺服器產生）、執行、介入的分岔
  dialogue.py     交談：說不說、說什麼；自由輸入只對應到白名單意圖
  speech.py       說話層：事實→口語；把同一個人的同一類事歸成「故事」；NPC 說過的句子記住不重複
  view.py         玩家視角投影：前端唯一拿得到的資料
  narrator.py     說書人（Ollama）：組 prompt、非同步、白盒驗證、失敗退回模板
  devtools.py     編年史、因果鏈、統計（會劇透，玩家介面不使用）
  cli.py          sim（看世界自己跑）／play（終端機版）
  content/
    locations.py  地點、相鄰、時段描述
    npcs.py       人物定義、初始人際、閒聊台詞                ← 劇透
    text.py       所有模板文字（事實句、目擊句、外表線索、算命、氣氛通知……）
web/              index.html / style.css / app.js（原生 JS，無框架、無建置步驟）
tests/            新引擎的測試（見第 7 節）
legacy/           舊 MVP 與它的測試
docs/reviews/     舊 MVP 的審查文件
```

### 一個回合怎麼走

```
前端 POST /api/act {id}
 → player.perform：id 必須在「當下」available_actions 清單裡（前端無法發明動作）
 → 規則結算玩家這一步（白盒骰子 world.roll，夾在 3%～97%，沒有絕對的必然）
 → sim.advance：時間往前走；每個時辰 NPC 依權重行動；每天清晨跑每日規則
     · 發生的事 → world.add_fact（Python 產生的事實）→ 在場的人 learn → reactions 調整好感、記恨、報官
     · 玩家在場且需要決定時 → world.pending（時間凍結，只剩介入選項）
 → game.save（自動存檔）
 → view.build（玩家視角投影） + narrator.submit（可選，非同步）
前端顯示片段；若有說書工作就輪詢 /api/narration，LLM 結果通過驗證才替換，否則保留模板
```

### 硬邊界（吸收自 docs/reviews/ 的教訓）

1. **只有 Python 能改 state。** LLM 的輸出只用來顯示，永遠不會寫回 world、不會變成事實、不會進任何記憶。
2. **世界記憶是結構化事實**（誰、對誰、在哪、何時、因為什麼），不是 LLM 寫的摘要。舊架構的記憶污染、跨局殘留、偽造 prompt 區塊這幾類問題因此整類消失。
3. **事實與存檔在同一個物件裡**，一起存、一起讀，不會有「state 歸零但記憶還在」。
4. **動作 id 由伺服器產生並驗證**；顯示文字就是動作本身的文字，沒有雲端改寫這一層（舊 A11 問題整類消失）。
5. **前端只拿到玩家角色能知道的東西**（`view.py`）；`tests/test_view_hiding.py` 會整包掃描。
6. **說書人只拿到這一回合、玩家看得到的片段**；輸出要通過白盒驗證（數字不能憑空出現、片段裡的人名一個不能少、不能多拉別的鎮民進場、長度合理、清掉控制字元），不過就用模板。
7. **所有隨機只走 `world.rng`**（seed 建立、隨存檔保存）。同 seed ＋ 同動作 ＝ 同世界。

## 6. 重要檔案位置（速查）

| 想改什麼 | 去哪裡 |
|---|---|
| 地點、相鄰、描寫 | `rpg/content/locations.py` |
| 新人物 / 台詞 | `rpg/content/npcs.py`（`NPCS`、`RELATIONS`、`CHATTER`） |
| 新的隱藏設定 | `rpg/genes.py`（`GENE_POOL`，每個基因都要落到機制上） |
| 新的 NPC 行為 | `rpg/behaviors.py`（`BEHAVIORS` 權重表） |
| 得知某件事後的反應 | `rpg/reactions.py` |
| 每日規則（經濟、債、病、案件） | `rpg/sim.py` |
| 玩家能做的事 | `rpg/player.py`（地點動作、介入）、`rpg/dialogue.py`（交談動作） |
| 事實的文字、目擊描寫 | `rpg/content/text.py` |
| NPC 口中的說法、故事歸併、清晨街談、提起你的事 | `rpg/speech.py` |
| 前端 | `web/` |

新增事實類型時：在 `text.fact_text` 加一句、需要的話在 `WITNESS` 加目擊描寫、在 `reactions.on_learn` 決定它會讓人怎麼想。

## 7. 如何執行測試

```bash
python -m unittest discover -s tests          # 新引擎（約 40 秒；有 node+playwright 會多跑瀏覽器測試）
python -m unittest discover -s legacy/tests   # 舊 MVP（仍應全綠，含 3 個刻意的 expected failure）

# 選用：裝了 pytest 也可以
pytest                                        # = 上面的快速測試，不需要 Ollama
```

### 真模型整合測試（`tests_llm/`，跟快速測試分開）

需要本機 Ollama 與 `RPG_MODEL`（預設 `qwen3.5:9b`）。連不上或沒有模型時整組 SKIP，印出 `LLM UNAVAILABLE` 與原因——那是環境狀況，不是遊戲錯誤。

```bash
python -m tests_llm                    # 全部情境＋連續遊玩 60 個說書回合
python -m tests_llm --long-turns 100   # 連續遊玩跑久一點
python -m tests_llm --only time absent # 只跑名稱含這些字的測試
python -m tests_llm --require          # Ollama 不可用時結束碼 3（給要強制跑的場合）
python -m tests_llm --rescore tests_llm/reports/latest.json   # 不呼叫模型：用現在的驗證器重判上次記錄的模型原文（調驗證器用，幾秒鐘）
pytest -m llm -s                       # 同一套，用 pytest 跑
```

- 不要求模型說出特定句子；檢查的是**契約**：顯示給玩家的文字不能多出鎮民、不能把只被提到的人寫成在場、不能改台詞、
  不能改時辰天氣、不能多出同行者或事件、剛介紹過的地方不能再介紹一遍、不能講出人物設定或玩家不知道的祕密、長度、繁體中文；
  說書人永遠不改世界狀態（每回合比對 hash，並跟一份沒有說書人的影子世界逐回合比對）。
- 情境是確定的（`tests_llm/scenarios.py`：剛抵達後停留、純對話、談到不在場的人、多人在場、有私密設定、六個時辰×天氣、固定 seed 連續遊玩）。
- 跑完印出統計（接受率、退回率與原因、模型原始輸出各類越界次數、有沒有漏到玩家眼前、延遲、連續遊玩前後半段退回率），
  逐回合完整紀錄（prompt、模型原文、顯示文字、判定）寫到 `tests_llm/reports/latest.json`。調提示或驗證器時先看這份。
- 報告裡「Rejected though the checker saw nothing」是驗證器可能太嚴的地方；「Reached the player」必須是 0，不是 0 就是驗證器的缺口。
  改驗證器之後先 `--rescore` 看兩個數字怎麼變，再決定要不要重跑真模型。
- 環境變數：`RPG_OLLAMA_URL`、`RPG_MODEL`、`RPG_LLM_TIMEOUT`（預設 180 秒）、`RPG_LLM_LONG_TURNS`、`RPG_LLM_MIN_ACCEPT`（接受率下限，預設只要求至少一次被採用）。
- 契約檢查器（`tests_llm/contract.py`）刻意跟 production 驗證器分開寫；`tests/test_llm_harness.py` 會確認兩邊對得上，
  也確認測試架構本身（情境確定、沒有模型時正確 SKIP、假模型故意越界時不會漏到玩家眼前）。

測試分組：

| 檔案 | 保護什麼 |
|---|---|
| `test_world_invariants.py` | 長時間（120～240 天）、多 seed、隨機玩家下，錢/健康/好感/狀態/事實因果/死者不再行動等不變量 |
| `test_causality.py` | 世界會長出因果鏈、事件多樣、每個世界故事不同、傳聞會走樣並能冤枉人、玩家介入真的改變結果、知識與隱私規則；另有「不變量檢查器自己會抓錯」的元測試 |
| `test_actions.py` | 只能做清單上的事、每個動作在多種狀態下都能執行、被抓、昏倒、自由輸入只導向白名單意圖、借貸、驕傲的人拒收施捨 |
| `test_determinism_and_save.py` | 同 seed 同動作同世界、存讀檔後接著跑完全一致、壞存檔不崩、引擎不用全域 random |
| `test_view_hiding.py` | 前端資料不含內部欄位、不含玩家不知道的祕密、選單不洩漏誰被關 |
| `test_narrator.py` | LLM 亂寫／捏造數字／多拉人／逾時／連不上 → 退回模板；敘事永遠不改 state；prompt 不含祕密；`think:false`、`num_ctx:8192` 有帶 |
| `test_dialogue.py` | 同一個故事清晨只播一次、見聞錄一件事一條、傳話一次講完整件事、追問會換說法然後對方不聊了、家常話不重複、NPC 只提一次你做的事、當事人不轉述自己做的事、偷竊被逮後被趕出去並被盯上、選句子不動到世界的亂數 |
| `test_llm_harness.py` | 真模型整合測試的架構：情境確定且真的涵蓋宣稱的條件、契約檢查器抓得到每一類越界且不誤判模板、production 驗證器擋得住契約檢查器會抓的每一類、假模型故意越界時不會漏給玩家、沒有 Ollama 時明確 SKIP |
| `test_server.py` | 真 HTTP：完整流程、壞請求、除錯端點預設關閉、靜態檔不能穿越目錄 |
| `test_ui_e2e.py` + `ui_e2e.js` | 真瀏覽器：開局、選出身、移動、交談、快捷鍵、側欄、手機抽屜、說書人敘事出現且不卡住、頁面沒有 JS 錯誤 |

## 8. 如何 debug

```bash
RPG_DEBUG=1 python -m rpg               # 開 /api/debug/summary、/chronicle、/chains、/world（會劇透）
python -m rpg.cli sim --seed 7 --days 60 --chains   # 不需玩家，看一個世界 60 天的編年史與最長因果鏈（會劇透）
python -m rpg.cli sim --seed 7 --days 60 --all      # 包含所有瑣事
```

- 除錯模式下 `POST /api/new` 可以帶 `seed` 重現特定世界；非除錯模式會忽略 seed。
- 每條事實都記了 `causes`（指向更早的事實），`devtools.longest_chains` 會把因果鏈串出來。
- `world.mischief_log` 是調皮事件的隱藏日誌；`world.genes` 是這個世界抽到的隱藏設定。
- 平衡調整的方法：改權重 → 跑 30～40 個 seed 各 60 天看統計（死亡、逃離、逮捕、冤案、鬥毆、因果鏈深度）→ 再讀幾份編年史確認「讀起來像故事」。`tests/test_causality.py` 守住大致範圍。

## 9. 已知限制

- 說書人只在本機 Ollama 上實際設計過，沒有在真實模型上做過大量 E2E；驗證規則偏保守（寧可退回模板）。
- 數值平衡是用模擬統計調的，沒有大量真人遊玩回饋。某些世界會比較平靜、某些比較動盪，這是刻意的變異，但幅度可能還要調。
- 只有一個存檔槽、單人、本機。沒有帳號、沒有多人。
- 介面只有繁體中文。Google Fonts 離線時退回系統字體。
- 長時間遊玩後存檔會變大（事實只增不減）；目前在數百 KB 量級，還沒做壓縮或歸檔。
- 網頁介面的故事區只保留最近 60 個回合的文字（見聞錄不受影響）。
- 沒有結局。世界會一直運轉下去。

## 10. 刻意設計，不是 bug

- **玩家抵達時，鎮上已經發生過一些事。** 見聞錄裡標「你來之前」的就是。
- **NPC 會說錯話。** 傳話會走樣、街坊會亂猜；見聞錄記的是「你聽到的版本」，不保證是真的。捕頭也只能依他聽到的辦案。
- **同一件事，不同的人告訴你的版本可能不同。**
- **很多事你不在場就不會知道**，除非有人告訴你、或鬧大到全鎮都在傳。
- **沒有好感度數字**，只有態度描述；沒有任務提示，也沒有地圖標記。
- **有些人不會因為你給錢就接受**；有些事交情不夠，對方不會說。
- **介入有代價**：替人出頭可能得罪人，見義勇為可能挨打，袖手旁觀也是一種選擇，鎮上的人會記得。
- **偶爾會有一句沒頭沒尾的氣氛通知**——那是刻意的，不會解釋。
- **昏倒不是死亡**：會在別處醒來，損失一些東西，遊戲繼續。
- **沒有說書人時文字比較樸素**，但所有結果都一樣；說書人只改變講法，不改變發生的事。
- **相同 seed 在不同的玩家動作下會走出不同的世界**——你做的每件事都會改變骰子的順序。
- **同一場談話裡一直問同一件事，對方會不耐煩、甚至走開**；同一件事被街坊傳過了，清晨不會再聽一遍。
- **見聞錄以「一件事」為單位**：同一個人接連出的事會合成一條，日子顯示最新的那次。

## 11. 給接手者的規則

- 任何能改變遊戲結果的東西（金錢、健康、旗標、關係、事件是否發生、成敗）只能由 Python 規則決定。要讓 LLM 參與，必須像 `narrator.py` 一樣：只讀已發生的事、輸出只顯示、白盒驗證、可退回。
- 新增「調皮事件」類的例外時，觸發時機與內容池都要白盒化並寫進 `mischief_log`。
- 新增玩家看得到的資料前，先想「玩家角色怎麼會知道這件事」，並讓 `test_view_hiding.py` 涵蓋它。
- 文件（包括這份）不寫人物祕密、隱藏設定內容、事件鏈與驚喜。
- 新增會被說出口的事實類型時，在 `speech.SPOKEN` 補口語說法、在 `speech.story_key` 決定它屬於哪個故事；只影響措辭的隨機一律用 `speech.pick`／`speech.chance`（文字專用亂數），不要用 `world.rng`——措辭不該改變世界的走向。
- NPC 台詞不要直接把 `fact_text`（紀錄體）塞進引號；走 `speech.retell`／`speech.spoken`。
- 改平衡後跑全部測試；`test_causality.py` 的範圍斷言失敗時，先讀編年史判斷是平衡跑掉還是斷言過嚴，再決定改哪一邊。
