"""角色的認知：感官 → 察覺到的性質 → 用自己的概念去理解 → 信念。

世界真實（world.things、world.facts、各人的真實狀態）只有一份；每個角色腦中是自己的版本：
- 察覺：只拿得到自己感官夠得到的性質（content/nature.TRAITS 規定哪個性質要用什麼感官、多敏銳）。
- 理解：用自己會的概念去套（content/nature.CONCEPTS）。懂醫的看成結石、練內功的看成內丹、不懂的只說是個硬塊。
- 信念：記在 entity["mind"]["things"]，可以錯、可以累積、可以被別人告知的名字改變、可以被實驗推翻。

角色做決定只能讀這裡（以及自己知道的事實），不能讀 world.things 的 kind 或別人的真實數值。
這裡的函式也是 NPC 決策「該看什麼」的唯一入口（例如估別人有多少錢）。
"""

from __future__ import annotations

import random

from .content.nature import (CONCEPTS, DEFAULT_SENSES, DESCRIBE, KINDS, MODALITIES, REGIONS, SAME_THING, TRAITS)


# ---------------------------------------------------------------- 心智的建立
def init_mind(e: dict, domains=(), senses=None):
    m = e.setdefault("mind", {"domains": [], "things": {}, "learned": [], "self": []})
    for d in ["common", *domains]:
        if d not in m["domains"]:
            m["domains"].append(d)
    s = e.setdefault("senses", dict(DEFAULT_SENSES))
    for k, v in (senses or {}).items():
        s[k] = max(s.get(k, 0), v)
    return m


def mind(e: dict) -> dict:
    return init_mind(e) if "mind" not in e else e["mind"]


def sense(e: dict, name: str) -> int:
    return e.get("senses", DEFAULT_SENSES).get(name, 0)


def concepts_of(e: dict) -> list[str]:
    m = mind(e)
    return [cid for cid, c in CONCEPTS.items() if c["domain"] in m["domains"] or cid in m["learned"]]


# ---------------------------------------------------------------- 世界裡的東西（真實）
def add_thing(w, kind: str, host: str | None = None, holder: str | None = None, place: str | None = None,
              origin: str = "start", traits: dict | None = None) -> str:
    k = KINDS[kind]
    w.thing_seq += 1
    tid = f"t{w.thing_seq}"
    w.things[tid] = {
        "id": tid, "kind": kind, "host": host, "holder": holder, "place": place,
        "traits": {**k["traits"], **(traits or {})}, "internal": bool(k.get("internal")),
        "integrity": 100, "vital": k.get("vital"), "volatile": k.get("volatile", 0), "brittle": bool(k.get("brittle")),
        "cause": k.get("cause"), "tool": dict(k.get("tool") or {}), "origin": origin, "active": True,
    }
    return tid


def things_of(w, ref: str, held: bool | None = None) -> list[dict]:
    """ref 身上（體內或隨身）的東西。held=True 只要隨身物品、False 只要體內的、None 都要。"""
    out = []
    for t in w.things.values():
        if not t["active"]:
            continue
        if held is not True and t["host"] == ref:
            out.append(t)
        elif held is not False and t["holder"] == ref:
            out.append(t)
    return out


def power_of(w, ref: str) -> float:
    """功力：體內跟「功力」連在一起的東西還剩多少（真實值，只有世界模擬器用）。"""
    return sum(t["traits"].get("energy", 0) * t["integrity"] / 100 for t in things_of(w, ref, held=False)
               if t["vital"] == "power")


# ---------------------------------------------------------------- 察覺
def noticeable(w, observer: dict, thing: dict, contact: bool, events=()) -> dict:
    """observer 這一次能察覺到 thing 的哪些性質。contact＝有沒有實際碰到（觸診、敲、壓）；
    events＝這次發生了什麼作用（例如 vibrated：被震動時，共鳴才聽得出來）。"""
    out = {}
    for trait, value in thing["traits"].items():
        spec = TRAITS.get(trait)
        if not spec:
            continue
        if spec.get("experiment") and not ({"vibrated", "tapped"} & set(events)):
            continue
        routes = spec["internal_senses"] if thing["internal"] else spec["sense"]
        for sname, depth in routes:
            if sname in ("touch",) and not contact:
                continue
            if sname == "listen" and thing["internal"] and not contact and "vibrated" not in events:
                continue
            if sense(observer, sname) >= depth:
                out[trait] = value
                break
    if out:
        out["internal"] = bool(thing["internal"])    # 在不在身體裡，察覺到東西的同時就知道
    return out


# ---------------------------------------------------------------- 理解
def _ok(cond, value) -> bool:
    if isinstance(cond, tuple):
        op, x = cond
        try:
            return value >= x if op == ">=" else value <= x
        except TypeError:
            return False
    if isinstance(cond, list):
        return value in cond
    return value == cond


def interpret(observer: dict, noticed: dict) -> tuple[str | None, int]:
    """用 observer 會的概念去理解察覺到的性質。回傳 (概念 id, 把握 0～100)；套不上任何概念時是 (None, 0)。"""
    best, best_score, best_cov = None, 0.0, 0.0
    for cid in concepts_of(observer):
        c = CONCEPTS[cid]
        if any(n not in noticed for n in c.get("needs", [])):
            continue
        matched, seen, tight = 0, 0, 0.0
        reject = False
        for trait, cond in c["pattern"].items():
            if trait not in noticed:
                continue
            seen += 1
            if _ok(cond, noticed[trait]):
                matched += 1
                if isinstance(cond, tuple):      # 門檻越嚴的條件越具體（能量 ≥7 比 ≥2 更能說明這是什麼）
                    tight += (cond[1] if cond[0] == ">=" else 10 - cond[1]) * 0.02
            else:
                reject = True
                break
        coverage = matched / len(c["pattern"])
        if reject or seen == 0 or coverage < 0.4:
            continue
        # 跟察覺到的每一點都吻合的概念裡，吻合得越多（越具體）越優先；新的證據只要不矛盾，就不會推翻原本的理解
        score = (matched + len(c.get("needs", [])) * 0.5 + tight) * c.get("weight", 1.0)
        if score > best_score:
            best, best_score, best_cov = cid, score, coverage * c.get("weight", 1.0)
    if not best:
        return None, 0
    return best, int(min(95, best_cov * 100))


def region_label(region: str | None, domains) -> str:
    if not region:
        return ""
    labels = REGIONS.get(region, {"default": "身上"})
    for d in reversed(list(domains)):
        if d in labels:
            return labels[d]
    return labels["default"]


def method_label(modality: str | None, domains) -> str:
    labels = MODALITIES.get(modality or "", {"default": "某種手法"})
    for d in reversed(list(domains)):
        if d in labels:
            return labels[d]
    return labels["default"]


def describe(noticed: dict, domains=()) -> str:
    """不認得時的說法：只用察覺到的性質，任何人都說得出口。"""
    bits = []
    if "size" in noticed:
        bits.append(DESCRIBE["size"].get(noticed["size"], ""))
    if "hardness" in noticed:
        bits.append(next(w for v, w in DESCRIBE["hardness"] if noticed["hardness"] >= v) + "的")
    if "warmth" in noticed:
        bits.append(DESCRIBE["warmth"].get(noticed["warmth"], "") + "的")
    form = DESCRIBE["form"].get(noticed.get("form"), "東西")
    extra = []
    if "energy" in noticed and noticed["energy"]:
        extra.append(next(w for v, w in DESCRIBE["energy"] if noticed["energy"] >= v))
    if noticed.get("resonant"):
        extra.append(DESCRIBE["resonant"][True])
    if "material" in noticed and noticed["material"] in DESCRIBE["material"]:
        extra.append(DESCRIBE["material"][noticed["material"]])
    where = region_label(noticed.get("region"), domains)
    head = (f"{where}有一個" if where else "一個") + "".join(bits) + form
    return head + ("，" + "，".join(extra) if extra else "")


# ---------------------------------------------------------------- 信念
def belief(e: dict, tid: str) -> dict | None:
    return mind(e)["things"].get(tid)


def believe_thing(w, who: str, tid: str, noticed: dict, src: str) -> dict:
    """把這次察覺到的性質併入 who 對 tid 的信念，然後用 who 自己的概念重新理解。
    理解改變時記進 history——角色的世界觀是一步一步建立（也可能一步一步走偏）的。"""
    e = w.ent(who)
    t = w.things[tid]
    b = mind(e)["things"].setdefault(tid, {"noticed": {}, "concept": None, "label": None, "conf": 0, "named": None,
                                          "host": t["host"], "holder": t["holder"], "src": src, "day": w.day,
                                          "history": []})
    b["noticed"].update(noticed)
    cid, conf = interpret(e, b["noticed"])
    label = CONCEPTS[cid]["label"] if cid else describe(b["noticed"], mind(e)["domains"])
    if t.get("label_self") and t.get("holder") == who:
        label = t["label_self"]          # 自己帶來的東西，自己知道它叫什麼
    if b["named"] and not cid:
        label = f"{label}（聽說叫「{b['named']['word']}」）"
    if label != b["label"]:
        if b["label"]:
            b["history"].append({"day": w.day, "label": b["label"]})
        b.update(concept=cid, label=label, conf=conf)
    b["day"] = w.day
    return b


def tell_name(w, teller: str, listener: str, tid: str) -> dict | None:
    """teller 把自己對 tid 的叫法告訴 listener。listener 會用自己的知識接住它：
    - 自己的知識裡有「同一個東西」的概念 → 換成自己懂的說法（並記得對方怎麼叫）。
    - 完全沒有 → 記下這個詞（「聽說叫金丹」），但不知道它是什麼。"""
    tb = belief(w.ent(teller), tid)
    if not tb or not tb.get("label"):
        return None
    le = w.ent(listener)
    lb = mind(le)["things"].setdefault(tid, {"noticed": {}, "concept": None, "label": None, "conf": 0, "named": None,
                                             "host": tb.get("host"), "holder": tb.get("holder"), "src": teller,
                                             "day": w.day, "history": []})
    # 傳過去的是「那個詞」：講的人自己也只是聽說的，就只傳那個聽來的詞
    word = tb["label"] if tb["concept"] or not tb.get("named") else tb["named"]["word"]
    if tb["concept"]:
        mine = [c for group in SAME_THING if tb["concept"] in group for c in group if c in concepts_of(le)]
        if mine and mine[0] != lb["concept"]:
            if lb["label"]:
                lb["history"].append({"day": w.day, "label": lb["label"]})
            lb.update(concept=mine[0], label=CONCEPTS[mine[0]]["label"], conf=max(lb["conf"], 50))
            lb["named"] = {"word": word, "by": teller}
            return lb
    lb["named"] = {"word": word, "by": teller}
    if not lb["concept"]:
        if lb["label"]:
            lb["history"].append({"day": w.day, "label": lb["label"]})
        lb["label"] = (f"{describe(lb['noticed'], mind(le)['domains'])}（聽說叫「{word}」）" if lb["noticed"]
                       else f"一個叫「{word}」的東西")
        lb["conf"] = 30
    return lb


def learn_concept(w, who: str, cid: str):
    """學會一個新概念（被教、讀到、反覆實驗之後）。之後再看同樣的東西，理解就會不一樣。"""
    m = mind(w.ent(who))
    if cid not in m["learned"]:
        m["learned"].append(cid)
    for tid, b in list(m["things"].items()):
        if tid in w.things and b["noticed"]:
            believe_thing(w, who, tid, {}, b["src"])


# ---------------------------------------------------------------- NPC 決策用的「估計」（不可直接讀別人的真實數值）
WEALTH_BY_ROLE = {"酒館老闆": 120, "客棧掌櫃": 120, "賭坊東家": 400, "地主": 600, "濟世堂大夫": 100, "武館館主": 80,
                  "雜貨攤販": 60, "繡娘": 50, "外地行商": 200, "船夫": 40}
WEALTH_BY_BACKGROUND = {"heir": 150, "peddler": 70, "herbalist": 45, "scholar": 30, "escort": 45, "drifter": 10}


def perceived_wealth(w, observer: str, target: str) -> int:
    """observer 覺得 target 大概有多少錢：看身分、產業、聽說過的事（贏錢、被偷、借錢），加上看走眼的誤差。
    會估量的人誤差小。這是 NPC 決定「偷誰、跟誰借」的依據——不是 target 錢包裡的真實數字。"""
    if target == "player":
        base = WEALTH_BY_BACKGROUND.get(w.player.get("background"), 30)
    else:
        t = w.npcs[target]
        base = WEALTH_BY_ROLE.get(t["role"], 25)
        if any(p["owner"] == target for p in w.properties.values()):
            base += 40
    obs = w.ent(observer) if observer == "player" or observer in w.npcs else {}
    for fid in obs.get("knows", {}):
        f = w.facts.get(fid)
        if not f or target not in f["roles"].values():
            continue
        amt = f["data"].get("amount", 0) or 0
        if f["type"] == "gamble_win" or (f["type"] == "theft" and f["roles"].get("thief") == target):
            base += amt
        elif f["type"] in ("gamble_loss", "theft_report", "property_seized") or \
                (f["type"] == "loan" and f["roles"].get("borrower") == target):
            base -= amt or 30
    skill = sense(obs, "appraise") if obs else 0
    noise = random.Random(f"{w.seed}:{observer}:{target}:{w.day // 3}").uniform(-0.5, 0.5) * (1 - skill / 4)
    return max(0, int(base * (1 + noise)))


def believed_actor(w, who: str, fid: str):
    """who 認為某件事是誰做的：有自己的版本（view）就看自己的版本，否則看事實上記的角色。"""
    info = w.ent(who)["knows"].get(fid)
    if info and "view" in info:
        return info["view"].get("actor")
    return w.culprit_of(w.facts[fid])


def shown_attitude(w, nid: str) -> int:
    """玩家感覺得到的態度：是 NPC 表現出來的樣子，不是心裡的數字。不老實的人心裡有疙瘩，臉上還是客客氣氣。"""
    n = w.npcs[nid]
    op = w.opinion(nid, "player")
    if op < 0 and n["traits"]["honesty"] <= 3:
        return max(op, 15)
    return op
