# 文字冒險遊戲（Ollama 本地文字 RPG）— CLAUDE.md

> 通用操作規則（Bash、修改前讀檔、commit 規範等）見全域 `~/.claude/CLAUDE.md`。
> 本檔案只放這個專案專屬的事實與決策，不重複全域內容。
> 詳細除錯過程、實測數據、before/after 對照、假設驗證紀錄見 `DEVLOG.md`（平常不用讀，只有要追溯「這個決定當初怎麼查出來的」才回去翻）。
> 如果之後想往「NPC關係自我演化、多元宇宙」這類更宏大的方向擴充，先看 `終極願景.md`——平常完全不用管，這份純粹是設計者自己的長期方向筆記，不是待辦清單，不影響現在的開發工作。

## 專案現況

MVP 已從單一 NPC、單一場景擴充成多 NPC（`npc_wang` 老王、`npc_ayue` 阿月、`npc_ayue_mother` 阿月的母親、`npc_debtor` 討債人、`npc_vendor` 陳伯、`npc_innkeeper` 孫掌櫃）、多場景（`SCENES` registry：`tavern` 老王酒館、`street` 酒館外街道、`market` 市集、`inn` 客棧、`gate` 鎮口、`dojo` 武館、`ayue_home` 阿月家），核心 pipeline 穩定：Call 1（敘事生成）/ Call 2（好感度判定）拆分呼叫、Call 2 用 `temperature:0`+`seed:42`、JSON 用括號深度解析法容錯、輸出開頭結尾殘留符號有 `strip_residue` 過濾、好感度用分級描述餵給模型（不直接給精確數字）。長期記憶已接上 Qdrant + `bge-m3`（2026-07-13 起都搬到 NAS，192.168.113.112），驗證過能自然引用過去事件、不是死記憶也不是照抄。

**小鎮擴張第一步（2026-07-18）**：街道從單純的過場場景升級成真正的樞紐——新增「街道 → 市集」的 `scene` 型選項，市集是這個小鎮第二個真正的場景（`ayue_home` 屬於需要 flag 解鎖的支線場景，不算在內），裡面有第一個完全獨立於老王/阿月故事線的 NPC「陳伯」（雜貨攤販）。這是專案第一次驗證「一個場景輻射連到多個新地方」這種導航模式，已驗證完整路徑（酒館→街道→市集→街道→酒館）每一步的選項清單、`state["location"]`、記憶查詢隔離性都正確，架構撐得住。

**小鎮擴張到中等規模（2026-07-19）**：街道再輻射出三條新出口——`inn` 客棧（有真正的 NPC「孫掌櫃」，跟其他 NPC 一樣走通用好感度追蹤，沒有另外新增任何標記機制）、`gate` 鎮口（純氛圍場景，沒有 NPC，選項是 `flavor` 型，暗示小鎮以外還有更大的世界，純敘事鋪墊、這次不做任何機制）、`dojo` 武館（目前先當空場景，沒有真正的 NPC，選項同樣是 `flavor` 型）。三個新場景都比照 `market` 的既有模式（`intro`／`scene_atmosphere`／`options`），沒有更動任何核心機制。已驗證完整路徑（酒館→街道→客棧→街道→鎮口→街道→武館→街道→市集→回酒館，共10次場景切換）選項清單、`state["location"]` 全部正確；跟孫掌櫃的真實 Call1+Call2 互動（10次獨立呼叫）驗證通過，敘事語氣（見多識廣、話說得不緊不慢、有所保留）跟其他 NPC 風格明顯區隔。

「珠子拼線」設計（見 `終極願景.md` 擴充方向七）已有第一次實作：老王的第一顆故事珠子「被討債的人纏上」（`wang_debtor_trouble` 選項），表面獨立於阿月線（不要求任何阿月相關前提），已驗證兩條線的 flag/affinity 完全互不干擾。第二個 NPC 故事線正式起步。

`wang_debtor_trouble` 現在需要先鋪墊過才會出現：老王的日常互動（一般 `npc` 型選項）判定成功時，Python 有 `WANG_DEBT_MENTION_CHANCE`（30%）機率決定這回合要不要讓 Call1 順帶帶到討債人這件事（`flavor_hint` 機制，跟 `scripted_outcome` 是姊妹但語意不同：一個是「這回合已確定的事」，一個是「這回合可以輕描淡寫帶到的背景細節」），成功才觸發 `mentioned_wang_debt`，`wang_debtor_trouble` 才會浮現。已驗證：新開一局選項不可見、多輪互動後 flag 觸發、選項正確浮現。

選項系統支援四種型別（`npc`／`scene`／`flavor`／`npc_scripted`，見 `game_mvp.py` 裡 `SCENES` 上方的註解），場景切換、離開遊戲都已驗證正常運作。選項可選帶 `requires_flag`，玩家沒觸發對應旗標時該選項不會出現在選單（也不會浪費雲端呼叫去生成它的措辭）——目前唯一的例子是「跟著阿月回家看看」，觸發 `offered_help_ayue` 這個 flag 才會解鎖。`flags_set` 已正式加進 schema（鎖 `FLAG_WHITELIST` 白名單），`state["player"]["flags"]` 也已真正用起來。選項文字生成可選走雲端 API（`.env` 設 `CLOUD_API_KEY`），沒設定或呼叫失敗一律 fallback 回寫死文字並印出訊息，已驗證雲端成功路徑（文字會依情境變化）跟三種 fallback 路徑（沒設key／呼叫例外／數量對不上）都正常。

玩家能力數值已加入：`state["player"]` 不存 prowess 數值本身，只存 `prowess_growth_count`（成功次數，整數）。`npc_scripted` 型選項的判定是機率制：`resolve_scripted_outcome(base_success_rate, prowess_bonus)` 把「基礎成功率（依 state，例如好感度）」跟「玩家數值修正」相加後 clamp 在 5-95 之間再擲骰，取代原本純粹寫死的門檻二選一。`ayue_secret_money` 已改用這個函式（好感度決定 base_rate 70 或 30，prowess 每偏離 `PROWESS_BASE`（5.0）一點修正 ±4，直接讀 `current_prowess()` 算出的精確值、不四捨五入），實測驗證過 prowess 越高、成功率確實統計上越高。`prowess` 的成長曲線是微分方程解析解 `prowess_at(base, ceiling, growth_count, rate)`（`= ceiling - (ceiling - base) * e^(-rate·growth_count)`），對任何有限 `growth_count` 數學上都嚴格小於 `PROWESS_BOUND`，判定成功時 `outcome` 帶的 `grow_prowess: True` 會被 `apply_turn_result()` 套用（只是 `prowess_growth_count += 1`），只有「四捨五入後顯示的整數」真的變了才印出「[你的膽識似乎更加沉穩了]」。`grow_prowess` 是通用布林參數，之後其他 `npc_scripted` 選項要接同一套成長邏輯只要在 outcome 裡加這個 key。**注意**：`prowess_at()` 雖然是解析解，但在 float64 實務精度下 `growth_count≥121` 時就會精確等於 `PROWESS_BOUND`（浮點數表示法的必然限制，不是實作或公式錯誤），使用者已確認這個現實遊玩中不可能觸及的邊界情況維持現狀、不進一步處理（詳見 DEVLOG.md）。

已知一個刻意接受的限制，見下方「已知限制」。

## 專案目標

LLM 驅動的文字 RPG。選項有限（非全開放輸入），少量自訂輸入格。核心賣點是「記得玩家做過的事」，所有架構決策圍繞這個賣點展開。

## MVP 範圍（第一階段只做這些，不要超做）

> 範圍已於 2026-07-12 擴充至多 NPC、多場景 + Qdrant 長期記憶 + 雲端選項文字生成（見上方專案現況），以下是最初的最小可玩版本定義，供對照，非現況。

- 1 個場景，2-3 個固定選項（自訂輸入格、別名比對、隱藏觸發詞清單先不做）
- 1 個 NPC，背景故事只寫 3-5 條事實
- State 存在記憶體裡的一個 Python dict（不接 MongoDB）
- 完全不用 Qdrant／向量記憶（NPC 記憶先靠塞最近幾句對話進 context）
- `affinity` 只留一個數字（`hard`/`soft` 雙軌先不分）
- 呈現層用 CLI（不做網頁）
- 模型設定：`qwen3.5:9b`，`think: false` + `num_ctx: 8192`
- `state_delta` schema 最小版：只要 `narrative` + 一個鎖 enum(-1/0/+1) 的好感度欄位

完整升級路徑對照（撞到對應問題才翻 `文字RPG架構決策.md` 裡的對應章節，不用預先讀）：
自訂輸入格 → 第8節；schema 鐵律/踩坑 → 第4.1、9節；資料儲存 → 第5節；好感度雙軌 → 第4.6節；NPC背景設計 → 第4.7節；NAS搬遷 → 第6節；效能/卡頓 → 第4.3、4.4節；呈現層選型 → 第7節。

## 技術棧（已定案）

- 後端/orchestrator：Python
- 敘事生成模型：`qwen3.5:9b`（Ollama，留在筆電，需 GPU、低延遲）
- Embedding 模型：`bge-m3`（2026-07-13 起搬到 NAS，`ollama-embed` container，192.168.113.112:11434，1024維，`/api/embed`）
- 向量資料庫：Qdrant（2026-07-13 起搬到 NAS，`qdrant` container，192.168.113.112:6333；部署細節、防火牆考量見 DEVLOG.md）
- State 資料庫：MongoDB（NAS 既有服務；MVP 階段先用記憶體 dict 代替，不急著接）
- 呈現層：CLI（MVP）→ Web／HTML+CSS（驗證過後）。**已排除 Pygame**（文字排版能力陽春，不適合本專案的內容型態）
- 選項文字生成：雲端 API（OpenAI 相容介面，預設 SiliconFlow，模型 `Qwen/Qwen3.5-9B`，需 `enable_thinking: false` 否則會逾時），跟本地 Ollama 分開一支函式。金鑰從 `.env` 讀取（複製 `.env.example` 建立，簡易手動解析，沒引入 python-dotenv），`.env` 不進版控。沒設定/呼叫失敗/回傳數量對不上，三條路徑都會 fallback 回寫死的 `OPTIONS` 文字並印出訊息，不影響遊戲能不能玩

## 已定案的架構原則

- **核心迴圈留本地、周邊功能可雲端**：高頻呼叫、且行為已被實測調校過的核心邏輯（本專案的敘事生成 Call 1、好感度判定 Call 2）留在本地模型，不要換；低頻、非核心、且有明確 fallback 能接手的周邊功能（例如選項文字生成）可以改用雲端 API。分界依據是「呼叫頻率＋是否核心＋有沒有安全網」，不是隨意決定哪個方便就用哪個
- **效果需要100%確定的分支，交給規則決定，不要交給 Call2 判定**：`OPTIONS` 的 `"npc_scripted"` 型別是這個原則的實作——像「好感度過門檻才會被接受」這種關鍵劇情分支，delta/flag 由 Python 規則依當下 state 直接決定，只把「怎麼把這個結果講成故事」交給 Call1，完全跳過 Call2。跟一般 `"npc"` 型選項（delta 完全交給 Call2 讀 narrative 判定）的差異在於：一般互動的好感度浮動本來就允許隨機性，但「觸發關鍵flag」這種一次性、不可逆的狀態轉換不該讓 LLM 的隨機判定去決定要不要發生
- **`npc_scripted` 的機率判定是 Python 端純數值運算，不違反下方 Schema 鐵律**：`resolve_scripted_outcome()` 用的 `base_success_rate`／`prowess_bonus`／擲骰結果，全程只在 Python 端流動，從來不會被塞進 LLM 的 output schema，LLM 只負責讀已經決定好的結果去講故事（`scripted_outcome` 參數）。跟「LLM output schema 絕不開放數字欄位」是兩件事：那條鐵律管的是「不能讓 LLM 自己吐數字出來當 state 變化依據」，這裡是「Python 規則自己算好數字，只把結果的敘事包裝丟給 LLM」，跟 `OFFER_HELP_THRESHOLD` 的既有用法同一類
- **特例：`prowess_at()` 改成微分方程解析解，判準是理論嚴謹性，不是效能或體驗**——這個專案絕大多數決策的判準都是「實測效果」「玩家體感」（例如 tier 描述邊界鬆動、`PROWESS_LEARNING_RATE` 之類的參數都是先猜、playtest 後再調），這條是特例：從離散累加版本換成解析解版本，純粹是因為前者在數學上不是真正的漸近線（每次都疊加一次有限增量，浮點誤差會累積），跟效能、手感、bug 都無關，值得記住這條決策的判準跟其他條不同，之後如果要「反向」評估這個決定該不該回頭改，不要套用「有沒有影響體驗」這個一般判準去衡量
- **`npc_scripted` 選項的成功率門檻/基礎值放在選項資料本身，不寫死在 `main()` 裡**：`success_threshold`／`base_rate_above`／`base_rate_below` 是每個 `npc_scripted` 選項自己帶的欄位（`main()` 讀 `option["..."]`，不是讀某個特定選項專屬命名的模組常數），這是加入 `wang_debtor_trouble`（第二個用這個機制的選項）時做的泛化——不同珠子、不同角色的門檻/基礎成功率沒有理由綁在同一組常數上（例如 `ayue_secret_money` 跟 `wang_debtor_trouble` 現在各自有自己的 `..._THRESHOLD`／`..._BASE_RATE_ABOVE/BELOW` 常數，只是被塞進各自選項的欄位裡）。`PROWESS_BONUS_PER_POINT`（prowess 修正幅度）跟 `grow_prowess`（要不要成長）維持全域共用，因為這兩者是玩家數值本身的通用規則，不是個別劇情珠子的設定
- **一般 `npc` 型選項也能鋪墊未來會解鎖的內容，機制是「Python 先擲骰決定要不要嘗試，Call2 判定結果出來後才確認旗標」，不是讓 LLM 自己判斷**：`main()` 在呼叫 `call_llm()` 之前，先用 `random.randint()` 決定這輪要不要帶 `flavor_hint`（因果順序限制：Call1 要先知道「這輪要不要提」才能寫進敘事，但「這次算不算成功」要等 Call2 判定完才知道），所以拆成兩段：擲骰的「嘗試」在 Call1 之前決定，旗標的「確認」在拿到 delta 之後才套用（`debt_mention_attempted and delta == 1`）。跟 `npc_scripted` 的差異：`npc_scripted` 完全跳過 Call2、效果 100% 由規則決定；這裡 Call2 照常跑、旗標只是疊加在正常判定結果之上的額外條件，兩者都不讓 LLM 自己決定「要不要觸發」，差別只在要不要跳過好感度判定本身

## 硬體與部署環境

- 筆電：MSI Katana 15，RTX 4060 Laptop GPU（8GB VRAM），RAM 48GB，Ollama 0.31.1，實測可用 VRAM 約 6GB
- NAS：已有 Docker/MongoDB 常駐環境
- 分工原則：只有需要 GPU、低延遲的敘事生成（`qwen3.5:9b`）留在筆電；MongoDB、Qdrant、`bge-m3`、遊戲主程式全部常駐 NAS
- 筆電不開機時：可查歷史記憶、看存檔，但無法生成新的一回合
- Ollama 對外服務需設 `OLLAMA_HOST=0.0.0.0`，Windows 防火牆需放行 11434 port
- NAS SSH 帳號 `claude-deploy`（私鑰 `~/.ssh/claude_nas_deploy`）**沒有 sudo 權限**，無法檢查/修改 ufw 或 iptables。這台 NAS 的 ufw 目前是 inactive（2026-07-13 確認），代表 Docker `-p` port publish 時明確綁定的 IP（例如 `192.168.113.112:port`，只綁區網 IP、不綁 `0.0.0.0`）**是唯一的網路隔離防線**——之後在這台機器上開任何新服務，都要記得沿用「明確綁區網IP」這個做法，不能假設系統防火牆會兜底

## 必要執行設定（已實測驗證，勿省略）

- 呼叫 `qwen3.5:9b` 務必在請求帶 `"think": false`，否則會吐大量 `<think>...</think>` 內容污染結構化輸出管線
- 務必設 `num_ctx: 8192`（Ollama 預設會用模型原生上限 262144 去預留 KV cache，即使對話很短也一樣，是拖垮效能的主因）
- 兩者必須同時設定才有效：thinking 決定「吐多少字」，`num_ctx` 決定「塞不塞得進 VRAM、吐多快」。實測數據見 DEVLOG.md 或 `文字RPG架構決策.md` 第 3.3 節

## Schema 設計鐵律（不可違反）

- LLM 的 output schema **絕不開放任何數字欄位**（hp/damage/gold 等）——結構上沒有位置可填，不是靠 prompt 講規矩
- 需要 LLM 主觀判斷的項目（如好感度浮動）一律收斂成 enum，並在 schema 型別層鎖死允許值
- `flags_set` 比照辦理，鎖 enum 白名單，**不做模糊字串比對/容錯**（理由見下方已知地雷）
- **`flags_set` 的 enum 白名單要跟「所有合法旗標」的白名單分開兩份**：`FLAG_WHITELIST`（`apply_flags()` 套用任何旗標前的總檢查）跟 `LLM_ASSIGNABLE_FLAGS`（`NARRATIVE_SCHEMA` 實際暴露給 Call1 自己判斷輸出的子集）不能是同一份清單——一個旗標只要出現在 `LLM_ASSIGNABLE_FLAGS` 裡，就代表允許 Call1 憑自己對敘事的判斷來觸發它，這對「效果需要100%由規則決定」的旗標（例如 `npc_scripted` 委託完成、Python 擲骰鋪墊）是不能接受的風險。實測證實過（見 DEVLOG.md）：只要旗標名稱在語意上跟敘事內容沾得上邊，Call1 就有機率自己把它塞進 `flags_set`，完全不管好感度判定實際是好是壞。**`LLM_ASSIGNABLE_FLAGS` 目前是空清單，`offered_help_ayue`／`helped_wang_debt`／`mentioned_wang_debt` 三個旗標全部只能由對應的規則路徑觸發（`npc_scripted` 的 `outcome["flag"]` 或 Python 擲骰後的 `apply_flags()`），已個別驗證過一般日常互動的 `flags_set` 不會意外吐出這三個旗標中的任何一個**
- UI 顯示的數字一律直接讀遊戲 state，絕不從 LLM 生成的 narrative 文字裡解析數字回來套用
- narrative 永遠只能是「state 變化之後」的產物，不能反過來當作 state 變化的依據

## 已知地雷（源自舊專案 `ai-novel-generator` 的踩坑紀錄，勿重蹈覆轍）

- **黑名單式事後糾錯打不贏**：模型出錯方式無窮，追不完；門檻鬆會漏抓、緊會誤殺正常輸出。已改用白名單（schema + enum）取代
- **明確排除「相似字串模糊比對/容錯自動修正」**：本專案 flag 命名常見 entity ID 在字尾（如 `met_npc_x` vs `met_npc_y`），模糊比對可能把事件誤套用到指涉完全不同的對象，是「悄悄套用到錯誤對象」而非單純漏記，傷害等級更高。NPC 別名表（第8節）是事先窮舉的精確比對白名單，不是這條規則的例外
- **不要做敘事一致性強制器**（如舊專案的 `character_arc_enforcer.py`）去硬性框住角色行為，會讓角色弧光罐頭化、失去生命力。數值判定與敘事生成必須徹底解離，不寫這類規則框
- **NPC 記憶要餵「事實」，不能餵「劇本」**：context 塞「上次跟你吵過架、你欠他錢」這類事實，不能塞「現在必須用某種固定語氣回話」，後者等於重蹈舊專案覆轍
- **自動一致性檢查/評分機制優先度放最低**：舊專案證明這類機制誤判率天生偏高，會變成需要人工持續維護的假自動化，不預先開發
- **未被選中的預生成分支必須丟棄**：背景緩衝策略會提前生成多個選項的結果，未被玩家選中的 narrative/state_delta 一律整批丟棄，不得寫入正式 state 或長期記憶，否則會污染「記得玩家做過的事」這個核心賣點
- **MongoDB 動態 key 注入風險**：`npc_affinity_delta` 是動態 key 的物件，套用邏輯前必須先驗證每個 key 是否存在於 NPC 白名單中，不在白名單一律丟棄，避免 LLM 吐出含 `$`/`.` 的異常 key 觸發 operator injection

## 已定案的 Prompt Engineering 原則（本專案實測驗證，適用於未來類似情境）

- 對 `qwen3.5:9b` 下技術性限制指示，優先用描述句、避免命令句，尤其避免「否定句 + 格式類技術詞彙（markdown/HTML/JSON）」的組合——這種組合容易誘發模型自我檢查並把檢查過程洩漏進輸出內容
- 餵給 LLM 的狀態數值，用分級描述取代精確數字（例如「對你有些好感，態度和緩」而非「好感度：3」）——精確數字容易被模型讀成一個要持續推進的量化目標
- 分級描述最邊界的那一階（最高/最低）措辭不能寫死絕對，要留機率性鬆動的縫隙——否則邊界值會變成模型自我實現的吸收態，卡住出不來
- 存進長期記憶的內容要用抽象摘要，不能存完整敘事原文——否則模型檢索到記憶時容易整段複製貼上，而不是自然引用；記憶注入 prompt 時也要用比喻式描述句，不要用條列式命令標籤
- **要壓過某個競爭中的背景設定拉力（例如某個NPC的核心事實一直把場景拉回原本的地方），優先用「加強白名單」而不是「排除句/黑名單」**：補一段具體、豐富、純正面的畫面細節（場景氛圍描述），用畫面份量自然壓過去；不要寫「這裡沒有X、沒有Y」這種排除句去對抗——即使短期測試排除句也有效，這種「否定句」跟已經踩過的「否定句+格式類技術詞彙」是同一個風險類別，不值得為了省事去冒險。場景氛圍描述要記得每一輪都塞進 prompt（不是只在切換場景那一刻印給玩家看一次就結束）
- **背景細節要描述「事件/事實」，不要描述「當下情緒狀態」，否則會把整段敘事的語氣染色**：`wang_debtor_trouble` 的鋪墊 hint 第一版寫「他心裡有點煩悶」，實測敘事整段都變成 NPC 對玩家不耐煩、態度冷淡（10輪裡9輪被 Call2 判成負面），連帶拖累好感度；改成純敘述「有這麼一件事，已經是前幾天的事了，講起來像抱怨一件翻篇的小麻煩」，拿掉「當下」「還在困擾」這種進行式張力後，同樣的敘事互動才恢復正常的正負面分布。教訓：跟 NPC 這回合對玩家的**態度**無關的背景資訊，措辭上要明確帶有「已經過去、輕描淡寫」的時態/語氣，不要用「他現在覺得 X」這種當下情緒描述句，即使只是想當「不影響重點的小細節」，模型也會把它讀進整體情緒基調
- **多個 NPC 共用的模板文字（例如 `affinity_tier()` 這種依數值回傳描述句的函式），措辭裡絕對不能寫死特定角色的代名詞**：`affinity_tier()` 的 `value <= -4` 這一階，是當初專門為阿月的 -5 觸底問題調整措辭時寫的，句子裡寫死了「她可能會微微鬆動一點」，但這個函式其實被所有 NPC 共用（包括老王、討債人等男性角色）。如果任何 NPC 的好感度跌到 -4 以下，Call1 就會讀到一句稱呼他為「她」的關係描述，語意錯亂、容易連帶拖累敘事品質。修法：拿掉代名詞，改成不需要主詞的說法（「...可能會微微鬆動一點」），跟其他分級描述句本來就沒有代名詞的寫法一致——中文本來就容易省略主詞，拿掉代名詞完全不影響語意，卻能讓同一句話安全套用在任何 NPC 身上。之後新增或修改任何跨 NPC 共用的模板句時，都要檢查有沒有不小心把某個角色專屬的代名詞/稱呼寫死進去

## 已知限制（刻意接受，不用再處理）

- 阿月（`npc_ayue`）好感度觸底（-5）後的回升機率刻意偏低（實測約 1/4 試驗會回升）、不用再調——這是角色設計的一部分（嘴硬心軟、討厭被同情、要真心誠意才會鬆動，見架構決策文件 4.7 節），不是 bug。相關驗證數據見 DEVLOG.md，不用重新調查或嘗試把成功率調高。2026-07-13 修過 `affinity_tier()` 的代名詞硬寫 bug（把「她可能會微微鬆動一點」改成拿掉代名詞），純粹是措辭層面的修正、語意不變，這個既有的 1/4 回升機率結論不受影響，不用因為這次修改而重新驗證這個數字。

## 可重用的舊專案資源

- 舊專案 `ai-novel-generator` 的 `utils/json_parser.py`：5 層 cascading JSON 容錯解析策略（標準 JSON → 抓 ```json``` 區塊 → 抓任意 code block → 暴力抓 `{...}` → 暴力抓 `[...]`），自成一體、不依賴專案其他部分成熟度，值得直接搬進本專案 `state_delta` 解析層，當 schema validation 之外的第一道防線（註：`game_mvp.py` 實際採用的是更簡單的括號深度計算法，見 DEVLOG.md）

## 尚待設計／待補（開發到那一步再填，不用現在預先規劃）

- MongoDB 實際安裝與連線設定（NAS 分工仍待做；Qdrant 已完成搬遷，見技術棧）
- state schema 版本遷移腳本（`version` 欄位如何驅動遷移邏輯）
- 完整合法 flag 清單（`FLAG_WHITELIST` 目前有 `offered_help_ayue`、`helped_wang_debt`、`mentioned_wang_debt` 三個；`LLM_ASSIGNABLE_FLAGS`——允許 Call1 自己在 `flags_set` 判斷輸出的子集——目前刻意留空，三個旗標都只能由 Python 規則/擲骰觸發，見 Schema 設計鐵律；之後如果真的有旗標適合讓 Call1 自由心證，再考慮放進 `LLM_ASSIGNABLE_FLAGS`）
- NPC 別名表、隱藏觸發詞清單的實際內容
- 各 NPC 核心事實清單（背景、性格、說話風格）
- 待實測調參：`affinity_soft` 上下限（暫定 ±5）、各 NPC 好感度門檻、長期記憶檢索是否疊加 recency 時間衰減——先寫死合理猜測，playtest 後回頭調
- `SCENES[scene_id]["npcs"]`（場景在場NPC清單）目前只是資料，沒有任何程式碼實際讀取它（2026-07-13 確認過），維持先前「長期記憶檢索先不加場景過濾」的決定；如果之後真的要用（例如查詢時依場景過濾、或顯示「這個場景有誰在」），再回頭接上
- `prowess` 目前只有 `ayue_secret_money` 判定成功這一條成長途徑，之後要不要有其他成長來源（例如特定劇情事件、專門的訓練互動）還沒設計；`PROWESS_LEARNING_RATE=0.3` 這個漸近曲線的速度參數也是先猜的，還沒 playtest 調過
- `ayue_secret_money`、`wang_debtor_trouble` 兩個選項接上 `resolve_scripted_outcome()`；`wang_debtor_trouble` 的 outcome 沒有帶 `grow_prowess`（只有 `ayue_secret_money` 有），之後要不要讓解圍討債人也算一種歷練還沒決定；`SECRET_MONEY_BASE_RATE_ABOVE/BELOW`、`WANG_DEBT_BASE_RATE_ABOVE/BELOW` 這幾個基礎成功率數字都是先猜的，還沒 playtest 後調整過
- `prowess_at()` 是微分方程解析解，數學上對任何有限 `growth_count` 都嚴格小於 `PROWESS_BOUND`，但實測發現 float64 精度有限，`growth_count≥121` 時 `ceiling - (ceiling-base)*e^(-rate·growth_count)` 這個減法就會被四捨五入成精確的 `10.0`（見 DEVLOG.md）——這是任何固定精度浮點數表示法的必然結果，改用 `Decimal` 只會把門檻往後推（推不掉），使用者已確認維持現狀、不進一步處理，現實遊玩要連續觸發 121 次判定成功是天文數字級別不可能發生的次數
- 「珠子拼線」（見終極願景.md 擴充方向七）目前只做了老王第一顆珠子（`wang_debtor_trouble`），驗證「一顆獨立珠子能不能自然運作」；還沒加第二顆珠子去驗證「同一組珠子、不同順序做，體感會不會不同」這件事，也還沒接上 Origin 狀態碼式的關聯標記（例如 `origin: "wang_debt_arc"`）；`npc_debtor` 的核心事實裡「上頭的人」是刻意留白的伏筆，之後要不要延伸出一個幕後角色，留到之後再說
- `WANG_DEBT_MENTION_CHANCE=30`（鋪墊 flag 的觸發機率）是先猜的，還沒 playtest 調過；`flavor_hint` 這個「一般 npc 型選項也能鋪墊未來內容」的機制目前只有 `wang_debtor_trouble` 一個用例，之後如果有其他珠子也想用同樣的「先鋪墊、後解鎖」模式，`flavor_hint`／`debt_mention_attempted` 這段邏輯要不要也比照 `success_threshold` 那樣泛化成選項自帶的資料欄位，還沒做
- `npc_vendor`（陳伯）目前只有 2 個 `npc` 型選項（閒聊、打聽消息），沒有任何 `npc_scripted` 或劇情鉤子；核心事實裡「女兒嫁到外地、好幾年沒回來」是刻意留白的伏筆，之後要不要發展成他自己的故事珠子（呼應珠子拼線設計），留到之後再說。市集目前只有陳伯一個 NPC，之後要不要多加攤位/NPC 讓場景更豐富，也還沒規劃
- 街道正式升級成樞紐後，目前有四條輻射線（街道→市集／客棧／鎮口／武館）；之後如果要再加其他地點，`street` 的 `options` 直接比照 `street_goto_market` 這個 `scene` 型選項的模式加一筆即可，不需要改動樞紐本身的架構
- `npc_innkeeper`（孫掌櫃）目前只有 2 個 `npc` 型選項（問候、打聽旅人），沒有任何 `npc_scripted` 或劇情鉤子；核心事實裡「客人喝多了吐真言，他聽過不少故事，只是從不主動提起」是刻意留白的伏筆（他可能知道其他 NPC 線的內幕），之後要不要接上劇情鉤子還沒設計
- `gate`（鎮口）跟 `dojo`（武館）目前都是空場景（`npcs: []`），選項只有 `flavor` 型（純敘事，不呼叫 Call1）+ 回街道。`gate` 刻意鋪了「小鎮以外還有更大的世界」這個伏筆，對應終極願景.md 裡「懶惰生成」的擴展方向，但這次刻意不做任何機制；`dojo` 純粹先佔位，之後想加真人 NPC（例如武館師傅）再回頭接上，不需要改動場景本身的資料結構

## 參考文件

- `文字RPG架構決策.md`（本資料夾內）— 完整架構藍圖。每節對應「之後撞到某個具體問題時才對應加上去的升級包」，不是起跑門檻，不用一次讀完
- `DEVLOG.md`（本資料夾內）— 除錯過程、實測數據、假設驗證與推翻的完整紀錄，依時間順序排列
- `終極願景.md`（本資料夾內）— 長期、遙遠的方向筆記（去中心化世界、多元宇宙等），平常不用讀，只有要做可能影響長期方向的決策時才回頭對一下有沒有衝突
