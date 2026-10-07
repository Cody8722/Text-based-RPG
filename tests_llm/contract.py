"""說書人契約的獨立檢查器（測試用）。

刻意跟 `rpg/narrator.check` 分開寫：production 驗證器決定「要不要給玩家看」，這裡判斷「給玩家看的東西有沒有越界」。
兩者如果一樣，測試就只是在測自己。這裡的詞表是**高精確度**的（只收明確矛盾的詞），所以：

- 對「模型原始輸出」跑一次 → 統計模型多常越界（不代表錯，validator 會擋）。
- 對「最後顯示給玩家的文字」跑一次 → 必須是零。只要有一條漏過去，就是 validator 的缺口，測試失敗。

所有檢查都只拿「這一回合給說書人的情境（ctx）」和世界狀態來比，不要求任何特定句子。
"""

from __future__ import annotations

import re

from rpg.content import text as T
from rpg.content.locations import LOCATIONS

QUOTE = re.compile(r"「([^「」]+)」")
PUNCT = re.compile(r"[\s，。！？、；：…—「」『』,.!?;:~～·]")
SENTENCE = re.compile(r"[^。！？\n]+")

DAY_ONLY = ["陽光", "烈日", "艷陽", "正午", "晌午", "朝陽", "晨光", "日正當中"]
NIGHT_ONLY = ["月光", "月色", "星光", "夜色", "深夜", "午夜", "三更", "夜幕", "星空"]
TIME_CLASH = {
    0: NIGHT_ONLY + ["正午", "晌午", "午後", "下午", "夕陽", "黃昏", "傍晚", "暮色", "落日"],
    1: NIGHT_ONLY + ["正午", "晌午", "午後", "下午", "夕陽", "黃昏", "傍晚", "暮色", "落日"],
    2: NIGHT_ONLY + ["清晨", "晨光", "黎明", "拂曉", "黃昏", "暮色", "落日"],
    3: NIGHT_ONLY + ["清晨", "晨光", "黎明", "拂曉", "正午", "晌午"],
    4: DAY_ONLY + ["清晨", "黎明", "拂曉"],
    5: DAY_ONLY + ["清晨", "黎明", "拂曉", "黃昏", "傍晚", "夕陽"],
}
WEATHER_CLASH = {
    "晴": ["下雨", "細雨", "雨絲", "大雨", "雨點", "撐傘", "雨幕"],
    "雨": ["陽光普照", "萬里無雲", "艷陽", "烈日", "晴空"],
    "陰": ["陽光普照", "萬里無雲", "艷陽", "烈日", "晴空"],
}
COMPANIONS = ["你們幾", "你們一行", "一行人", "同伴", "同行的"]
PRESENCE = ["走到", "走過來", "走了過來", "走進", "湊過來", "站在", "坐在", "迎上", "拍了拍", "遞給"]
EVENTS = ["過世", "斷氣", "被抓", "抓進", "偷走", "打傷", "起火", "失火", "拔刀", "鮮血", "昏倒", "搶走"]
SIMPLIFIED = set("这说们时来为会对过还没发现开关问应见门马车东头话让谁请边进国实样种动点从两无与气钱铁卖买听声灯阳阴场欢间别给红纸风飞题闪队险满济药医伤价吴孙陈刘赵张苏冯镇闻爷")
PLACES = sorted({p["name"] for p in LOCATIONS.values()}, key=len, reverse=True)

CATEGORIES = ["format", "length", "dialogue", "digits", "cast_missing", "cast_extra", "absent_on_stage", "companions", "time", "weather",
              "scene_reintro", "invented_event", "persona_leak", "secret_leak", "simplified"]


def _named(text: str, name: str) -> bool:
    """「每一塊石頭」裡的石頭是東西，不是人。"""
    for i in range(len(text)):
        if text.startswith(name, i) and not (name == "石頭" and i and text[i - 1] in "塊顆粒堆些"):
            return True
    return False


def flat(s: str) -> str:
    return PUNCT.sub("", s)


def narration(text: str) -> str:
    """說書人自己的敘述（去掉「」裡的台詞）。"""
    out, depth = [], 0
    for ch in text:
        if ch == "「":
            depth += 1
        elif ch == "」":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def grams(s: str, n: int) -> set[str]:
    s = flat(s)
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def scene_overlap(text: str, place: str) -> float:
    desc = grams(LOCATIONS[place]["day"], 4) | grams(LOCATIONS[place]["night"], 4)
    return len(desc & grams(text, 4)) / max(1, len(desc))


def audit(text, ctx: dict, w) -> list[str]:
    """回傳 text 違反了哪些契約類別（空 list = 沒有越界）。text 是 None 代表模型根本沒給出文字。"""
    if not isinstance(text, str) or not text.strip():
        return ["format"]
    tpl = ctx["template"]
    said = narration(text)
    fresh = lambda words: [x for x in words if x in said and x not in tpl]  # noqa: E731
    out = []
    if "{" in text or "【" in text:
        out.append("format")
    if len(text) > len(tpl) * 2 + 80:
        out.append("length")
    said_q = [flat(q) for q in QUOTE.findall(text)]
    for q in (flat(x) for x in QUOTE.findall(tpl)):
        # 字一樣、順序一樣；說書人在一句話中間插個動作、拆成連續幾段也算保留
        if not any("".join(said_q[i:j]) == q for i in range(len(said_q)) for j in range(i + 1, len(said_q) + 1)):
            out.append("dialogue")
            break
    if set(re.findall(r"\d+", text)) - set(re.findall(r"\d+", tpl)):
        out.append("digits")
    people = text
    for p in PLACES:                      # 「老王酒館」是地名，不是老王本人
        people = people.replace(p, "□")
    if any(n["call"] in tpl and n["call"] not in text for n in w.npcs.values()):
        out.append("cast_missing")       # 片段裡的人在敘事裡不見了（玩家會搞不清楚是誰說的話）
    if any(_named(people, n["call"]) and n["call"] not in tpl for n in w.npcs.values()):
        out.append("cast_extra")
    for name in ctx.get("absent", []):
        # 名字後面緊跟（最多隔兩個字的副詞）在場的動作
        if re.search(re.escape(name) + r"[也便正就又還已緩慢悠]{0,2}(" + "|".join(PRESENCE) + ")", said):
            out.append("absent_on_stage")
            break
    if fresh(COMPANIONS):
        out.append("companions")
    if fresh(TIME_CLASH[ctx["period"]]):
        out.append("time")
    if fresh(WEATHER_CLASH.get(ctx["weather"], [])):
        out.append("weather")
    if not ctx["arrived"] and ("你來到" in said and "你來到" not in tpl or scene_overlap(said, ctx["place"]) > 0.3):
        out.append("scene_reintro")
    if fresh(EVENTS):
        out.append("invented_event")
    tpl6 = grams(tpl, 6)
    said6 = grams(said, 6)
    for n in w.npcs.values():
        if n.get("persona") and (grams(n["persona"], 6) - tpl6) & said6:
            out.append("persona_leak")
            break
    for f in w.facts.values():
        if f["secrecy"] == "secret" and f["id"] not in w.player["knows"]:
            if len((grams(T.fact_text(w, f), 6) - tpl6) & said6) >= 2:
                out.append("secret_leak")
                break
    if any(ch in SIMPLIFIED for ch in text):
        out.append("simplified")
    return out
