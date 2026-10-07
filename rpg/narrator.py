"""說書人：把已經確定的結果講得更生動。可選，沒有 LLM 時遊戲照常可玩。

邊界（吸收 docs/reviews/ 的教訓）：
- LLM 只拿到「這一回合已經發生、玩家看得到」的片段（beats），沒有任何隱藏狀態。
- LLM 的輸出只用來顯示，永遠不會寫回 world、不會變成事實、不會進記憶。
- 輸出先過白盒驗證：數字不能憑空出現、片段裡的人名一個都不能少、不能冒出片段裡沒有的鎮民、
  長度要合理、控制字元一律清掉。任何一項不過就用模板原文。
- 失敗（連不上、逾時、亂碼）只會讓這一段改用模板，不影響任何遊戲結果。
- 台詞（「」裡的話）是規則選出來的，說書人一字不改照抄；只有台詞、沒有動作或場景的回合不送給說書人。
- 不給 NPC 的人物設定：那是給設計者看的內心描寫，說書人會把它講出來（等於劇透），也會讓每回合都重新介紹一次人物。
- 場景只給地名與時辰天氣；完整的地點描寫只在「剛走進來」那一回合的片段裡出現一次。
- 驗證也守住情境：時辰與天氣不能被改掉、只在話裡提到的人不能被寫成在場、不能多出同行者、
  不能把剛才已經介紹過的地方再介紹一遍、不能多出原文沒有的事件、要用繁體中文。
  這些都是「拒絕、退回模板」，不做任何自動修正（CLAUDE.md：黑名單式事後糾錯打不贏）。
  `tests_llm/` 用真的模型逐條驗證這份契約，並統計退回率。
- 依 CLAUDE.md 的實測結論：qwen3.5 一律 think:false + num_ctx:8192；提示用描述句，不用「不要…」這種否定命令。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from .content.locations import LOCATIONS, PERIODS
from .content.npcs import NPCS

REWRITE_KINDS = {"action", "speech", "witness", "arrive", "overheard", "approach", "player_say"}
DIALOGUE_KINDS = {"speech", "player_say"}
_QUOTE = re.compile(r"「([^「」]+)」")
_PUNCT = re.compile(r"[\s，。！？、；：…—「」『』,.!?;:]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏ -‮]")
_DIGITS = re.compile(r"\d+")


def parse_json_object(content: str) -> dict:
    start = content.index("{")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(content[start:i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("not an object")
                return obj
    raise ValueError("no complete JSON object")


def narrative_of(obj: dict):
    """取出 narrative。實測 qwen3.5:9b 偶爾會把欄位名寫歪（例如 "nationale"），即使請求帶了 format schema；
    物件裡只有一個欄位、而且是字串時，照樣當作敘事——結構上仍然只有一段文字，填不進數字或旗標。"""
    if "narrative" in obj:
        return obj["narrative"]
    if len(obj) == 1:
        (v,) = obj.values()
        if isinstance(v, str):
            return v
    return None


def all_names() -> dict[str, str]:
    """所有核心鎮民的稱呼／別名 → id（用來偵測 LLM 憑空拉人進場）。"""
    out = {}
    for nid, spec in NPCS.items():
        for a in [spec["call"], spec["name"], *spec.get("aliases", [])]:
            if len(a) >= 2:
                out[a] = nid
    return out


NAME_INDEX = all_names()


# ---------------- 情境契約用的詞表（精確比對、只用來拒絕） ----------------
# 每個時辰允許出現的時間詞群組；不在允許群組、又不是原文就有的時間詞 → 說書人改了時辰。
TIME_WORDS = {
    "dawn": ["清晨", "晨光", "早晨", "拂曉", "黎明", "晨曦", "朝陽", "晨霧", "天剛亮", "天濛濛亮"],
    "morning": ["上午", "早上"],
    "noon": ["正午", "中午", "晌午", "日正當中", "烈日當空", "日頭正毒"],
    "afternoon": ["午後", "下午", "日頭偏西"],
    "dusk": ["傍晚", "黃昏", "夕陽", "暮色", "落日", "晚霞", "日落"],
    "night": ["入夜", "夜色", "月光", "月色", "深夜", "夜深", "星光", "午夜", "三更", "夜幕", "星空", "月亮"],
    "daylight": ["陽光", "日光", "日頭", "太陽", "烈日", "艷陽"],
}
TIME_ALLOWED = {
    0: {"dawn", "morning", "daylight"}, 1: {"dawn", "morning", "daylight"}, 2: {"noon", "afternoon", "daylight"},
    3: {"afternoon", "dusk", "daylight"}, 4: {"dusk", "night"}, 5: {"night"},
}
_RAIN = ["下雨", "雨絲", "細雨", "雨聲", "雨點", "雨幕", "大雨", "小雨", "撐傘", "雨水", "陰雨"]
_SUN = ["陽光普照", "艷陽", "晴空", "萬里無雲", "陽光燦爛", "晴朗", "烈日"]
WEATHER_CONTRADICTS = {"晴": _RAIN, "雨": _SUN, "陰": _SUN + ["下雨", "雨絲", "細雨", "大雨", "撐傘"]}
COMPANION_WORDS = ["你們幾", "你們一行", "你們兩", "你們三", "同伴", "同行的", "一行人", "你們一夥"]
PRESENCE_WORDS = ["走到", "走過來", "走了過來", "走進", "走來", "站在", "坐在", "來到", "湊過來", "湊近", "朝你", "向你",
                  "對你", "拍了拍", "遞給", "看著你", "看了你", "點了點頭", "開口", "說道", "插嘴", "在一旁", "身旁", "身邊", "迎上"]
ARRIVAL_WORDS = ["映入眼簾", "第一次來到", "初來乍到"]   # 再加上「來到／走進／踏進＋這個地方的名字」，見 check()
PLACE_NAMES = sorted({p["name"] for p in LOCATIONS.values()}, key=len, reverse=True)
# 名字剛好也是普通名詞的鎮民：前面接量詞時是東西，不是人（「每一塊石頭」）
COMMON_WORD_NAMES = {"石頭": "塊顆粒堆些"}
EVENT_WORDS = ["過世", "死了", "斷氣", "被抓", "抓進", "偷走", "偷了", "打傷", "揍了", "起火", "走水", "失火", "拔刀",
               "殺", "鮮血", "流血", "昏倒", "搶走", "搶了", "報官"]
# 簡體專用字（繁體文章裡不會出現的寫法）。只收沒有歧義的字。
SIMPLIFIED = set("这说时来为们会对过还没发现开关问应见长门马鸟车东头话让认谁读请边远进运难国实样种动点从两无与气号爷杂"
                 "钱银铁饭卖买鸡听声灯烟闻阳阴广场观欢华归乡亲爱脸热烧转轻递缓惊叹继续张刘赵孙吴陈苏冯闲间别么视线经"
                 "给红绿结终纸细织网风飞页题顾预领颜额闪阵际随队阶陆险汉沟泪浓涌满测济药医伤价仅侧摊柜馆师岁")
_SENT = re.compile(r"[^。！？\n]+")


def without_places(text: str) -> str:
    """地名裡可能有人名（老王酒館），比對人名之前先拿掉。"""
    for p in PLACE_NAMES:
        text = text.replace(p, "□")
    return text


def mentions(text: str, alias: str) -> bool:
    i = text.find(alias)
    while i >= 0:
        if not (alias in COMMON_WORD_NAMES and i > 0 and text[i - 1] in COMMON_WORD_NAMES[alias]):
            return True
        i = text.find(alias, i + 1)
    return False


def quotes_kept(template: str, text: str) -> bool:
    """原文的每一句「」都要原封不動出現在輸出裡（標點、空白不計）。
    說書人可以在一句話中間插一個動作，把它拆成連續的兩三段「」——字一樣、順序一樣就算保留。"""
    out = [_PUNCT.sub("", q) for q in _QUOTE.findall(text)]
    for q in (_PUNCT.sub("", x) for x in _QUOTE.findall(template)):
        if not any("".join(out[i:j]) == q for i in range(len(out)) for j in range(i + 1, min(len(out), i + 4) + 1)):
            return False
    return True


def narration_only(text: str) -> str:
    """去掉「」裡的台詞，只留說書人自己的敘述。"""
    out, depth = [], 0
    for ch in text:
        if ch == "「":
            depth += 1
        elif ch == "」":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def ngrams(s: str, n: int = 4) -> set[str]:
    s = _PUNCT.sub("", s)
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def scene_overlap(text: str, place: str) -> float:
    """輸出跟這個地點的完整描寫有多少重疊（0～1）。"""
    if place not in LOCATIONS:
        return 0.0
    desc = ngrams(LOCATIONS[place]["day"]) | ngrams(LOCATIONS[place]["night"])
    return len(desc & ngrams(text)) / max(1, len(desc))


def check(output, ctx: dict) -> tuple[str | None, str | None]:
    """驗證一段說書人輸出。回傳（清理後文字, None）或（None, 拒絕原因）。
    ctx 至少要有 template、names；有情境欄位（period、weather、place、arrived、absent）時一併檢查。"""
    if not isinstance(output, str):
        return None, "not_text"
    template = ctx["template"]
    text = _CTRL.sub("", output.replace("\r", "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text or "{" in text or "}" in text or "【" in text:
        return None, "format"
    tlen = len(template)
    if len(text) < max(15, int(tlen * 0.5)):
        return None, "too_short"
    if len(text) > tlen * 2 + 80:
        return None, "too_long"
    # 台詞一字不改（多加字、少字、換字都不行；可以拆成連續幾段）
    if not quotes_kept(template, text):
        return None, "dialogue"
    allowed_digits = set(_DIGITS.findall(template))
    if any(d not in allowed_digits for d in _DIGITS.findall(text)):
        return None, "digits"
    for name in ctx["names"]:
        if name not in text:
            return None, "missing_name"
    present_ids = {NAME_INDEX[n] for n in ctx["names"] if n in NAME_INDEX}
    people_text = without_places(text)
    for alias, nid in NAME_INDEX.items():
        if mentions(people_text, alias) and nid not in present_ids and alias not in template:
            return None, "extra_name"
    if any(x in people_text for x in ctx.get("others", [])):   # 中途進鎮的新面孔
        return None, "extra_name"
    if any(ch in SIMPLIFIED for ch in text):
        return None, "simplified"
    said = narration_only(text)
    new = lambda words: [x for x in words if x in said and x not in template]  # noqa: E731
    if "period" in ctx:
        bad = [g for g, ws in TIME_WORDS.items() if g not in TIME_ALLOWED[ctx["period"]] and new(ws)]
        if bad:
            return None, "time"
    if new(WEATHER_CONTRADICTS.get(ctx.get("weather"), [])):
        return None, "weather"
    if new(COMPANION_WORDS):
        return None, "companions"
    for name in ctx.get("absent", []):
        for sent in _SENT.findall(said):
            if name in sent and any(p in sent for p in PRESENCE_WORDS):
                return None, "absent_on_stage"
    if "place" in ctx and not ctx.get("arrived"):
        here = LOCATIONS[ctx["place"]]["name"]
        again = ARRIVAL_WORDS + [v + here for v in ("來到", "走進", "踏進", "踏入", "走到")]
        if new(again) or scene_overlap(said, ctx["place"]) > 0.2:
            return None, "scene_reintro"
    if new(EVENT_WORDS):
        return None, "invented_event"
    return text, None


def validate(output: str, template: str, required_names: list[str]) -> str | None:
    """只做基本檢查的舊介面（不帶情境）。通過回傳清理後文字，不通過回傳 None。"""
    return check(output, {"template": template, "names": required_names})[0]


class Narrator:
    def __init__(self, mode: str | None = None, url: str | None = None, model: str | None = None, timeout: float = 60):
        self.mode = (mode or os.environ.get("RPG_LLM", "auto")).lower()
        self.url = (url or os.environ.get("RPG_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("RPG_MODEL", "qwen3.5:9b")
        self.timeout = timeout
        self.enabled = False
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.stats = {"ok": 0, "fallback": 0, "error": 0, "reasons": {}}
        if self.mode in ("auto", "ollama"):
            self.enabled = self.probe()

    # ---------- 連線 ----------
    def probe(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=1.5) as r:
                tags = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in tags.get("models", [])]
            return any(n == self.model or n.startswith(self.model.split(":")[0]) for n in names)
        except Exception:
            return False

    def call(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "think": False,
            "format": {"type": "object", "properties": {"narrative": {"type": "string"}}, "required": ["narrative"]},
            "options": {"num_ctx": 8192, "temperature": 0.8},
            "stream": False,
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        obj = parse_json_object(data["message"]["content"])
        if "narrative" not in obj and narrative_of(obj) is not None:
            with self.lock:
                self.stats["schema_key_fixed"] = self.stats.get("schema_key_fixed", 0) + 1
        return narrative_of(obj)

    # ---------- 組 prompt ----------
    @staticmethod
    def build_context(w, beats: list[dict]) -> dict | None:
        rew = [b for b in beats if b["kind"] in REWRITE_KINDS]
        if not rew or all(b["kind"] in DIALOGUE_KINDS for b in rew):
            return None   # 純對話：台詞已經是定稿，照原樣顯示
        template = "\n".join(b["text"] for b in rew)
        names = [n["call"] for n in w.npcs.values() if n["call"] in template]
        loc = w.player["location"]
        here = {w.npcs[i]["call"] for i in w.present_npcs(loc)} | {b.get("speaker") and w.npcs[b["speaker"]]["call"]
                                                                 for b in rew if b.get("speaker") in w.npcs}
        on_stage = [x for x in names if x in here]
        mentioned = [x for x in names if x not in here]
        place = LOCATIONS[loc]
        return {
            "template": template,
            "names": names,
            "period": w.period,
            "weather": w.weather,
            "place": loc,
            "arrived": place["day"] in template or place["night"] in template,
            "on_stage": on_stage,
            "absent": mentioned,
            "others": [n["call"] for i, n in w.npcs.items() if i not in NPCS and n["call"] not in template],
            "scene": f"{LOCATIONS[loc]['name']}，{PERIODS[w.period]}，{w.weather}",
            "cast": "你" + ("、" + "、".join(on_stage) if on_stage else ""),
            "mentioned": "、".join(mentioned),
            "length": int(len(template) * 1.3) + 20,
        }

    @staticmethod
    def prompts(ctx: dict) -> tuple[str, str]:
        system = (
            "你是一位說書人，替一款發生在江南小鎮「青石鎮」的文字冒險遊戲，把剛剛發生的事講給玩家聽。"
            "玩家在故事裡以「你」稱呼。下面的「本段已發生的事」全都已經確定，你的工作是把它們串成一段流暢、有畫面的敘事："
            "引號「」裡的台詞逐字照抄，事件的結果、出場的人、提到的數目都照原樣保留，"
            "你補上的只有動作、神情和此刻的氣氛。"
            "這一段緊接在上一段之後，玩家已經熟悉這裡的場景和人物，敘事就從剛發生的事寫起。"
            "篇幅貼近指定的字數。全文使用繁體中文，只包含文字與標點符號。輸出一個 JSON 物件，欄位 narrative 放這段敘事。"
        )
        user = f"【場景】{ctx['scene']}\n【這一段在場的人】{ctx['cast']}\n"
        if ctx.get("mentioned"):
            user += f"【只在話裡提到、此刻不在場的人】{ctx['mentioned']}\n"
        user += f"【篇幅】約{ctx['length']}字\n【本段已發生的事】\n{ctx['template']}"
        return system, user

    # ---------- 非同步工作 ----------
    def submit(self, w, beats: list[dict]) -> str | None:
        if not self.enabled:
            return None
        ctx = self.build_context(w, beats)
        if not ctx:
            return None
        jid = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[jid] = {"status": "pending", "text": ctx["template"]}
            if len(self.jobs) > 200:
                for k in list(self.jobs)[:100]:
                    self.jobs.pop(k, None)
        self.pool.submit(self._run, jid, ctx)
        return jid

    def narrate_ctx(self, ctx: dict) -> dict:
        """同步跑一次說書：呼叫模型、驗證、決定顯示什麼。遊戲（背景執行緒）與真模型測試走同一條路。"""
        rec = {"source": "template", "text": ctx["template"], "raw": None, "reason": None, "error": None}
        started = time.monotonic()
        try:
            system, user = self.prompts(ctx)
            raw = self.call(system, user)
            rec["raw"] = raw
            text, reason = check(raw, ctx)
            if text:
                rec.update(source="llm", text=text)
            else:
                rec["reason"] = reason
        except Exception as e:  # 連不上、逾時、亂碼：一律退回模板
            rec.update(reason="error", error=f"{type(e).__name__}: {e}"[:200])
        rec["latency"] = round(time.monotonic() - started, 2)
        with self.lock:
            key = "ok" if rec["source"] == "llm" else "error" if rec["reason"] == "error" else "fallback"
            self.stats[key] += 1
            if rec["reason"]:
                self.stats["reasons"][rec["reason"]] = self.stats["reasons"].get(rec["reason"], 0) + 1
        return rec

    def narrate(self, w, beats: list[dict]) -> dict | None:
        """同步版：這一回合不需要說書人時回傳 None。"""
        ctx = self.build_context(w, beats)
        if not ctx:
            return None
        return {**self.narrate_ctx(ctx), "ctx": ctx}

    def _run(self, jid: str, ctx: dict):
        rec = self.narrate_ctx(ctx)
        with self.lock:
            self.jobs[jid] = {"status": "done", "text": rec["text"], "source": rec["source"]}

    def get(self, jid: str) -> dict:
        with self.lock:
            return dict(self.jobs.get(jid) or {"status": "unknown"})
