"""固定技能池與自訂天賦。

兩者都是「角色的初始條件」，一起決定角色會什麼、懂什麼、身上有什麼、看得見什麼：
- 固定技能（content/nature.SKILLS）：系統完全理解的穩定基礎——帶來知識（概念）、感官、做法（practice），等級只是附帶。
- 自訂天賦：玩家自由寫的一段文字。系統不要求它屬於任何預設類型。

自訂天賦的處理分兩步，刻意分開：
1. 解讀（parse）：把文字拆成一句一句的「主張」（claim）。主張只是「玩家說自己是什麼」，標上它可能涉及的面向
   （知識、經歷、身體、血統、能力、感知、身份、物品、狀態、規則、性格……認不出的就是 other）。
   有 LLM 時可以幫忙解讀，但輸出只能是原文的片段＋封閉清單裡的標籤（見 parse_llm），不能新增主張。
2. 裁定（adjudicate）：世界決定每個主張在這個世界裡「實際上」是什麼——作用範圍、強度上限、代價、可靠度、副作用。
   裁定用的亂數由世界種子與天賦原文決定（同一個世界、同一段天賦 → 同一個結果），不消耗 world.rng。

玩家腦中保留的是自己的說法（mind.self），世界裡成立的是裁定後的真實（entity["talents"]、abilities、things……）。
兩者可能不一樣：玩家要在遊戲裡自己發現「原來我的力氣是有極限的」。
"""

from __future__ import annotations

import random
import re

from . import mind
from .content.nature import (DOMAIN_CUES, FACET_CUES, MAGNITUDE_CUES, MAX_SKILLS, MODALITY_CUES, SKILLS,
                             BACKGROUND_DOMAINS, BACKGROUND_SENSES)

FACETS = ["knowledge", "profession", "experience", "memory", "identity", "ability", "perception", "body", "bloodline",
          "item", "state", "rule", "disposition", "other"]
DOMAINS = sorted({d for d, _ in DOMAIN_CUES} | {"medicine_trad", "common"})
MODALITY_NAMES = ["vibration", "heat", "cold", "cut", "chemical", "qi", "blunt", "care", "craft"]

# 知識帶來的感官與做法：懂什麼，就會注意什麼、會怎麼做（強度受限於這個世界沒有對應的器材）
DOMAIN_SENSES = {"medicine_modern": {"touch": 3, "listen": 2}, "acoustics": {"listen": 3}, "engineering": {"structure": 2},
                 "physics": {"listen": 2}, "neigong": {"qi": 1}, "cultivation": {}, "herbal": {"smell": 2},
                 "medicine_trad": {"touch": 3}}
DOMAIN_PRACTICES = {
    "medicine_modern": {"modality": "care", "magnitude": 3, "precision": 8, "reach": "touch", "label": "診察與處置"},
    "acoustics": {"modality": "vibration", "magnitude": 2, "precision": 8, "reach": "touch",
                  "label": "聚焦的震動", "phrase": "憑著記憶中的手法，借身邊的器物製造出聚焦的震動"},
    "engineering": {"modality": "craft", "magnitude": 4, "precision": 7, "reach": "touch", "label": "修造"},
    "herbal": {"modality": "chemical", "magnitude": 3, "precision": 6, "reach": "touch", "label": "用藥"},
    "neigong": {"modality": "qi", "magnitude": 2, "precision": 4, "reach": "touch", "label": "運勁"},
    "martial": {"modality": "blunt", "magnitude": 5, "precision": 5, "reach": "touch", "label": "拳腳"},
}
KNOWLEDGE_FACETS = {"knowledge", "profession", "experience", "memory", "identity"}


def talent_rng(w, who: str, text: str) -> random.Random:
    return random.Random(f"{w.seed}:talent:{who}:{text}")


# ---------------------------------------------------------------- 固定技能
def apply_background(w, who: str, background: str):
    e = w.ent(who)
    mind.init_mind(e, BACKGROUND_DOMAINS.get(background, []), BACKGROUND_SENSES.get(background, {}))


def apply_skills(w, who: str, skills) -> list[str]:
    e = w.ent(who)
    chosen = []
    for s in skills or []:
        if s in SKILLS and s not in chosen and len(chosen) < MAX_SKILLS:
            chosen.append(s)
    e["skills"] = chosen
    for s in chosen:
        spec = SKILLS[s]
        mind.init_mind(e, spec["domains"], spec.get("senses"))
        for p in spec["practices"]:
            add_ability(e, {**p, "source": f"skill:{s}", "reliability": 95})
        e["prowess_bonus"] = e.get("prowess_bonus", 0) + spec.get("prowess", 0)
    return chosen


def add_ability(e: dict, ab: dict) -> dict:
    abilities = e.setdefault("abilities", [])
    ab = {"id": f"a{len(abilities) + 1}", "magnitude": 1, "precision": 3, "reach": "touch", "reliability": 90,
          "cost": 0, **ab}
    abilities.append(ab)
    return ab


# ---------------------------------------------------------------- 解讀：文字 → 主張
_SPLIT = re.compile(r"[。！？；;\n]+|，(?=而且|並且|還|又|同時|另外)|，(?=我)")


def clauses(text: str) -> list[str]:
    text = (text or "").strip()[:400]
    out = [c.strip(" ，,、") for c in _SPLIT.split(text)]
    return [c for c in out if c]


def _cues(text, table):
    return [name for name, words in table if any(x in text for x in words)]


def parse_rules(text: str) -> list[dict]:
    """不靠 LLM 的解讀：詞表只用來「標記」，不用來「篩選」——標不出來的句子仍然是一個主張（facet=other）。"""
    out = []
    for c in clauses(text):
        facets = _cues(c, FACET_CUES)
        mods = _cues(c, MODALITY_CUES)
        mag = next((m for m, words in MAGNITUDE_CUES if any(x in c for x in words)), 5)
        out.append({"text": c, "facet": facets[0] if facets else "other", "facets": facets or ["other"],
                    "domains": _cues(c, DOMAIN_CUES), "modality": mods[0] if mods else None, "magnitude": mag})
    return out


def validate_claims(raw, text: str) -> list[dict] | None:
    """LLM 解讀的結果要過白名單：每個主張的 text 必須是玩家原文的片段（不能憑空多出天賦），
    其他欄位只能是封閉清單裡的值；多出來的欄位一律丟掉。"""
    if not isinstance(raw, list) or not raw or len(raw) > 12:
        return None
    out = []
    for c in raw:
        if not isinstance(c, dict):
            return None
        t = c.get("text")
        if not isinstance(t, str) or not t.strip() or t.strip() not in text:
            return None
        facet = c.get("facet") if c.get("facet") in FACETS else "other"
        domains = [d for d in (c.get("domains") or []) if d in DOMAINS][:4]
        mod = c.get("modality") if c.get("modality") in MODALITY_NAMES else None
        mag = c.get("magnitude") if isinstance(c.get("magnitude"), int) and 1 <= c.get("magnitude") <= 10 else 5
        out.append({"text": t.strip(), "facet": facet, "facets": [facet], "domains": domains, "modality": mod,
                    "magnitude": mag})
    return out


CLAIMS_SCHEMA = {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "object", "properties": {
    "text": {"type": "string"}, "facet": {"type": "string", "enum": FACETS},
    "domains": {"type": "array", "items": {"type": "string", "enum": DOMAINS}},
    "modality": {"type": ["string", "null"]}, "magnitude": {"type": "integer"}}, "required": ["text", "facet"]}}},
    "required": ["claims"]}


def llm_prompt(text: str) -> tuple[str, str]:
    system = ("你協助一款文字冒險遊戲理解玩家寫下的角色背景。把玩家的文字拆成幾個主張，每個主張的 text 直接摘錄原文的一段；"
              f"facet 從 {FACETS} 選一個；domains 從 {DOMAINS} 選相關的；modality 從 {MODALITY_NAMES} 選一個或 null；"
              "magnitude 是玩家宣稱的強度 1～10。你只負責整理玩家說了什麼，這些設定在遊戲世界裡實際如何成立，由遊戲決定。"
              "輸出一個 JSON 物件，欄位 claims 是主張的陣列。")
    return system, f"【玩家寫的背景】{text}"


def parse(text: str, llm=None) -> list[dict]:
    """llm：可選，(text) -> 原始 JSON list。過不了驗證就用詞表解讀。"""
    if llm:
        try:
            got = validate_claims(llm(text), text)
            if got:
                return got
        except Exception:
            pass
    return parse_rules(text)


# ---------------------------------------------------------------- 裁定：主張 → 世界真實
SELF_WORDS = {"knowledge": "你的學識", "profession": "你的本行", "experience": "你的經歷", "memory": "你的記憶",
              "identity": "你的身份", "ability": "你的能力", "perception": "你的感知", "body": "你的身體",
              "bloodline": "你的血脈", "item": "你帶著的東西", "state": "你身上的狀況", "rule": "你身上的規則",
              "disposition": "你的性子", "other": "你說不上來的特別之處"}


def adjudicate(w, who: str, claims: list[dict]) -> list[dict]:
    e = w.ent(who)
    records = []
    for c in claims:
        rng = talent_rng(w, who, c["text"])
        rec = {"claim": c["text"], "facet": c["facet"], "granted": {}}
        facets = set(c["facets"])
        domains = list(c["domains"])
        # 任何主張都可能帶著知識（「前世是醫生」「研究超聲波」）：懂的東西進心智
        if domains and (facets & KNOWLEDGE_FACETS or c["facet"] == "other"):
            senses = {}
            for d in domains:
                for k, v in DOMAIN_SENSES.get(d, {}).items():
                    senses[k] = max(senses.get(k, 0), v)
            mind.init_mind(e, domains, senses)
            rec["granted"]["domains"] = domains
            rec["granted"]["senses"] = senses
            for d in domains:
                p = DOMAIN_PRACTICES.get(d)
                if p and not any(a.get("source") == f"talent:{d}" for a in e.get("abilities", [])):
                    ab = add_ability(e, {**p, "source": f"talent:{d}", "claim": c["text"], "reliability": 90})
                    rec["granted"].setdefault("abilities", []).append(ab["id"])
        f = c["facet"]
        if f == "ability" or (f == "other" and c["modality"]):
            # 玩家說自己能做到什麼：世界給的是有上限、有代價、不一定每次都成的版本
            claimed = c["magnitude"]
            cap = rng.randint(3, 7)
            mag = min(claimed, cap)
            ab = add_ability(e, {"modality": c["modality"] or "qi", "magnitude": mag, "precision": rng.randint(2, 6),
                                 "reach": "touch", "reliability": max(40, 92 - 6 * max(0, mag - 4)),
                                 "cost": max(0, (mag - 4) * 5), "label": c["text"], "claim": c["text"],
                                 "phrase": "使出你相信自己擁有的那份本事",
                                 "claimed_magnitude": claimed, "source": "talent:ability"})
            rec["granted"]["ability"] = ab["id"]
        elif f == "perception":
            which = "spirit" if any(x in c["text"] for x in ("看不見", "看不到", "鬼", "靈", "妖", "常人")) else \
                "qi" if "氣" in c["text"] else "listen" if "聽" in c["text"] else "smell" if "聞" in c["text"] else "spirit"
            depth = rng.randint(1, 2)
            mind.init_mind(e, [], {which: depth})
            rec["granted"]["senses"] = {which: depth}
        elif f in ("bloodline", "body"):
            tid = None
            if f == "bloodline" or any(x in c["text"] for x in ("龍", "妖", "仙", "神", "異")):
                tid = mind.add_thing(w, "lineage", host=who, origin="talent",
                                     traits={"energy": rng.randint(3, 7)})
                rec["granted"]["thing"] = tid
            bonus = round(rng.uniform(0.3, 1.5), 1)
            e["prowess_bonus"] = e.get("prowess_bonus", 0) + bonus
            rec["granted"]["prowess"] = bonus
        elif f == "item":
            special = any(x in c["text"] for x in ("特殊", "神秘", "奇怪", "不明", "陪伴", "傳家", "古"))
            if any(x in c["text"] for x in ("刀", "劍", "刃", "匕")):
                kind = "blade_odd" if special and rng.random() < 0.7 else "blade"
            else:
                kind = "trinket"
            tid = mind.add_thing(w, kind, holder=who, origin="talent")
            w.things[tid]["label_self"] = c["text"]
            rec["granted"]["thing"] = tid
        elif f == "state":
            kind = rng.choice(["seedling", "foreign_needle", None])   # None：其實什麼也沒有
            if kind:
                rec["granted"]["thing"] = mind.add_thing(w, kind, host=who, origin="talent")
            else:
                rec["granted"]["nothing"] = True
        elif f == "rule":
            r = {"text": c["text"], "reliability": rng.randint(60, 95),
                 "hook": "lost" if "迷路" in c["text"] else None}
            e.setdefault("rules", []).append(r)
            rec["granted"]["rule"] = r
        elif f == "disposition":
            tags = [t for t, words in (("distrust", ("不信任", "多疑")), ("bold", ("膽大", "不怕")), ("timid", ("膽小",)),
                                         ("calm", ("冷靜",))) if any(x in c["text"] for x in words)]
            e.setdefault("disposition", []).extend(tags or ["other"])
            rec["granted"]["disposition"] = tags or ["other"]
        elif f == "other" and not rec["granted"]:
            e.setdefault("latent", []).append({"text": c["text"], "domains": domains})
            rec["granted"]["latent"] = True
        records.append(rec)
        mind.mind(e)["self"].append({"text": c["text"], "about": SELF_WORDS.get(f, SELF_WORDS["other"])})
    e.setdefault("talents", []).extend(records)
    return records


def setup_character(w, who: str, background: str, skills=(), talent: str = "", llm=None) -> dict:
    """出身（原本的）＋固定技能（最多兩項）＋自訂天賦（可空白），一起成為角色的初始條件。"""
    apply_background(w, who, background)
    chosen = apply_skills(w, who, skills)
    e = w.ent(who)
    e["talent_text"] = (talent or "").strip()[:400]
    claims = parse(e["talent_text"], llm) if e["talent_text"] else []
    e["talent_claims"] = claims
    records = adjudicate(w, who, claims) if claims else []
    # 自己的身體：角色知道自己體內有什麼——用自己的感官去感覺（不一定準）
    self_perceive(w, who)
    return {"skills": chosen, "claims": claims, "records": records}


def self_perceive(w, who: str):
    e = w.ent(who)
    for t in mind.things_of(w, who):
        noticed = mind.noticeable(w, e, t, contact=True)
        if t["holder"] == who:
            noticed.setdefault("form", t["traits"].get("form"))
        if noticed:
            b = mind.believe_thing(w, who, t["id"], noticed, "self")
            if t.get("label_self"):        # 自己帶來的東西，自己知道它是什麼（至少知道自己怎麼叫它）
                b["label"] = t["label_self"]
