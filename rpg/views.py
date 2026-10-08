"""一件事的「各人版本」（view）：誰看到了什麼、怎麼理解、怎麼轉述。

世界裡發生的事只有一條真實的事實（world.facts，truth=True）；每個知道它的人，knows[fid]["view"] 是自己的版本：
  actor       認為是誰做的（None＝不知道是誰）
  face        看到了臉但叫不出名字（之後再見到可能認出來）——只是「記得那張臉」，不是知道是誰
  actor_desc  說得出的樣子（「一個外地人」「一個像是郎中的外地人」……）
  verb / modality / method   做了什麼、用什麼方式（method 是用自己的話說的）
  host        被作用的人
  thing / thing_label / thing_concept   作用在什麼東西上、自己叫它什麼
  effects     自己察覺到的後果（不一定是全部的後果）
  exag        轉述時被誇大過幾次

規則：
- 察覺（perceive）只用這個人的感官與知識：體內的東西碎了，旁人看不見；震動有沒有被聽出來，要看耳朵。
- 轉述（retell）是用聽的人自己的知識重新理解講的人的版本，嘴碎的人會加油添醋，不老實的人會換掉主角。
  所以同一件事在鎮上會長出好幾個版本——沒有任何「全鎮共用的旗標」。
"""

from __future__ import annotations

from . import mind
from .content.nature import CONCEPTS, SAME_THING

VISIBLE_TO_ALL = {"collapse", "bleed", "heat_wave"}


def actor_desc(w, observer: str, actor: str, verb: str) -> str:
    seen_doctoring = any(
        f["type"] == "act" and f["roles"].get("actor") == actor and f["data"].get("verb") in ("examine", "treat")
        for fid in w.ent(observer)["knows"] for f in [w.facts.get(fid)] if f) if observer != actor else False
    base = "一個外地人" if actor == "player" else "一個陌生人"
    if verb in ("examine", "treat") or seen_doctoring:
        return "一個像是郎中的外地人" if actor == "player" else "一個像是郎中的人"
    return base


def knows_face(w, observer: str, actor: str) -> bool:
    if observer == actor:
        return True
    if actor == "player":
        return observer in w.player["met"] or w.npcs[observer].get("met_player")
    return True   # 鎮民彼此認得


def perceive(w, observer: str, ev: dict) -> dict:
    """observer 對事件 ev 的版本。ev 是世界模擬器給的真實：actor、host、thing、verb、modality、effects、contact。"""
    o = w.ent(observer)
    domains = mind.mind(o)["domains"]
    actor, host = ev["actor"], ev.get("host")
    conscious = observer != host or "collapse" not in ev["effects"]
    v = {"verb": ev["verb"], "host": host, "thing": ev.get("thing"), "exag": 0, "effects": [], "modality": None,
         "actor": None, "face": None, "actor_desc": None}
    if observer == actor:
        v["actor"] = actor
    elif conscious and knows_face(w, observer, actor):
        v["actor"] = actor
    elif conscious:
        v["face"] = actor
        v["actor_desc"] = actor_desc(w, observer, actor, ev["verb"])
    else:
        v["actor_desc"] = "有人"
    # 作用方式：做的人知道；被作用的人摸得到震動、熱；旁人要聽得到、看得到
    mod = ev.get("modality")
    if mod:
        if observer == actor or (observer == host and ev.get("contact")):
            v["modality"] = mod
        elif mod in ("vibration",) and mind.sense(o, "listen") >= 1 and ev.get("magnitude", 0) >= 2:
            v["modality"] = mod
        elif mod in ("heat", "cut", "blunt", "cold"):
            v["modality"] = mod
    v["method"] = mind.method_label(v["modality"], domains) if v["modality"] else "某種手法"
    # 作用在什麼上：自己對那個東西有理解，就用自己的叫法
    tid = ev.get("thing")
    b = mind.belief(o, tid) if tid else None
    if b:
        v["thing_label"], v["thing_concept"] = b["label"], b["concept"]
    # 察覺得到的後果
    for eff in ev["effects"]:
        if eff in VISIBLE_TO_ALL:
            v["effects"].append(eff)
        elif eff == "pain" and (observer == host or mind.sense(o, "sight") >= 1):
            v["effects"].append(eff)
        elif eff in ("thing_cracked", "thing_shattered"):
            if (observer == actor and ev.get("contact")) or (observer == host and b) or \
                    (b and mind.sense(o, "qi") >= 2):
                v["effects"].append(eff)
        elif eff == "power_loss":
            if (observer == host and (b or mind.sense(o, "qi") >= 1)) or mind.sense(o, "qi") >= 2:
                v["effects"].append(eff)
        elif eff == "relief" and (observer == host or (observer == actor and ev.get("contact"))):
            v["effects"].append(eff)
        elif eff == "nothing" and observer == actor:
            v["effects"].append(eff)
    if not v["effects"] and observer != actor:
        v["effects"].append("unclear")
    return v


def retell(w, teller: str, listener: str, fid: str) -> dict | None:
    """teller 把自己的版本講給 listener：用 listener 自己的知識重新理解，嘴碎的人會誇大，不老實的人可能換掉主角。"""
    tv = (w.ent(teller)["knows"].get(fid) or {}).get("view")
    if tv is None:
        return None
    lv = dict(tv)
    lv["effects"] = list(tv.get("effects", []))
    lv["face"] = None                      # 臉是自己看到的，轉述不過去
    le = w.ent(listener)
    ldom = mind.mind(le)["domains"]
    if lv.get("modality"):
        lv["method"] = mind.method_label(lv["modality"], ldom)
    if tv.get("thing"):
        lb = mind.tell_name(w, teller, listener, tv["thing"]) if mind.belief(w.ent(teller), tv["thing"]) else None
        if lb:
            lv["thing_label"], lv["thing_concept"] = lb["label"], lb["concept"]
        elif tv.get("thing_concept"):
            mine = [c for g in SAME_THING if tv["thing_concept"] in g for c in g if c in mind.concepts_of(le)]
            if mine:
                lv["thing_label"], lv["thing_concept"] = CONCEPTS[mine[0]]["label"], mine[0]
    if teller in w.npcs:
        t = w.npcs[teller]
        if t["traits"]["gossip"] >= 6 and w.roll(t["traits"]["gossip"] * 7, lo=0, hi=80):
            lv["exag"] = min(3, lv.get("exag", 0) + 1)
        if lv.get("actor") and t["traits"]["honesty"] <= 4 and w.roll((10 - t["traits"]["honesty"]) * 4, lo=0, hi=40):
            disliked = [o for o, v in t["opinions"].items() if v <= -25 and o in w.npcs and o != lv["actor"]
                        and w.npcs[o]["status"] in ("normal", "jailed")]
            if disliked:
                lv["actor"] = min(disliked, key=lambda o: t["opinions"][o])
    return lv


def recognize(w, observer: str, actor: str) -> list[str]:
    """observer 看到 actor 的臉：之前只記得臉的事件，現在知道是誰做的了。回傳被認出來的事件。"""
    out = []
    for fid, info in w.ent(observer)["knows"].items():
        v = info.get("view")
        if v and v.get("face") == actor and v.get("actor") is None:
            v["actor"] = actor
            v["face"] = None
            out.append(fid)
    return out


# ---------------------------------------------------------------- 說出口
def _who(w, ref, speaker, listener):
    if ref is None:
        return None
    if ref == speaker:
        return "我"
    if ref == "player":
        return "你" if listener == "player" else "那個外地人"
    return w.name(ref)


EFFECT_TEXT = {
    "thing_cracked": ["把{thing}震出了裂痕", "震碎了{thing}", "隔空震碎了{thing}", "隔空就把{thing}震得粉碎"],
    "thing_shattered": ["把{thing}弄碎了", "把{thing}整個打碎了", "隔空把{thing}打得粉碎", "隔空把{thing}化成了粉"],
    "pain": ["{host}痛得直冒冷汗", "{host}痛得在地上打滾", "{host}痛得死去活來", "{host}痛得死去活來"],
    "collapse": ["{host}當場倒了下去", "{host}當場昏死過去", "{host}差點就這麼沒了", "{host}差點就這麼沒了"],
    "bleed": ["血流了一地"] * 4,
    "heat_wave": ["一股熱浪炸了開來", "一股熱浪把旁人都掀開了", "整條街都感覺到那股熱浪", "整條街都感覺到那股熱浪"],
    "power_loss": ["{host}的功力大損", "{host}的修為廢了大半", "{host}的修為全廢了", "{host}的修為全廢了"],
    "relief": ["{host}好像舒服多了", "{host}的病一下子就好了", "{host}的病一下子就好了", "{host}的病一下子就好了"],
    "nothing": ["沒見到什麼變化"] * 4,
    "unclear": ["之後怎麼樣就不清楚了"] * 4,
}


def render(w, f: dict, view: dict | None, speaker: str | None = None, listener: str = "player") -> str:
    """把某人的版本說成一句話（不含句號）。沒有 view 時用事實上記的角色（開發者看的真實版本）。"""
    v = view or {"actor": f["roles"].get("actor"), "host": f["roles"].get("target"), "verb": f["data"].get("verb"),
                 "method": mind.method_label(f["data"].get("modality"), ["common"]),
                 "thing_label": f["data"].get("thing_label"), "effects": f["data"].get("effects", []), "exag": 0}
    exag = min(3, v.get("exag", 0))
    who = _who(w, v.get("actor"), speaker, listener)
    if who is None:
        desc = v.get("actor_desc") or "有人"
        if exag and desc.startswith("一個"):
            desc = "一個神秘醫師" if "郎中" in desc else "一個神秘的" + desc[2:]
        who = desc
    host = _who(w, v.get("host"), speaker, listener) or "某人"
    thing = v.get("thing_label")
    thing_ref = f"{host}的{thing}" if thing else f"{host}的身子"
    verb = v.get("verb")
    method = v.get("method") or "某種手法"
    if verb == "examine":
        head = f"{who}仔細察看了{host}"
    elif verb == "tap":
        head = f"{who}敲了敲{thing_ref}"
    elif verb == "treat":
        head = f"{who}用{method}替{host}醫治"
    elif verb == "strike":
        head = f"{who}動手打了{host}"
    else:
        head = f"{who}用{method}對{thing_ref}下了手" if thing else f"{who}用{method}對付{host}"
    tails = []
    for eff in v.get("effects", []):
        pool = EFFECT_TEXT.get(eff)
        if pool:
            tails.append(pool[exag].format(thing=thing_ref if thing else "那東西", host=host))
    if any(e in ("thing_cracked", "thing_shattered") for e in v.get("effects", [])) and thing:
        head = f"{who}用{method}"
    return head + ("，" + "，".join(tails) if tails else "")
