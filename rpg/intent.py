"""自由行動的理解：玩家的一句話 → 結構化的意圖（不是結果）。

意圖只有幾個封閉欄位：
  verb      做什麼（examine/apply/tap/treat/strike/talk/give/take/move/wait/note/other）
  target    對誰／對什麼——只能是伺服器列出的候選（玩家「以為」在這裡的人與東西，用玩家自己的叫法）
  modality  用什麼方式作用（震動、熱、割……）
  means     用自己的哪一項能力或哪件東西
  purpose   想達成什麼（help/harm/learn/None）
  hypothesis 玩家自己的推測（只記進玩家的腦中，不會變成世界真實）
裡面沒有任何「結果」欄位——結果只由世界模擬器（act.py）決定。

理解的方式：
- 詞表解析（parse_rules）：不需要 LLM。只認得意圖的形狀，認不出時回傳候選選項讓玩家點選，而不是猜。
- LLM 解析（parse_llm，可選）：讓 LLM 從候選清單裡挑；輸出過白名單驗證（多出來的欄位、包括任何「結果」一律丟掉，
  target／means 必須是清單裡的 id）。驗證不過就退回詞表解析。這是 CLAUDE.md「模糊比對排除」原則的延伸：
  LLM 只能在伺服器給的精確選項之間選，不能發明對象。
"""

from __future__ import annotations

import json

from . import mind
from .content.nature import MODALITY_CUES, SAME_THING

VERBS = ["examine", "apply", "tap", "treat", "strike", "talk", "give", "take", "move", "wait", "note", "other"]
PURPOSES = ["help", "harm", "learn"]
MODALITIES = ["vibration", "heat", "cold", "cut", "chemical", "qi", "blunt", "care", "craft"]

VERB_WORDS = [
    ("apply", ["震碎", "打碎", "擊碎", "弄碎", "碎掉", "敲碎", "壓碎", "燒掉", "燒", "烤", "凍住", "凍", "割開", "割掉", "切開",
               "切掉", "刺穿", "劈開", "震"]),
    ("treat", ["治療", "醫治", "救治", "治好", "治一治", "診治", "包紮", "上藥", "施針", "針灸", "止血", "推拿", "治", "救"]),
    ("tap", ["敲敲", "敲一敲", "叩", "彈一彈", "敲"]),
    ("examine", ["檢查", "看看", "查看", "觀察", "診察", "診斷", "把脈", "摸摸", "摸一摸", "摸", "端詳", "研究", "打量",
                 "看一下", "瞧瞧", "聽聽", "看"]),
    ("strike", ["揍", "攻擊", "踢", "殺", "砍", "打"]),
    ("give", ["給", "送給", "遞給"]),
    ("take", ["拿走", "偷", "搶", "拿"]),
    ("talk", ["問問", "問", "告訴", "說", "聊"]),
    ("wait", ["休息", "等一會", "等", "坐一會"]),
    ("move", ["走到", "前往", "回到", "去"]),
]
NOTE_WORDS = ["懷疑", "猜", "覺得", "認為", "推測", "大概是", "應該是", "可能是", "看來是"]
HELP_WORDS = ["救", "治", "幫", "病因", "緩解", "減輕", "好起來"]
HARM_WORDS = ["殺", "傷", "打死", "弄死", "教訓", "報仇"]
PERSON_PRONOUNS = ["這個人", "那個人", "對方", "病人", "他", "她"]
THING_PRONOUNS = ["那個東西", "這個東西", "那東西", "這東西", "那顆", "這顆", "那塊", "這塊", "它", "異物", "硬塊", "團塊"]
INSIDE_WORDS = ["體內", "身體裡", "肚子", "肚裡", "腹中", "裡面", "身上"]


# ---------------------------------------------------------------- 候選：玩家「以為」在這裡的人與東西
def candidates(w) -> dict:
    p = w.player
    loc = p["location"]
    targets = [{"id": "self", "kind": "self", "label": "你自己", "words": ["我自己", "自己"]}]
    present = list(w.present_npcs(loc))
    if loc == "yamen":
        present += [i for i, n in w.npcs.items() if n["status"] == "jailed" and i not in present]
    for nid in present:
        n = w.npcs[nid]
        met = nid in p["met"]
        words = ([*n["aliases"], n["call"]] if met else []) + seen_words(n)
        targets.append({"id": f"p:{nid}", "kind": "person", "label": n["call"] if met else f"一個{n['role']}",
                        "words": [x for x in words if x]})
    reach = set(present) | {"player"}
    for tid, b in mind.mind(p)["things"].items():
        t = w.things.get(tid)
        if not t or not t["active"]:
            continue
        host = b.get("host") or b.get("holder")
        if host not in reach:
            continue
        where = ""
        if b.get("host") and b["host"] != "player":
            where = f"（{w.name(b['host'])}{mind.region_label(b['noticed'].get('region'), mind.mind(p)['domains'])}）"
        words = thing_words(b, held=b.get("holder") == "player")
        targets.append({"id": f"t:{tid}", "kind": "thing", "label": f"{b['label']}{where}", "words": words,
                        "host": b.get("host")})
    means = []
    for ab in p.get("abilities", []):
        means.append({"id": f"a:{ab['id']}", "label": ab.get("label", ""), "modality": ab["modality"],
                      "words": [x for x in (ab.get("label"), ab.get("claim")) if x]})
    for t in mind.things_of(w, "player", held=True):
        b = mind.belief(p, t["id"]) or {}
        means.append({"id": f"i:{t['id']}", "label": b.get("label", "隨身的東西"), "modality": next(iter(t["tool"]), None),
                      "words": thing_words(b, held=True)})
    return {"targets": targets, "means": means}


def absent_mention(w, text: str, cands: dict) -> str | None:
    """玩家提到一個自己知道、但現在不在眼前的東西（例如那個人已經走了）：回傳玩家對它的叫法。"""
    here = {c["id"] for c in cands["targets"]}
    for tid, b in mind.mind(w.player)["things"].items():
        if f"t:{tid}" in here:
            continue
        if any(x and x in text for x in thing_words(b)):
            return b["label"]
    return None


def seen_words(n: dict) -> list[str]:
    """還不認識的人，玩家只能用看得到的樣子叫他：身分（「鎮口守門人」「守門人」）、外表（「老兵」「姑娘」）。"""
    role = n["role"]
    out = [role] + [role[-k:] for k in (3, 2) if len(role) > k]
    first = (n.get("appearance") or "").split("，")[0].split("。")[0]
    if "的" in first:
        head = first.rsplit("的", 1)[1].strip()
        if 2 <= len(head) <= 4:
            out.append(head)
    return list(dict.fromkeys(x for x in out if len(x) >= 2))


def thing_words(b: dict, held: bool = False) -> list[str]:
    """玩家對一個東西的叫法，以及它的短稱（「老菜刀」→「菜刀」）。隨身的東西連最後一個字也算（「那把刀」）。"""
    out = []
    for s in (b.get("label") or "", (b.get("named") or {}).get("word") or ""):
        if not s:
            continue
        out.append(s)
        for part in s.replace("（", "|").replace("）", "|").replace("「", "|").replace("」", "|").split("|"):
            part = part.strip("的 ")
            if len(part) >= 2:
                out.append(part)
                if part.startswith("體內的") and len(part) > 3:
                    out.append(part[3:])
                out += [part[-k:] for k in (3, 2) if len(part) > k]
                if held and part:
                    out.append(part[-1])
    return list(dict.fromkeys(x for x in out if x))


# ---------------------------------------------------------------- 詞表解析
def _first(text, table):
    for name, words in table:
        if any(x in text for x in words):
            return name
    return None


def parse_rules(w, text: str, cands: dict | None = None) -> tuple[dict | None, list[dict]]:
    """回傳 (意圖, 候選選項)。意圖為 None 時，前端顯示選項讓玩家挑（「你是想……？」）。"""
    cands = cands or candidates(w)
    t = (text or "").strip()[:200]
    verb = _first(t, VERB_WORDS)
    if not verb and any(x in t for x in NOTE_WORDS):
        verb = "note"
    modality = _first(t, MODALITY_CUES)
    means = next((m for m in cands["means"] if any(x and x in t for x in m["words"])), None)
    if not modality and means:
        modality = means["modality"]
    if verb == "apply" and not modality:
        modality = "blunt"
    if verb == "treat" and not modality:
        modality = "chemical" if "藥" in t else "care"
    target = resolve_target(w, t, cands, verb)
    purpose = "help" if any(x in t for x in HELP_WORDS) else "harm" if any(x in t for x in HARM_WORDS) else \
        "learn" if verb in ("examine", "tap") else None
    intent = {"verb": verb or "other", "target": target["id"] if target else None, "modality": modality,
              "means": means["id"] if means else None, "purpose": purpose,
              "hypothesis": t if verb == "note" or any(x in t for x in NOTE_WORDS) else None, "text": t,
              "deep": any(x in t for x in INSIDE_WORDS)}
    needs_target = intent["verb"] in ("examine", "apply", "tap", "treat", "strike", "give", "take", "talk")
    if verb and (target or not needs_target):
        return intent, []
    return None, clarify(w, intent, cands)


def resolve_target(w, t: str, cands: dict, verb: str | None):
    """精確比對：候選的叫法出現在句子裡，或用代名詞指向剛剛關注的人／東西。不做模糊比對。"""
    p = w.player
    named = [c for c in cands["targets"] if any(x and x in t for x in c["words"])]
    things = [c for c in named if c["kind"] == "thing"]
    persons = [c for c in named if c["kind"] == "person"]
    if things:
        return max(things, key=lambda c: max(len(x) for x in c["words"] if x in t))
    focus_thing = p.get("focus_thing")
    if any(x in t for x in THING_PRONOUNS) and focus_thing:
        hit = next((c for c in cands["targets"] if c["id"] == f"t:{focus_thing}"), None)
        if hit:
            return hit
    person = persons[0] if persons else None
    if not person and any(x in t for x in PERSON_PRONOUNS):
        focus = p.get("talking_to") or p.get("focus_person")
        person = next((c for c in cands["targets"] if c["id"] == f"p:{focus}"), None)
        if not person:
            people = [c for c in cands["targets"] if c["kind"] == "person"]
            person = people[0] if len(people) == 1 else None
    if person and verb in ("apply", "tap", "treat") and any(x in t for x in INSIDE_WORDS):
        inside = [c for c in cands["targets"] if c["kind"] == "thing" and c.get("host") == person["id"][2:]]
        if len(inside) == 1:
            return inside[0]
    if person:
        return person
    if any(x in t for x in ("我自己", "自己")):
        return cands["targets"][0]
    return None


VERB_LABEL = {"examine": "仔細察看", "apply": "對它下手", "tap": "敲一敲", "treat": "替對方醫治", "strike": "動手打",
              "talk": "跟對方說話", "give": "給對方東西", "take": "拿走", "other": "試試看"}


def clarify(w, partial: dict, cands: dict) -> list[dict]:
    """解析不完整時，給玩家幾個具體的選項（伺服器產生、伺服器驗證）。"""
    opts = []
    verbs = [partial["verb"]] if partial["verb"] not in (None, "other") else ["examine", "talk", "treat"]
    targets = [c for c in cands["targets"] if c["id"] != "self"] or cands["targets"]
    if partial.get("target"):
        targets = [c for c in targets if c["id"] == partial["target"]]
    for v in verbs:
        for c in targets[:4]:
            opts.append({**partial, "verb": v, "target": c["id"], "label": f"{VERB_LABEL.get(v, v)}：{c['label']}"})
            if len(opts) >= 4:
                return opts
    return opts


# ---------------------------------------------------------------- LLM 解析（可選）
INTENT_SCHEMA = {"type": "object", "properties": {
    "verb": {"type": "string", "enum": VERBS}, "target": {"type": ["string", "null"]},
    "modality": {"type": ["string", "null"]}, "means": {"type": ["string", "null"]},
    "purpose": {"type": ["string", "null"]}}, "required": ["verb"]}


def llm_prompt(text: str, cands: dict) -> tuple[str, str]:
    system = ("你是一個文字冒險遊戲的指令理解器。玩家用一句話描述想做的事，你把它對應到固定的欄位："
              f"verb 只能是 {VERBS} 其中之一；target 只能是候選清單裡的 id 或 null；means 只能是能力／物品清單裡的 id 或 null；"
              f"modality 只能是 {MODALITIES} 其中之一或 null；purpose 只能是 {PURPOSES} 其中之一或 null。"
              "你只負責理解玩家想做什麼，事情的結果由遊戲世界決定。輸出一個 JSON 物件。")
    lines = [f"- {c['id']}：{c['label']}" for c in cands["targets"]]
    mlines = [f"- {m['id']}：{m['label']}" for m in cands["means"]]
    user = "【候選對象】\n" + "\n".join(lines) + "\n【能力與物品】\n" + ("\n".join(mlines) or "（無）") + f"\n【玩家說】{text}"
    return system, user


def validate_llm_intent(raw, cands: dict, text: str) -> dict | None:
    if not isinstance(raw, dict) or raw.get("verb") not in VERBS:
        return None
    tids = {c["id"] for c in cands["targets"]}
    mids = {m["id"] for m in cands["means"]}
    target = raw.get("target")
    means = raw.get("means")
    if target is not None and target not in tids:
        return None
    if means is not None and means not in mids:
        return None
    return {"verb": raw["verb"], "target": target, "means": means,
            "modality": raw.get("modality") if raw.get("modality") in MODALITIES else None,
            "purpose": raw.get("purpose") if raw.get("purpose") in PURPOSES else None,
            "hypothesis": text if raw["verb"] == "note" else None, "text": text,
            "deep": any(x in text for x in INSIDE_WORDS)}


def parse(w, text: str, llm=None) -> tuple[dict | None, list[dict]]:
    """llm：可選，(system, user) -> dict。LLM 結果過不了驗證就用詞表解析。"""
    cands = candidates(w)
    if llm:
        try:
            got = validate_llm_intent(llm(*llm_prompt(text, cands)), cands, (text or "")[:200])
            if got:
                return got, []
        except Exception:
            pass
    return parse_rules(w, text, cands)


def same_concept(a: str | None, b: str | None) -> bool:
    return bool(a and b) and (a == b or any(a in g and b in g for g in SAME_THING))


def describe_intent(intent: dict) -> str:
    return json.dumps({k: intent.get(k) for k in ("verb", "target", "modality", "means", "purpose")}, ensure_ascii=False)
