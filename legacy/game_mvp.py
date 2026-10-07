"""
文字 RPG — MVP 雛型
對應「文字RPG架構決策.md」第 0 節的最小可玩版本規格（NPC、場景都已從單一擴充成多個，用 id 查表）：
  - 多個場景（SCENES registry，用 scene_id 查表），場景間可用「scene」型選項切換，街道已升級成樞紐（見 DEVLOG.md）
  - 多個 NPC，用 npc_id 查表（NPCS registry），核心事實寫死（見 4.7 節原則）
  - state 存在記憶體 dict，不接資料庫
  - 長期記憶已接 Qdrant + bge-m3（見 5.5 節；2026-07-13 起兩者都已搬到 NAS，192.168.113.112）
  - affinity 只有一個數字（hard/soft 雙軌是之後的升級，見 4.6 節）
  - CLI 呈現（見第 7 節）
  - qwen3.5:9b，think:false + num_ctx:8192（見第 3 節已實測設定）
  - 選項文字生成改走雲端 API（核心迴圈 Call1/Call2 仍是本地 Ollama，不動）
  - flags_set 已正式加進 schema（鎖 enum 白名單，見 FLAG_WHITELIST），"npc_scripted" 型選項的效果由規則決定：
    基礎成功率依好感度，疊加玩家 prowess 數值修正（resolve_scripted_outcome()），只有敘事交給 Call1；
    prowess 只存 growth_count（整數，見 state），精確值即時用微分方程解析解 prowess_at() 算
    （current_prowess()），對任何有限 growth_count 都嚴格小於 PROWESS_BOUND；顯示給玩家看時才 round()

前置需求：
  1. 本機跑著 `ollama serve`（或背景服務已啟動），已 `ollama pull qwen3.5:9b`（敘事生成，維持在筆電）
  2. NAS（192.168.113.112）上跑著 `qdrant` container（6333）跟 `ollama-embed` container（11434，已 `ollama pull bge-m3`）——
     部署方式見 DEVLOG.md，兩個 port 都明確綁定 NAS 的區網 IP，只有同一區網連得到
  3. `pip install requests`
  4. 選填：把 `.env.example` 複製成 `.env`，填入 `CLOUD_API_KEY`（OpenAI 相容雲端 API 的金鑰，例如矽基流動/SiliconFlow）。
     `.env` 不存在或沒填 key 都會直接 fallback 回寫死的選項文字，不影響遊戲能不能玩、也不會報錯。
     `.env` 不進版控（見 .gitignore），已存在的環境變數優先於 `.env` 裡的值。
     可選：`CLOUD_API_BASE_URL`（預設 SiliconFlow）、`CLOUD_MODEL`（預設 `Qwen/Qwen3.5-9B`，已對照 SiliconFlow 目錄確認存在）
"""

import json
import math
import os
import random
import re
import sys
import time

import requests


def load_dotenv(path: str | None = None) -> None:
    """簡易 .env 解析（不用 python-dotenv，維持專案只依賴 requests 的原則）。
    檔案不存在就直接跳過，不報錯；已存在的環境變數優先，不會被 .env 覆蓋掉。"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


load_dotenv()

OLLAMA_URL = "http://localhost:11434/api/chat"  # 敘事生成 qwen3.5:9b，需GPU/低延遲，維持在筆電
OLLAMA_EMBED_URL = "http://192.168.113.112:11434/api/embed"  # bge-m3，已搬到NAS（ollama-embed container）
MODEL = "qwen3.5:9b"
EMBEDDING_MODEL = "bge-m3"

QDRANT_URL = "http://192.168.113.112:6333"  # 已搬到NAS（qdrant container）
MEMORY_COLLECTION = "memories"
MEMORY_VECTOR_SIZE = 1024  # bge-m3 dense embedding 實測維度
MEMORY_TOP_K = 4

# ---------- 雲端 API（選項文字生成專用，核心迴圈 Call1/Call2 維持本地 Ollama 不動） ----------
# OpenAI 相容介面（例如矽基流動/SiliconFlow），key 一律從環境變數讀，不寫死在程式碼裡
CLOUD_API_BASE_URL = os.environ.get("CLOUD_API_BASE_URL", "https://api.siliconflow.cn/v1")
CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY")
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "Qwen/Qwen3.5-9B")  # 已對照 SiliconFlow /v1/models 目錄確認存在（見 DEVLOG.md）

# 開頭/結尾殘留的格式符號：純符號（{}[]<>*_`~|）或 HTML tag（如 <br>）
_RESIDUE_EDGE = re.compile(r"^(?:[{}\[\]<>*_`~|]|<[^<>]{0,20}>)+|(?:[{}\[\]<>*_`~|]|<[^<>]{0,20}>)+$")


def strip_residue(text: str) -> str:
    return _RESIDUE_EDGE.sub("", text).strip()


# ---------- JSON 容錯解析：括號深度計算法，從第一個 { 開始找配對的 }，抓出第一個完整物件 ----------
# 深度計算會避開字串裡的 { }（靠 in_string 狀態），不會被 narrative 內容裡混進的括號字元誤導
def parse_llm_json(content: str) -> dict:
    start = content.index("{")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(content[start : i + 1])
    raise ValueError(f"找不到完整的 JSON 物件：{content!r}")


# ---------- NPC 核心事實 registry（先寫死，見 4.7 節：不能用 LLM 即時生），用 npc_id 查表 ----------
NPCS = {
    "npc_wang": {
        "name": "老王",
        "facts": [
            "老王在這間小酒館當老闆兼酒保，已經十五年了。",
            "老王年輕時欠過一屁股債，所以特別看不慣揮霍的人。",
            "老王嘴巴很硬，常常口氣很衝，但其實心腸很軟，常常偷偷幫街坊付酒錢。",
            "老王其實很怕黑，酒館打烊後他一定會把每一盞燈都留到最後才關。",
        ],
    },
    # 初稿，待調整：19歲女孩，在老王酒館端酒打雜兩年多
    "npc_ayue": {
        "name": "阿月",
        "facts": [
            "阿月是老王雇來幫忙端酒、擦桌子的女孩，今年十九歲，在酒館做了兩年多。",
            "她總是笑嘻嘻地跟客人搭話，看起來天不怕地不怕，其實心裡藏著一件事：家裡母親臥病在床，欠了不少醫藥費。",
            "阿月很崇拜老王，把他當成半個父親看待，卻不知道老王早就在偷偷幫她墊付一部分醫藥費。",
            "她討厭被人可憐或施捨，只要有人一副同情她的樣子，她就會立刻擺臭臉、轉移話題。",
            "阿月很會看人臉色，能一眼看出客人是不是想找麻煩，這是她在酒館工作練出來的本事。",
        ],
    },
    # 戲份天生很輕，只給極簡的核心事實，不比照老王阿月那麼完整
    "npc_ayue_mother": {
        "name": "阿月的母親",
        "facts": [
            "阿月的母親長年臥病，精神時好時壞，清醒時總是絮絮叨叨叮嚀阿月要照顧好自己。",
            "她的醫藥費一直是阿月最大的負擔，但她自己並不完全清楚阿月在外面吃了多少苦。",
        ],
    },
    # 老王第一顆故事珠子（見終極願景.md 擴充方向七：珠子拼線）用的一次性 NPC，戲份輕，「上頭的人」是刻意留白的伏筆
    "npc_debtor": {
        "name": "討債人",
        "facts": [
            "他受雇替人討債，手段不算太狠，但很纏人。",
            "他自己也欠著一屁股債，接這差事是為了還債，不是真心想為難人。",
            "他不知道老王年輕時也曾經歷過一模一樣的處境。",
            "他從沒提過雇主是誰，只說「上頭的人」，語氣裡帶著一絲畏懼。",
        ],
    },
    # 市集場景的核心 NPC，戲份份量介於「阿月的母親」（極簡）跟「阿月／老王」（完整）之間——
    # 之後可能有互動空間（例如買賣、打聽消息），但不是核心角色，先給 3 條核心事實
    "npc_vendor": {
        "name": "陳伯",
        "facts": [
            "陳伯在市集擺了一個雜貨攤，賣柴米油鹽、針線雜貨，在這一帶擺攤將近二十年。",
            "他嗓門大、愛講價，但市集裡誰家發生什麼事，大概都逃不過他耳朵，消息很靈通。",
            "他有個女兒嫁到外地，好幾年沒回來看他了，偶爾提起會突然沉默一下。",
        ],
    },
    # 客棧場景的核心 NPC，份量比照陳伯（3條核心事實），一樣走通用的好感度追蹤機制，不額外新增標記
    "npc_innkeeper": {
        "name": "孫掌櫃",
        "facts": [
            "孫掌櫃經營這間客棧十幾年，房間不多，但總收拾得乾乾淨淨。",
            "他見多識廣，南來北往的旅人他都招待過，說話總是不緊不慢，帶著幾分閱歷。",
            "他其實不太愛管別人的事，但客人喝多了吐真言，他聽過不少故事，只是從不主動提起。",
        ],
    },
}

# ---------- state（記憶體 dict，MVP 階段不接資料庫） ----------
state = {
    "turn_count": 0,
    "location": "tavern",  # 見架構決策文件 5.2 節，對應 SCENES 的 key
    "player": {
        "flags": {},  # 見 5.2 節；flags_set 觸發的旗標存這裡，key是flag名稱，value是True
        # prowess 不直接存數值，只存成功次數（整數，沒有浮點數精度問題）；當下的精確值即時用 prowess_at() 算，見 current_prowess()
        "prowess_growth_count": 0,
    },
    "npcs": {
        # affinity：單一數字，範圍大約 -5 ~ 5，MVP 先不分 hard/soft
        # option_counts：這個 NPC 的每個選項各被問過幾次，餵給敘事呼叫提示模型別重複
        "npc_wang": {"affinity": 0, "option_counts": {}},
        "npc_ayue": {"affinity": 0, "option_counts": {}},
        "npc_ayue_mother": {"affinity": 0, "option_counts": {}},
        "npc_debtor": {"affinity": 0, "option_counts": {}},
        "npc_vendor": {"affinity": 0, "option_counts": {}},
        "npc_innkeeper": {"affinity": 0, "option_counts": {}},
    },
}

AFFINITY_BOUND = 5  # 見架構決策文件 4.6 節
PROWESS_BASE = 5.0  # prowess 的起始值（growth_count=0 時的值），也是 resolve_scripted_outcome 疊加修正的中位數基準
PROWESS_BOUND = 10  # prowess 漸近上限，見 prowess_at()：微分方程解析解，數學上嚴格小於這個值，不需要 clamp
PROWESS_LEARNING_RATE = 0.3  # 漸近曲線的成長速率

# 見 5.3 節鐵律：flags_set 鎖 enum 白名單，不做模糊字串比對。這是套用 apply_flags() 時的總合法清單
# （不管旗標是 Call1 自己在 flags_set 判斷出來的，還是 Python 規則直接決定的，套用前都要通過這道檢查）
FLAG_WHITELIST = ["offered_help_ayue", "helped_wang_debt", "mentioned_wang_debt"]

# NARRATIVE_SCHEMA 的 flags_set 只暴露這個子集給 Call1 自己判斷要不要輸出。目前刻意留空：
# 三個既有旗標（offered_help_ayue／helped_wang_debt／mentioned_wang_debt）分別由各自的 npc_scripted 規則
# 或 Python 擲骰 100% 決定觸發時機，一個都不該讓 Call1 自己判斷。實測證實這個風險是真的：一般 wang_business
# 互動只是敘事帶到「討債」，Call1 就自己把 helped_wang_debt（原本只該由完成委託觸發）塞進 flags_set 輸出，
# 而且那輪 delta 還是 -1（互動判定成不成功跟旗標完全兜不起來）——見 DEVLOG.md。
# 之後如果真的有旗標適合讓 Call1 自己判斷觸發時機（不需要 100% 精確、允許模型自由心證的情境），才放進這裡
LLM_ASSIGNABLE_FLAGS = []

# 好感度高於這個值才會坦然接受幫助，不高於就觸發防備反應——先用猜的，之後可調
OFFER_HELP_THRESHOLD = 0

# 旗標對應的「已發生事實」：(適用的 npc_id, 要塞進 context 的那句話)
FLAG_FACTS = {
    "offered_help_ayue": ("npc_ayue", "你曾經在她最需要的時候，悄悄塞錢幫過她一次，她一直記在心裡。"),
    "helped_wang_debt": ("npc_wang", "你曾經在他被討債的人纏上時，出面幫他解決了這件事，他一直記在心裡。"),
}


def apply_flags(flags: list[str]) -> None:
    for flag in flags:
        if flag in FLAG_WHITELIST:
            state["player"]["flags"][flag] = True


def get_flag_facts(target_npc_id: str) -> list[str]:
    return [fact for flag, (npc_id, fact) in FLAG_FACTS.items() if npc_id == target_npc_id and state["player"]["flags"].get(flag)]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# prowess 的漸近成長曲線：微分方程 d(prowess)/d(growth_count) = rate * (ceiling - prowess) 的解析解。
# 跟「每次成功都疊加一次離散增量」的差異：離散版本的浮點數誤差會在有限次數內真的精確撞到 ceiling（見 DEVLOG.md 的
# 46 次實測案例），這個封閉解版本是連續函式，任何有限的 growth_count 代入都嚴格小於 ceiling，不會有這個問題。
# state 只存 growth_count（整數，沒有精度累積問題），當下的精確值永遠即時用這個函式重新算，不快取成浮點數欄位。
def prowess_at(base: float, ceiling: float, growth_count: int, rate: float = PROWESS_LEARNING_RATE) -> float:
    return ceiling - (ceiling - base) * math.exp(-rate * growth_count)


def current_prowess() -> float:
    return prowess_at(PROWESS_BASE, PROWESS_BOUND, state["player"]["prowess_growth_count"])


# npc_scripted 型選項的成功率判定：基礎難度（依當下 state，例如好感度）+ 玩家數值修正，取代原本純粹寫死的常數門檻
def resolve_scripted_outcome(base_success_rate: float, prowess_bonus: float = 0) -> bool:
    final_rate = clamp(base_success_rate + prowess_bonus, 5, 95)
    return random.randint(1, 100) <= final_rate


# ayue_secret_money 用：好感度高低先給一個基礎成功率（取代原本的好感度二選一門檻），再疊加 prowess 修正
SECRET_MONEY_BASE_RATE_ABOVE = 70  # 好感度 > OFFER_HELP_THRESHOLD 時的基礎成功率
SECRET_MONEY_BASE_RATE_BELOW = 30  # 好感度 <= OFFER_HELP_THRESHOLD 時的基礎成功率
PROWESS_BONUS_PER_POINT = 4  # prowess 每偏離 PROWESS_BASE 1點，成功率 +/- 這個值（跨選項共用的全域修正幅度）

# wang_debtor_trouble 用：跟 ayue_secret_money 同一套機制（好感度決定基礎成功率、疊加 PROWESS_BONUS_PER_POINT），
# 門檻/基礎值各自獨立設定，不共用 OFFER_HELP_THRESHOLD/SECRET_MONEY_BASE_RATE_*（不同珠子、不同角色，數字沒有理由綁在一起）
WANG_DEBT_THRESHOLD = 0  # 好感度高於這個值，處理討債人比較有底氣，基礎成功率較高
WANG_DEBT_BASE_RATE_ABOVE = 70
WANG_DEBT_BASE_RATE_BELOW = 30

# 老王日常互動（一般 npc 型選項）判定成功時，額外疊加這個機率去鋪墊「被討債的人纏上」——
# Python 決定要不要這回合帶到（見 main() 裡的擲骰），Call1 只負責把已經決定好的事寫進敘事（flavor_hint），
# 不讓 LLM 自己判斷「這次要不要提」，理由跟 npc_scripted 一樣：機率要 100% 由規則控制，不能交給模型自由心證
WANG_DEBT_MENTION_CHANCE = 30  # 百分比
# 見 DEVLOG.md：前兩版都失敗了——「他心裡有點煩悶」這種當下情緒描述、以及「當下正被討債人纏上、還沒跟任何人細說」
# 這種進行式張力，都會讓整段敘事讀起來像老王在防備/心虛，被 Call2 判成負面互動（實測 13 輪裡 12 次 -1，0 次 +1）。
# 改成「已經是前幾天的事，講起來像在抱怨一件翻篇的小麻煩」，拿掉當下的緊張感，才不會逼老王對玩家擺出防備姿態
WANG_DEBT_MENTION_HINT = "前幾天有個討債的人找上老王，那件事現在已經算是過去了，偶爾想到還是有點沒好氣，但更像在抱怨一件麻煩事，不是什麼放不下的心事。"


def affinity_tier(value: int) -> str:
    if value >= 4:
        return "對你相當信任、態度友善"
    if value >= 2:
        return "對你有些好感，態度和緩"
    if value <= -4:
        return "對你很有戒心，話說得很衝，但如果你做出明顯不同以往、真心誠意的舉動，可能會微微鬆動一點"
    if value <= -2:
        return "對你有點提防，語氣偶爾帶刺"
    return "對你的態度普通，還在觀察你"


# 最近幾輪對話，各 NPC 分開存，塞進下一次呼叫的 context 時不互相汙染（見 4.1 節：只給這次判斷真正需要的資訊）
conversation_history: dict[str, list[dict]] = {npc_id: [] for npc_id in NPCS}

# ---------- 場景 registry（見 5.2 節，用 scene_id 查表；每個場景自帶固定選項清單） ----------
# 選項的 "type" 決定 main() 怎麼處理這個選項：
#   "npc"          → 走完整的 Call1/Call2 pipeline（既有機制，不動）
#   "scene"        → 純狀態切換：state["location"] 改成 target，印新場景的 intro，不呼叫任何 LLM
#   "flavor"       → 印一句寫死的 response，不呼叫 LLM、不改 location（見 4.2 節：規則表查詢，不呼叫LLM）
#   "npc_scripted" → 效果（delta/flag）由規則依當下好感度先判斷好，只有「怎麼講成故事」交給 Call1；
#                    不呼叫 Call2。選項本身要帶 outcome_below/outcome_above 兩個結果（各含 delta/flag/hint）
# 選項可選帶 "requires_flag"：值是 flag 名稱，玩家還沒觸發這個 flag 時，這個選項不會出現在 display_options 裡
# （見 get_visible_options()，過濾發生在丟去雲端生成措辭之前，未解鎖的選項不會浪費雲端呼叫）
SCENES = {
    "tavern": {
        "name": "老王酒館",
        "intro": (
            "夜幕低垂，你推開了「老王酒館」的木門。吧台後，老王正低頭擦拭著一只酒杯，"
            "見你進來，只是抬了抬眼皮，沒說話。角落裡，端著酒盤穿梭在桌子間的阿月，"
            "抬頭朝你露出一個燦爛的笑容。"
        ),
        # 每一輪都會塞進 build_system_prompt()（不只是進場景那一刻），用具體畫面份量撐住場景感
        "scene_atmosphere": (
            "酒館裡瀰漫著酒香與煙草味，木頭吧台被歲月磨得發亮，牆上掛著幾串乾燥的辣椒和一盞昏黃的油燈。"
            "幾張木桌散落各處，地上鋪著吸了不少酒漬的舊木板，遠處角落堆著幾個空酒桶。"
        ),
        "npcs": ["npc_wang", "npc_ayue"],
        "options": [
            {"id": "wang_business", "text": "跟老王攀談幾句，問問今天生意如何", "type": "npc", "target": "npc_wang"},
            {"id": "wang_compliment", "text": "點一杯酒，稱讚老王調酒的手藝", "type": "npc", "target": "npc_wang"},
            {"id": "ayue_greet", "text": "跟阿月打個招呼，問問她今天忙不忙", "type": "npc", "target": "npc_ayue"},  # 中性
            {"id": "ayue_concern", "text": "關心地問阿月，最近是不是遇到什麼煩心事，臉色看起來不太好", "type": "npc", "target": "npc_ayue"},  # 關心
            {"id": "ayue_tease", "text": "笑著調侃阿月，說她笑得這麼燦爛，該不會是想跟你多要點小費", "type": "npc", "target": "npc_ayue"},  # 調侃
            {
                "id": "ayue_secret_money",
                "text": "趁四下無人，偷偷塞一點錢給阿月",
                "type": "npc_scripted",
                "target": "npc_ayue",
                "success_threshold": OFFER_HELP_THRESHOLD,
                "base_rate_above": SECRET_MONEY_BASE_RATE_ABOVE,
                "base_rate_below": SECRET_MONEY_BASE_RATE_BELOW,
                "outcome_below": {
                    "delta": -1,
                    "flag": None,
                    "hint": "玩家趁四下無人，偷偷塞了一筆錢給阿月，想幫她分擔一些。阿月察覺後神情變得防備，像是被同情或被收買一樣很不高興，直接拒絕收下這筆錢。",
                },
                "outcome_above": {
                    "delta": 1,
                    "flag": "offered_help_ayue",
                    "hint": "玩家趁四下無人，偷偷塞了一筆錢給阿月，想幫她分擔一些。阿月這次沒有拒絕，坦然收下了，眼神裡帶著感激。",
                    "grow_prowess": True,  # 成功一次代表懂得看時機、拿捏分寸，算一種歷練
                },
            },
            # 老王第一顆故事珠子（見終極願景.md 擴充方向七）：表面獨立於阿月線，不要求任何阿月相關前提；
            # 敘事是否自然帶到阿月，交給 Call1 依當下場景/記憶自己判斷，不在這裡的 hint 強行安插。
            # 出現在選單前要先鋪墊過（見 mentioned_wang_debt），不然玩家會覺得選項憑空冒出來、很突兀
            {
                "id": "wang_debtor_trouble",
                "text": "老王被討債的人纏上，你決定出面幫他解圍",
                "type": "npc_scripted",
                "target": "npc_wang",
                "requires_flag": "mentioned_wang_debt",
                "success_threshold": WANG_DEBT_THRESHOLD,
                "base_rate_above": WANG_DEBT_BASE_RATE_ABOVE,
                "base_rate_below": WANG_DEBT_BASE_RATE_BELOW,
                "outcome_below": {
                    "delta": -1,
                    "flag": None,
                    "hint": "一個討債人纏上了老王，你試著出面幫忙解圍，但這次沒能把事情擺平，討債人依然不依不饒地留下狠話才離開，老王的臉色顯得有些尷尬又無奈。",
                },
                "outcome_above": {
                    "delta": 3,  # 比日常對話的±1更有份量，這是完成委託該有的回饋
                    "flag": "helped_wang_debt",
                    "hint": "一個討債人纏上了老王，你趁勢出面，幾句話軟硬兼施地把事情擺平，討債人悻悻然地離開了。老王先是愣了一下，隨後鬆了口氣，眼神裡多了幾分感激，難得沒有嘴硬。",
                },
            },
            {"id": "goto_street", "text": "推開木門，走到酒館外的街道上", "type": "scene", "target": "street"},
            {
                "id": "goto_ayue_home",
                "text": "跟著阿月回家看看",
                "type": "scene",
                "target": "ayue_home",
                "requires_flag": "offered_help_ayue",
            },
        ],
    },
    "street": {
        "name": "酒館外的街道",
        "intro": (
            "酒館外的街道靜悄悄的，只有幾盞路燈搖曳著昏黃的光。晚風帶著一點涼意，"
            "遠處隱約傳來幾聲犬吠，老王酒館的木門就在你身後。"
        ),
        "scene_atmosphere": (
            "石板路蜿蜒向兩側延伸，幾盞路燈立在路邊，光線昏黃搖曳。牆邊堆著幾個木箱，"
            "遠處隱約可見幾戶人家透出的燈火，晚風帶著涼意拂過臉頰，偶爾傳來幾聲犬吠。"
        ),
        "npcs": [],
        "options": [
            {"id": "street_back_to_tavern", "text": "推開木門，走回老王酒館裡", "type": "scene", "target": "tavern"},
            {
                "id": "street_look_around",
                "text": "抬頭看看夜空，讓自己靜一靜",
                "type": "flavor",
                "response": "夜空繁星點點，你深吸一口涼爽的空氣，思緒稍微平靜了下來。",
            },
            # 街道第一次從單純的過場升級成樞紐：這是選單裡第一個「通往新場景」的 scene 型選項，見 DEVLOG.md
            {"id": "street_goto_market", "text": "沿著街道走去市集看看", "type": "scene", "target": "market"},
            # 小鎮擴張到中等規模（2026-07-19）：街道再輻射出三條新的出口，比照 street_goto_market 的模式
            {"id": "street_goto_inn", "text": "沿街道走去客棧看看", "type": "scene", "target": "inn"},
            {"id": "street_goto_gate", "text": "往小鎮邊界的城門走去", "type": "scene", "target": "gate"},
            {"id": "street_goto_dojo", "text": "沿另一條巷子走去武館看看", "type": "scene", "target": "dojo"},
        ],
    },
    "inn": {
        "name": "客棧",
        "intro": (
            "推開客棧的木門，大堂裡燈火通明，孫掌櫃正低頭在櫃檯後撥著算盤。"
            "角落幾張桌子旁，幾個像是趕路的旅人正低聲交談，偶爾傳來一兩聲疲憊的笑。"
        ),
        "scene_atmosphere": (
            "客棧大堂擺著幾張方桌，牆上掛著一塊寫著「賓至如歸」的舊匾額，木頭地板被踩得發亮。"
            "櫃檯後方的架子上整齊疊著棉被與燈油，樓梯通往二樓的客房，隱約能聞到剛擦過的桐油味，"
            "偶爾有旅人上下樓梯，行李摩擦地板發出細碎的聲響。"
        ),
        "npcs": ["npc_innkeeper"],
        "options": [
            {"id": "innkeeper_chat", "text": "跟孫掌櫃打聲招呼，問問客棧生意如何", "type": "npc", "target": "npc_innkeeper"},
            {
                "id": "innkeeper_ask_travelers",
                "text": "向孫掌櫃打聽最近有沒有什麼特別的旅人路過",
                "type": "npc",
                "target": "npc_innkeeper",
            },
            {"id": "inn_back_to_street", "text": "走出客棧，回到街道", "type": "scene", "target": "street"},
        ],
    },
    "gate": {
        "name": "鎮口",
        "intro": (
            "走到小鎮的邊界，一座斑駁的城門矗立在眼前。兩名守衛倚著城牆打盹，"
            "門外的官道上，一支商隊正緩緩駛入，車輪碾過石板路發出沉悶的聲響。"
            "城門外是一片看不到盡頭的原野，天色再遠一點，就什麼都看不清了。"
        ),
        # 純氛圍場景（沒有真正的 NPC），刻意留這個伏筆——小鎮以外還有更大的世界，之後如果要往外擴充，這裡是起點
        "scene_atmosphere": (
            "城門又高又厚，磚石縫裡長著雜草，兩側掛著已經褪色的燈籠。守衛的長矛倚在牆邊，"
            "偶爾有商隊、腳夫進出，吆喝著讓路。城門外的官道向遠方延伸，塵土在風裡揚起，"
            "再往外，就是小鎮以外的世界了，隱約能看到遠山的輪廓。"
        ),
        "npcs": [],
        "options": [
            {
                "id": "gate_watch_caravan",
                "text": "站在城門邊，看著商隊進出，猜猜他們從哪裡來",
                "type": "flavor",
                "response": "商隊的騾馬馱著沉甸甸的貨物，車夫滿臉風霜，操著你聽不太懂的口音。你忽然意識到，小鎮外頭，是一個比你想像中更大的世界。",
            },
            {"id": "gate_back_to_street", "text": "轉身離開城門，走回街道", "type": "scene", "target": "street"},
        ],
    },
    "dojo": {
        "name": "武館",
        "intro": (
            "武館的大門半掩著，隱約傳來練武的吆喝聲跟兵器碰撞的悶響，但推門進去，"
            "空蕩蕩的院子裡卻不見半個人影，只有地上散落的幾個沙包還在輕輕晃動。"
        ),
        # 目前先當空場景，沒有真正的 NPC，之後想加真人再說
        "scene_atmosphere": (
            "武館的院子鋪著壓實的黃土，四周立著幾根木樁，樁身佈滿深淺不一的拳痕。"
            "牆邊架子上掛著幾件兵器，看起來許久沒被動過，蒙著一層薄灰。"
            "偶爾一陣風吹過，院子裡的旗幟獵獵作響，吆喝聲時有時無，聽不出從哪個方向傳來。"
        ),
        "npcs": [],
        "options": [
            {
                "id": "dojo_look_around",
                "text": "在空蕩蕩的院子裡走走，看看有沒有人",
                "type": "flavor",
                "response": "你繞了院子一圈，除了風聲和隱約的吆喝，什麼人也沒看到，倒是牆角那排兵器架，讓你多看了兩眼。",
            },
            {"id": "dojo_back_to_street", "text": "退出武館，回到街道", "type": "scene", "target": "street"},
        ],
    },
    "market": {
        "name": "市集",
        "intro": (
            "轉過街道盡頭的巷口，眼前忽然熱鬧起來。這是個小小的夜市，一盞盞燈籠掛在攤子上方，"
            "叫賣聲此起彼落，油鹽醬醋、針線雜貨擺得滿滿當當，空氣裡混著食物香氣與塵土味。"
        ),
        # 每一輪都會塞進 build_system_prompt()，跟其他場景的做法一致，用具體畫面份量撐住場景感
        "scene_atmosphere": (
            "市集裡一個個攤位緊挨著排開，竹編的籃子堆滿乾貨與雜貨，燈籠在夜風裡輕輕搖晃。"
            "地上是碎石與泥土混合的小徑，偶爾有人提著菜籃匆匆走過，遠處傳來討價還價的喧鬧聲，"
            "還有攤販扯著嗓子叫賣的吆喝，混著油鍋滋滋作響的香氣。"
        ),
        "npcs": ["npc_vendor"],
        "options": [
            {"id": "vendor_chat", "text": "走到陳伯的雜貨攤前，看看他在賣什麼", "type": "npc", "target": "npc_vendor"},
            {"id": "vendor_gossip", "text": "跟陳伯打聽市集裡最近有什麼消息", "type": "npc", "target": "npc_vendor"},
            {"id": "market_back_to_street", "text": "離開市集，走回街道", "type": "scene", "target": "street"},
        ],
    },
    "ayue_home": {
        "name": "阿月家",
        "intro": (
            "阿月帶你穿過幾條窄巷，推開一扇有些斑駁的木門。屋裡很小，藥味淡淡地飄著，"
            "阿月的母親躺在靠窗的床上，見你們進來，勉強撐起身子，眼神有些渙散。"
        ),
        # 見 DEVLOG.md：阿月自己「在酒館工作」那幾條核心事實拉力太強，光講場景名稱蓋不過去；
        # 改用純正面、具體的畫面細節（不是排除句），用份量自然壓過去，每一輪都會塞進 build_system_prompt()
        "scene_atmosphere": (
            "這是阿月家，一間窄小簡陋的屋子。牆角堆疊著幾件洗得發白的舊衣，窗邊擺著一張病榻，"
            "母親安靜地躺在上頭。矮桌上放著幾包藥材，空氣裡飄著淡淡的藥味，牆上掛著一幅褪了色的舊畫，"
            "地板是斑駁的木板，踩上去偶爾會發出輕微的嘎吱聲。"
        ),
        "npcs": ["npc_ayue_mother"],
        "options": [
            {
                "id": "visit_ayue_mother",
                "text": "走到床邊，探望阿月的母親，跟她說幾句話",
                "type": "npc",
                "target": "npc_ayue_mother",
            },
            {"id": "ayue_home_chat", "text": "跟阿月在她家裡聊聊", "type": "npc", "target": "npc_ayue"},
            {"id": "ayue_home_leave", "text": "跟阿月道別，走回老王酒館", "type": "scene", "target": "tavern"},
        ],
    },
}


def build_cloud_option_prompt(options: list[dict]) -> str:
    lines = []
    for opt in options:
        if opt["type"] in ("npc", "npc_scripted"):
            npc = NPCS[opt["target"]]
            tier = affinity_tier(state["npcs"][opt["target"]]["affinity"])
            lines.append(f'- [id={opt["id"]}] （對象：{npc["name"]}，目前關係：{tier}）核心意圖："{opt["text"]}"')
        else:
            lines.append(f'- [id={opt["id"]}] （場景行動，不針對特定角色）核心意圖："{opt["text"]}"')
    intents_text = "\n".join(lines)
    scene_name = SCENES[state["location"]]["name"]
    return f"""你在幫一款文字冒險遊戲產生選單文字。這是玩家目前站在「{scene_name}」裡，可以做的幾種固定互動，每種互動背後的核心意圖不會變，你的工作是幫每一種意圖換一種新鮮的說法，讓同一個意圖用不同的話講出來，讀起來像是這個當下、這個關係狀態會自然說出的話。

【固定的互動意圖，依序是】
{intents_text}

輸出格式是一個 JSON 物件，裡面有一個 "options" 陣列，陣列裡每個元素是 {{"id": 上面方括號裡的 id, "text": 對應的新句子}}，每個 id 恰好出現一次，每句話長度跟原句差不多，繁體中文，只包含文字與標點符號。只輸出 JSON，不要有 JSON 以外的文字或說明。"""


CLOUD_TEXT_MAX_LEN = 120


def parse_cloud_options(raw, options: list[dict]) -> list[str] | None:
    """驗證雲端回傳的結構，回傳「依 Python 選項順序排好」的顯示文字；任何異常一律回傳 None（呼叫端 fallback）。
    雲端文字只用來顯示，所以這裡的驗證只負責結構（型別、id 對得上、不重複、非空、長度）；
    文字語意是否貼近原意圖 Python 無法驗證，也不需要驗證——選項的行為由 Python 的選項資料決定，與這些文字無關"""
    if not isinstance(raw, list) or len(raw) != len(options):
        return None
    by_id: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            return None
        if item["id"] in by_id:
            return None
        text = " ".join(strip_residue(item["text"]).split())  # 收斂成單行
        if not text or len(text) > CLOUD_TEXT_MAX_LEN:
            return None
        by_id[item["id"]] = text
    if set(by_id) != {opt["id"] for opt in options}:
        return None
    return [by_id[opt["id"]] for opt in options]


def call_cloud_option_llm(options: list[dict]) -> list[str] | None:
    if not CLOUD_API_KEY:
        print("[未設定 CLOUD_API_KEY，本輪選項文字使用預設，不影響遊戲]")
        return None
    try:
        resp = requests.post(
            f"{CLOUD_API_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {CLOUD_API_KEY}"},
            json={
                "model": CLOUD_MODEL,
                "messages": [
                    {"role": "system", "content": build_cloud_option_prompt(options)},
                    {"role": "user", "content": "請生成這一輪的選單文字。"},
                ],
                "temperature": 0.9,
                "enable_thinking": False,  # 跟本機模型的 think:false 同一個原則：關掉才不會逾時、才好解析
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        texts = parse_cloud_options(parse_llm_json(content).get("options"), options)
        if texts is None:
            print("[選項文字雲端生成結構異常（型別、id 或數量對不上），改用預設選項]")
        return texts
    except Exception as e:
        print(f"[選項文字雲端生成失敗，改用預設選項：{e}]")
        return None


def is_scripted_option_completed(opt: dict) -> bool:
    # npc_scripted 的成功結果會設一個旗標（outcome_above["flag"]），旗標已設代表這件事已經發生過。
    # 這類是一次性、不可逆的劇情轉換：完成後選項不再出現，避免重複拿好感度/prowess。
    # 失敗（outcome_below）不設旗標，所以失敗後選項仍在，可以再試——維持原本的設計
    if opt.get("type") != "npc_scripted":
        return False
    done_flag = opt["outcome_above"].get("flag")
    return bool(done_flag and state["player"]["flags"].get(done_flag))


def get_visible_options(scene_options: list[dict]) -> list[dict]:
    return [
        opt
        for opt in scene_options
        if ("requires_flag" not in opt or state["player"]["flags"].get(opt["requires_flag"]))
        and not is_scripted_option_completed(opt)
    ]


def render_options() -> list[dict]:
    current_options = get_visible_options(SCENES[state["location"]]["options"])
    fresh_texts = call_cloud_option_llm(current_options)
    if fresh_texts:
        # 雲端措辭只放進 display_text（純顯示）；id／type／target／text（意圖）都維持 Python 原值，
        # main() 的行為與送進 Call1／history 的 action 一律讀原值，玩家選的 index 對應的永遠是 Python 的選項
        return [{**opt, "display_text": t} for opt, t in zip(current_options, fresh_texts)]
    return current_options


# ---------- 長期記憶（Qdrant + bge-m3，見 5.5 節；直接打 REST API，不加 qdrant-client 依賴） ----------
MEMORY_ENABLED = True  # 開場連線檢查失敗就關掉，整個 session 不再重試，避免每輪都噴錯誤訊息


def ensure_memory_collection() -> None:
    global MEMORY_ENABLED
    try:
        resp = requests.get(f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}", timeout=10)
        if resp.status_code == 200:
            return
        requests.put(
            f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}",
            json={"vectors": {"size": MEMORY_VECTOR_SIZE, "distance": "Cosine"}},
            timeout=10,
        ).raise_for_status()
    except requests.exceptions.RequestException as e:
        MEMORY_ENABLED = False
        print(f"[連不上 Qdrant，這次遊戲長期記憶功能停用，不影響其他功能：{e}]")


def embed_text(text: str) -> list[float]:
    resp = requests.post(OLLAMA_EMBED_URL, json={"model": EMBEDDING_MODEL, "input": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


MEMORY_TEXT_MAX_LEN = 200


def sanitize_memory_text(text: str) -> str:
    # 記憶文字會被原樣放進未來的 system prompt：收斂成單行、拿掉【】，避免偽造 prompt 區塊標題
    # （例如 Python 才會產生的「【你們之間確實發生過的事】」），並限制長度
    return " ".join(text.replace("【", " ").replace("】", " ").split())[:MEMORY_TEXT_MAX_LEN]


def scripted_memory_note(outcome: dict) -> str:
    # npc_scripted 回合的永久記憶由 Python 依「已確定的結果」建立：直接用該結果自己的 hint
    # （靜態、第三人稱的事實句，成功/失敗各自一句），不採用 Call1 自由撰寫的 memory_note，
    # 這樣 LLM 無法讓記憶描述出與 authoritative outcome 不符的事件
    return sanitize_memory_text(outcome["hint"])


def write_memory(turn_count: int, npc_id: str, text: str) -> None:
    if not MEMORY_ENABLED:
        return
    text = sanitize_memory_text(text)
    if not text:
        print("[這回合沒有可用的記憶摘要，跳過長期記憶寫入]")
        return
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            print(f"[memory_note 格式異常（像是鍵值資料而非敘述句），跳過這次寫入：{text!r}]")
            return
    except (json.JSONDecodeError, ValueError):
        pass  # 正常情況：這本來就該是一句敘述文字，不是合法JSON，解析失敗才是預期行為
    try:
        vector = embed_text(text)
        requests.put(
            f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}/points",
            json={
                "points": [
                    {
                        "id": turn_count,
                        "vector": vector,
                        "payload": {
                            "turn_count": turn_count,
                            "npc_ids": [npc_id],
                            "location": SCENES[state["location"]]["name"],
                            "tags": [],  # 對應 flags_set 內容（5.5節設計），write_memory 目前沒接收 flags_set 參數，先留空
                            "text": text,
                        },
                    }
                ]
            },
            timeout=15,
        ).raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[長期記憶寫入失敗，不影響本回合：{e}]")


def query_memories(query_text: str, npc_id: str | None) -> list[str]:
    if not MEMORY_ENABLED:
        return []
    try:
        vector = embed_text(query_text)
        body = {"vector": vector, "limit": MEMORY_TOP_K, "with_payload": True}
        if npc_id:
            body["filter"] = {"must": [{"key": "npc_ids", "match": {"any": [npc_id]}}]}
        resp = requests.post(f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}/points/search", json=body, timeout=15)
        resp.raise_for_status()
        return [hit["payload"]["text"] for hit in resp.json()["result"]]
    except requests.exceptions.RequestException as e:
        print(f"[長期記憶查詢失敗，本回合先跳過：{e}]")
        return []


def get_recent_narratives(target_npc_id: str, n: int = 2) -> list[str]:
    texts = []
    for msg in reversed(conversation_history[target_npc_id]):
        if msg["role"] == "assistant":
            texts.append(json.loads(msg["content"]).get("narrative", ""))
            if len(texts) >= n:
                break
    return list(reversed(texts))


# ---------- narrative schema（見 5.3 節鐵律：敘事生成只管敘事，不判好感度） ----------
NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {
            "type": "string",
            "description": "根據玩家的動作，用生動的繁體中文寫一小段（80-150字）敘事回應",
        },
        "memory_note": {
            "type": "string",
            "description": "用一句話（20-40字）寫成一段連貫通順的中文敘述句，摘要這回合發生的事實重點，像是在跟朋友轉述剛才發生的事，是給未來回憶用的客觀記錄",
        },
        "flags_set": {
            "type": "array",
            "items": {"type": "string", "enum": LLM_ASSIGNABLE_FLAGS},
            "description": "如果這段敘事裡發生了值得長期記住的關鍵事實，列出對應的標記；大多數回合都不會有任何標記，留空陣列即可",
        },
    },
    "required": ["narrative", "memory_note", "flags_set"],
}

# ---------- affinity schema（拆成獨立第二次呼叫，輸入是 Call 1 生成的 narrative） ----------
AFFINITY_SCHEMA = {
    "type": "object",
    "properties": {
        "affinity_delta": {
            "type": "integer",
            "enum": [-1, 0, 1],
            "description": "根據這段敘事的內容，判斷 NPC 對玩家好感度的變化方向：-1 代表變差、0 代表不變、+1 代表變好，三者為對等選項，依敘事實際呈現的態度挑一個。",
        },
    },
    "required": ["affinity_delta"],
}


def build_system_prompt(
    target_npc_id: str,
    ask_count: int,
    memories: list[str],
    scripted_outcome: str | None = None,
    flavor_hint: str | None = None,
) -> str:
    npc = NPCS[target_npc_id]
    facts_text = "\n".join(f"- {f}" for f in npc["facts"])
    affinity = state["npcs"][target_npc_id]["affinity"]
    current_scene = SCENES[state["location"]]
    scene_name = current_scene["name"]
    scene_atmosphere = current_scene.get("scene_atmosphere", "")
    scene_section = f"\n【眼前的場景：{scene_name}】\n{scene_atmosphere}\n" if scene_atmosphere else f"\n現在的場景：{scene_name}\n"
    repeat_hint = (
        f"玩家這是第 {ask_count} 次做這個動作了，請避免重複之前用過的措辭、比喻或情節細節，換個角度回應。"
        if ask_count > 1
        else "這是玩家第一次做這個動作。"
    )
    memory_section = ""
    if memories:
        memory_text = "\n".join(f"- {sanitize_memory_text(m)}" for m in memories)  # 讀取端也淨化，涵蓋舊版已存進 Qdrant 的資料
        memory_section = (
            "\n【你還記得的一些事】\n"
            f"以下是你零星記得的一些片段，會自然影響你現在的反應，不用刻意提起：\n{memory_text}\n"
        )
    flag_facts = get_flag_facts(target_npc_id)
    flag_section = ""
    if flag_facts:
        flag_text = "\n".join(f"- {f}" for f in flag_facts)
        flag_section = f"\n【你們之間確實發生過的事】\n{flag_text}\n"
    outcome_section = ""
    if scripted_outcome:
        outcome_section = f"\n【這回合已經確定發生的事，敘事要順著這個結果寫】\n{scripted_outcome}\n"
    flavor_section = ""
    if flavor_hint:
        flavor_section = (
            "\n【這回合背景裡多一件小事，找機會輕描淡寫地帶一句就好，不是這回合的重點】\n"
            f"{flavor_hint}\n"
            "提起這件事的時候，語氣是隨口抱怨、帶點無奈打趣，像在講一件已經翻篇的小麻煩事。\n"
        )
    return f"""你是一個文字冒險遊戲的敘事引擎，負責扮演 NPC「{npc['name']}」。

【{npc['name']} 的核心設定，這些是不可違背的事實】
{facts_text}
{scene_section}
【目前狀態】
玩家與{npc['name']}目前的關係：{affinity_tier(affinity)}
{repeat_hint}
{memory_section}{flag_section}{outcome_section}{flavor_section}
【你的任務】
根據玩家剛才做的動作，寫一段符合{npc['name']}性格的敘事回應（繁體中文，80-150字）。
這段文字會直接顯示給玩家閱讀，只包含中文文字與標點符號，像是說書人在講故事。
只輸出 JSON，不要有任何 JSON 以外的文字或說明。"""


def build_affinity_system_prompt(target_npc_id: str) -> str:
    npc = NPCS[target_npc_id]
    return f"""你是一個文字冒險遊戲的好感度判定器，只做一件事：讀一段敘事文字，判斷它呈現出 NPC「{npc['name']}」對玩家的態度變化方向。

【判斷依據】
只根據使用者訊息裡提供的敘事文字本身內容判斷，不要腦補文字以外的劇情。

只輸出 JSON，不要有任何 JSON 以外的文字或說明。"""


def call_narrative_llm(
    player_action: str,
    target_npc_id: str,
    ask_count: int,
    scripted_outcome: str | None = None,
    flavor_hint: str | None = None,
) -> dict:
    # history 的語意是「玩家實際經歷過的回合」：這個函式只讀，不寫；寫入由 commit_turn_history() 在整個回合成功後才做
    history = conversation_history[target_npc_id]
    recent_narratives = get_recent_narratives(target_npc_id, 2)
    query_text = " ".join([player_action, *recent_narratives])
    memories = query_memories(query_text, target_npc_id)
    user_message = {"role": "user", "content": f"玩家的動作：{player_action}"}
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": build_system_prompt(target_npc_id, ask_count, memories, scripted_outcome, flavor_hint),
            },
            *history,
            user_message,
        ],
        "think": False,  # 見 3.1 節：關閉 thinking，否則回應會混入 <think> 區塊
        "format": NARRATIVE_SCHEMA,
        "options": {"num_ctx": 8192},  # 見 3.2 節：不用預設 256K，省 VRAM
        "stream": False,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    parsed = parse_llm_json(content)
    narrative = strip_residue(parsed.get("narrative", ""))
    memory_note = strip_residue(parsed.get("memory_note", ""))
    # 見 9.1 節：白名單防線，schema 外的值一律丟棄，不信任模型自己會守規矩。
    # 這裡刻意過濾 LLM_ASSIGNABLE_FLAGS（比 FLAG_WHITELIST 窄），雙重保險：
    # 即使 Ollama 的 schema enum 約束被繞過，Python 這層還是不會放行 Call1 不該自己決定的旗標（例如 mentioned_wang_debt）
    flags_set = [f for f in parsed.get("flags_set", []) if f in LLM_ASSIGNABLE_FLAGS]
    return {"narrative": narrative, "memory_note": memory_note, "flags_set": flags_set}


def commit_turn_history(target_npc_id: str, player_action: str, narrative_result: dict) -> None:
    history = conversation_history[target_npc_id]
    history.append({"role": "user", "content": f"玩家的動作：{player_action}"})
    # 存清理後的版本，不是原始 content，避免殘渣透過對話歷史被模型參考模仿
    history.append(
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "narrative": narrative_result["narrative"],
                    "memory_note": narrative_result["memory_note"],
                    "flags_set": narrative_result["flags_set"],
                },
                ensure_ascii=False,
            ),
        }
    )


def call_affinity_llm(narrative: str, target_npc_id: str) -> int:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": build_affinity_system_prompt(target_npc_id)},
            {"role": "user", "content": narrative},
        ],
        "think": False,
        "format": AFFINITY_SCHEMA,
        "options": {"num_ctx": 8192, "temperature": 0, "seed": 42},
        "stream": False,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    delta = parse_llm_json(content).get("affinity_delta", 0)
    # 見 9.1 節：白名單防線，schema 外的值一律視為 0，不信任模型自己會守規矩
    return delta if delta in (-1, 0, 1) else 0


def call_llm(player_action: str, target_npc_id: str, ask_count: int, flavor_hint: str | None = None) -> dict:
    narrative_result = call_narrative_llm(player_action, target_npc_id, ask_count, flavor_hint=flavor_hint)
    delta = call_affinity_llm(narrative_result["narrative"], target_npc_id)
    return {
        "narrative": narrative_result["narrative"],
        "memory_note": narrative_result["memory_note"],
        "flags_set": narrative_result["flags_set"],
        "affinity_delta": delta,
    }


def print_typewriter(text: str, delay: float = 0.02) -> None:
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(delay)
    print()


def apply_turn_result(
    target_npc_id: str, option_id: str, ask_count: int, delta: int, memory_note: str, prowess_growth: bool = False
) -> None:
    npc_name = NPCS[target_npc_id]["name"]
    npc_state = state["npcs"][target_npc_id]
    npc_state["option_counts"][option_id] = ask_count
    npc_state["affinity"] = clamp(npc_state["affinity"] + delta, -AFFINITY_BOUND, AFFINITY_BOUND)
    state["turn_count"] += 1

    # 見 5.5 節：只有 flags_set 非空或好感度有變化的回合才寫長期記憶
    if delta != 0:
        write_memory(state["turn_count"], target_npc_id, memory_note)

    if delta == 1:
        print(f"\n（{npc_name}對你的態度似乎變好了一點）")
    elif delta == -1:
        print(f"\n（{npc_name}的臉色似乎沉了下來）")

    # 通用成長掛鉤：任何 npc_scripted 選項的 outcome 都可以帶 prowess_growth=True，不用各自另寫一套成長邏輯。
    # state 只累加 growth_count（整數），精確值每次都用 prowess_at() 重新算，不快取浮點數。
    # 訊息判斷用「四捨五入後顯示的整數有沒有變」而不是「精確值有沒有變」，否則接近上限時每次都有極小增量，
    # 會變成幾乎每輪都跳訊息，破壞「感覺卡住了」這個手感。
    if prowess_growth:
        old_display = round(current_prowess())
        state["player"]["prowess_growth_count"] += 1
        new_display = round(current_prowess())
        if new_display > old_display:
            print("[你的膽識似乎更加沉穩了]")

    print(f"[{npc_name}好感度：{npc_state['affinity']} ｜ 回合數：{state['turn_count']}]")


def main() -> None:
    print("=" * 50)
    print(" 文字 RPG — MVP 雛型")
    print("=" * 50)
    ensure_memory_collection()
    print_typewriter(SCENES[state["location"]]["intro"])

    display_options = render_options()  # 每回合渲染一次；雲端失敗會回傳當前場景的預設選項，此後選項清單維持到下一回合才換

    while True:
        print("\n你可以：")
        for i, opt in enumerate(display_options, 1):
            print(f"  {i}. {opt.get('display_text', opt['text'])}")
        print("  0. 離開遊戲（結束）")

        choice = input("\n> 你的選擇（輸入數字）：").strip()

        if choice == "0":
            print("\n你決定今晚就到這裡，事情先告一段落。")
            break

        if not choice.isdigit() or not (1 <= int(choice) <= len(display_options)):
            print("（這個選項不存在，請重新輸入）")
            continue

        option = display_options[int(choice) - 1]
        print()

        if option["type"] == "scene":
            state["location"] = option["target"]
            state["turn_count"] += 1
            print_typewriter(SCENES[state["location"]]["intro"])
            display_options = render_options()
            continue

        if option["type"] == "flavor":
            print_typewriter(option.get("response", ""))
            state["turn_count"] += 1
            display_options = render_options()
            continue

        if option["type"] == "npc_scripted":
            # 效果（delta/flag）由規則依當下好感度先決定，不呼叫 Call2；只有敘事怎麼講交給 Call1
            action = option["text"]
            option_id = option["id"]
            target_npc_id = option["target"]
            npc_name = NPCS[target_npc_id]["name"]
            npc_state = state["npcs"][target_npc_id]
            ask_count = npc_state["option_counts"].get(option_id, 0) + 1
            base_rate = (
                option["base_rate_above"]
                if npc_state["affinity"] > option["success_threshold"]
                else option["base_rate_below"]
            )
            prowess_bonus = (current_prowess() - PROWESS_BASE) * PROWESS_BONUS_PER_POINT
            success = resolve_scripted_outcome(base_rate, prowess_bonus)
            outcome = option["outcome_above"] if success else option["outcome_below"]

            # outcome 已經由 Python 決定（骰已擲出），從這裡開始 authoritative：Call1 只負責把它講成故事，
            # 它失敗（連不上、逾時、解析失敗、回傳空敘事）都不能讓這個 outcome 消失，否則玩家可以重選、重擲。
            # 備援敘事直接用 outcome 自己的 hint（Python 寫的第三人稱事實句）
            try:
                narrative_result = call_narrative_llm(
                    action, target_npc_id, ask_count, scripted_outcome=outcome["hint"]
                )
                narrative = narrative_result["narrative"]
                if not narrative.strip():
                    raise ValueError("Call1 回傳空敘事")
            except Exception as e:
                print(f"[敘事生成失敗，改用規則備援敘事，結果照常套用：{e}]")
                narrative = outcome["hint"]

            print_typewriter(narrative)
            # 玩家已看到這段敘事，才算進 history；memory_note 一律用 Python 建立的版本，LLM 的自由文字不進 history/Qdrant
            memory_note = scripted_memory_note(outcome)
            commit_turn_history(
                target_npc_id, action, {"narrative": narrative, "memory_note": memory_note, "flags_set": []}
            )

            if outcome["flag"]:
                apply_flags([outcome["flag"]])
            apply_turn_result(
                target_npc_id,
                option_id,
                ask_count,
                outcome["delta"],
                memory_note,
                prowess_growth=outcome.get("grow_prowess", False),
            )

            display_options = render_options()
            continue

        # option["type"] == "npc"：走既有的完整 Call1/Call2 pipeline，不動
        action = option["text"]
        option_id = option["id"]
        target_npc_id = option["target"]
        npc_name = NPCS[target_npc_id]["name"]
        npc_state = state["npcs"][target_npc_id]
        ask_count = npc_state["option_counts"].get(option_id, 0) + 1

        # 老王日常互動的鋪墊擲骰：Python 先決定「這回合要不要嘗試帶到討債人這件事」，成不成功交給 Call1/Call2 照常判斷，
        # flag 是否真的觸發要等拿到 delta 後再確認（見下方「判定成功時才觸發」）。已經鋪墊過或珠子已完成就不用再擲
        flags = state["player"]["flags"]
        debt_mention_attempted = (
            target_npc_id == "npc_wang"
            and not flags.get("mentioned_wang_debt")
            and not flags.get("helped_wang_debt")
            and random.randint(1, 100) <= WANG_DEBT_MENTION_CHANCE
        )
        flavor_hint = WANG_DEBT_MENTION_HINT if debt_mention_attempted else None

        try:
            result = call_llm(action, target_npc_id, ask_count, flavor_hint=flavor_hint)
        except requests.exceptions.ConnectionError:
            print("[連不上 Ollama，確認 `ollama serve` 有在跑，或模型已經 pull 好]")
            continue
        except Exception as e:
            print(f"[生成失敗，稍後再試：{e}]")
            continue

        print_typewriter(result.get("narrative", f"（{npc_name}沉默不語。）"))
        commit_turn_history(target_npc_id, action, result)  # Call1+Call2 都成功、玩家也看到了，才算進 history

        # 見 9.1 節：白名單防線，schema 外的值一律視為 0，不信任模型自己會守規矩
        delta = result.get("affinity_delta", 0)
        if delta not in (-1, 0, 1):
            delta = 0

        flags_to_apply = list(result.get("flags_set", []))
        if debt_mention_attempted and delta == 1:  # 判定成功時才真的觸發鋪墊 flag，不是只要嘗試過就算數
            flags_to_apply.append("mentioned_wang_debt")
        apply_flags(flags_to_apply)
        apply_turn_result(target_npc_id, option_id, ask_count, delta, result.get("memory_note", ""))

        display_options = render_options()  # 下一回合的選項，成功就換新文字，失敗就沿用當前場景的預設選項


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n（遊戲中斷）")
        sys.exit(0)
