"""自由行動的世界模擬：意圖 → 世界規則 → 真實結果 → 各人察覺到的版本 → 玩家看得到的片段。

流程（每一步都在世界這邊，LLM 不參與決定）：
1. 目標：意圖裡的 target 是「玩家以為的東西」（例如玩家叫它結石）。這裡把它對回世界裡真實的那個東西。
2. 能力：玩家「實際上」做得到什麼——技能、天賦裁定後的能力、手上的工具；什麼都沒有就是徒手。
   能力有可靠度（可能使不出來）與代價（會傷到自己）。玩家以為自己能做到的程度，世界不採信。
3. 規則：作用方式 × 目標的客觀性質（硬度、會不會共振、脆不脆、蘊藏多少能量、跟宿主的什麼連在一起……）。
   規則只看性質，不看東西叫什麼——同一套規則套在結石上和套在別的東西上，自然會有不同的結果。
4. 後果：寫成一條真實的事實（type="act"），每個在場的人各自得到自己察覺到的版本（views.perceive）。
5. 玩家只看到自己察覺到的東西；玩家的理解（例如「那是結石」）不會被偷偷改正，除非新的證據讓他自己改觀。
"""

from __future__ import annotations

from . import intent as intent_mod
from . import mind, sim, views
from .content.locations import LOCATIONS
from .content.nature import CAUSES

PHYSICAL = {"vibration", "blunt", "cut", "heat", "cold", "qi"}


# ---------------------------------------------------------------- 入口
def do(w, text: str, llm=None):
    p = w.player
    sim.beat(w, "player_say", f"你打算：{clean(text)}")
    it, opts = intent_mod.parse(w, text, llm)
    if not it and (gone := intent_mod.absent_mention(w, text, intent_mod.candidates(w))):
        w.flags["_do_opts"] = []
        sim.beat(w, "system", f"你要找的「{gone}」不在眼前。")
        return
    if not it:
        w.flags["_do_opts"] = opts
        if opts:
            sim.beat(w, "system", "你想做的是哪一個？")
        else:
            sim.beat(w, "system", "你想了想，一時不知道該從何下手。")
        return
    w.flags["_do_opts"] = []
    resolve(w, it)
    p["last_intent"] = {k: it.get(k) for k in ("verb", "target", "modality", "means", "purpose")}


def choose_option(w, idx: int):
    opts = w.flags.get("_do_opts") or []
    if 0 <= idx < len(opts):
        it = dict(opts[idx])
        it.pop("label", None)
        w.flags["_do_opts"] = []
        resolve(w, it)


def clean(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isprintable() and ch not in "\r\n\t")[:120]


def _target(w, ref: str | None):
    """意圖的 target → 世界裡真實的對象。('person', nid) / ('thing', tid) / ('self', 'player') / (None, None)。"""
    if not ref:
        return None, None
    if ref == "self":
        return "self", "player"
    kind, _, rid = ref.partition(":")
    if kind == "p" and rid in w.npcs:
        return "person", rid
    if kind == "t" and rid in w.things and w.things[rid]["active"]:
        return "thing", rid
    return None, None


def resolve(w, it: dict):
    p = w.player
    verb = it["verb"]
    kind, ref = _target(w, it.get("target"))
    if verb == "note":
        return note(w, it, ref if kind == "thing" else None)
    if verb in ("talk", "give", "take", "move", "wait"):
        return route_existing(w, it, kind, ref)
    if kind is None:
        sim.beat(w, "action", "你看了看四周，找不到你說的對象。")
        return
    if kind == "person":
        p["focus_person"] = ref
    if kind == "thing":
        p["focus_thing"] = ref
    if verb in ("examine", "tap"):
        return examine(w, it, kind, ref)
    if verb in ("apply", "treat", "strike"):
        return apply(w, it, kind, ref)
    sim.beat(w, "action", "你試了試，卻不太確定自己到底想做什麼，最後什麼也沒發生。")
    sim.advance(w, 1)


# ---------------------------------------------------------------- 只在腦中：推測
def note(w, it: dict, tid: str | None):
    """玩家的推測只寫進玩家自己的腦中——不會讓世界變成那樣，也不會被系統糾正。"""
    m = mind.mind(w.player)
    m.setdefault("notes", []).append({"day": w.day, "text": it["text"], "about": tid})
    del m["notes"][:-30]
    if tid and mind.belief(w.player, tid):
        mind.belief(w.player, tid)["hypothesis"] = it["text"]
    sim.beat(w, "action", "你在心裡記下了這個想法。")


# ---------------------------------------------------------------- 交給原本就有的系統
def route_existing(w, it, kind, ref):
    from . import dialogue, player as player_mod

    p = w.player
    verb = it["verb"]
    if verb == "talk" and kind == "person":
        if p.get("talking_to") != ref:
            return dialogue.start_talk(w, ref)
        return dialogue.do_talk(w, "chat")
    if verb == "move":
        for nb in LOCATIONS[p["location"]]["neighbors"]:
            if LOCATIONS[nb]["name"] in it["text"] or LOCATIONS[nb]["name"][:2] in it["text"]:
                return player_mod.do_move(w, nb)
        sim.beat(w, "action", "你想了想，不知道該往哪裡去。")
        return
    if verb == "wait":
        sim.beat(w, "action", "你找了個地方歇著，讓時間過去。")
        return sim.advance(w, 2)
    if verb == "take" and kind != "person" and p["location"] in ("market", "tavern", "inn", "pharmacy"):
        return player_mod.do_steal(w)
    if verb == "give" and kind == "person":
        if p.get("talking_to") != ref:
            dialogue.start_talk(w, ref)
        sim.beat(w, "system", "（要給什麼、給多少，請從談話選項裡挑。）")
        return
    sim.beat(w, "action", "你比劃了一下，最後沒有真的動手。")


# ---------------------------------------------------------------- 察看
def allows_contact(w, nid: str, verb: str) -> bool:
    """要碰到對方的身體，對方得肯：病著、傷著、昏著的人比較肯讓人看；陌生人無故摸過來會被推開。"""
    n = w.npcs[nid]
    if n["status"] == "jailed" and w.player["location"] != "yamen":
        return False
    if n["health"] < 30 or n.get("bedridden"):
        return w.opinion(nid, "player") > -40
    unwell = n["condition"] != "healthy" or n.get("symptom_until", -1) >= w.day
    need = -10 if unwell else 20
    if w.player.get("talking_to") == nid:
        need -= 15
    return w.opinion(nid, "player") >= need


def examine(w, it, kind, ref):
    p = w.player
    events = ("tapped",) if it["verb"] == "tap" else ()
    if kind == "person":
        n = w.npcs[ref]
        contact = allows_contact(w, ref, "examine")
        lines = [f"你打量{w.name(ref) if ref in p['met'] else '對方'}。" + outward(w, ref)]
        if not contact:
            lines.append(f"{w.name(ref)}往後一縮，不讓你碰。你只能遠遠看著。" if ref in p["met"] else "對方往後一縮，不讓你碰。")
        found = 0
        for t in mind.things_of(w, ref, held=False):
            noticed = mind.noticeable(w, p, t, contact=contact, events=events)
            if not noticed:
                continue
            found += 1
            lines.append(observe_line(w, t["id"], noticed))
        if contact and not found:
            lines.append("你仔細察看了一遍，沒有發現什麼特別的。")
        record(w, "examine", ref, None, None, effects=[], contact=contact, magnitude=0)
        sim.beat(w, "action", "".join(lines))
    elif kind == "thing":
        t = w.things[ref]
        reach = t["holder"] == "player" or t["host"] in (None, "player") or allows_contact(w, t["host"], "examine")
        noticed = mind.noticeable(w, p, t, contact=reach, events=events)
        sim.beat(w, "action", observe_line(w, ref, noticed) if noticed else "你看不出什麼名堂。")
    else:
        lines = []
        for t in mind.things_of(w, "player"):
            noticed = mind.noticeable(w, p, t, contact=True, events=events)
            if noticed:
                lines.append(observe_line(w, t["id"], noticed))
        sim.beat(w, "action", "".join(lines) or "你仔細感覺了一下自己的身體，沒覺得哪裡不對。")
    sim.advance(w, 1)


def outward(w, nid: str) -> str:
    from .content import text as T

    n = w.npcs[nid]
    bits = [T.demeanor(w, n)]
    for t in mind.things_of(w, nid, held=False):
        c = CAUSES.get(t.get("cause") or "")
        if c and (n["condition"] == "ill" or n.get("symptom_until", -1) >= w.day):
            bits.append(c["label"])
    return "，".join(b for b in bits if b) + "。"


def observe_line(w, tid: str, noticed: dict) -> str:
    p = w.player
    before = (mind.belief(p, tid) or {}).get("label")
    b = mind.believe_thing(w, "player", tid, noticed, "self")
    desc = mind.describe(b["noticed"], mind.mind(p)["domains"])
    t = w.things[tid]
    if t.get("label_self") and t.get("holder") == "player":
        p["focus_thing"] = tid
        return f"你把它拿在手裡端詳：{desc}。這是你自己帶來的東西（照你的說法：「{t['label_self']}」）。"
    if b["concept"]:
        line = f"你察覺到{desc}。依你的見識，這像是{b['label']}。"
    else:
        line = f"你察覺到{desc}。你說不上來這是什麼。"
    if before and before != b["label"]:
        line += f"——跟你原本以為的「{before}」不太一樣。"
    p["focus_thing"] = tid
    return line


# ---------------------------------------------------------------- 作用（下手、醫治、動手）
def capability(w, it: dict) -> dict:
    """玩家這一次「實際上」用得出來的能力。玩家以為的不算——只看世界裁定過的能力、技能與手上的東西。"""
    p = w.player
    mod = it.get("modality") or ("care" if it["verb"] == "treat" else "blunt")
    abilities = p.get("abilities", [])
    tools = {m: (t, mag) for t in mind.things_of(w, "player", held=True) for m, mag in t["tool"].items()}
    chosen = None
    means = it.get("means") or ""
    if means.startswith("a:"):
        chosen = next((a for a in abilities if a["id"] == means[2:]), None)
    if means.startswith("i:") and means[2:] in w.things:
        t = w.things[means[2:]]
        if t["tool"]:
            m, mag = next(iter(t["tool"].items()))
            skill = next((a for a in abilities if a["modality"] == m), None)
            return {"modality": m, "magnitude": mag + (1 if skill else 0), "precision": skill["precision"] if skill else 3,
                    "reliability": 95, "cost": 0, "label": "手上的東西", "tool": t["id"]}
    if not chosen:
        usable = [a for a in abilities if a["modality"] == mod and (not a.get("needs_tool") or a["needs_tool"] in tools)]
        chosen = max(usable, key=lambda a: (a["magnitude"] * 2 + a["precision"]), default=None)
    if chosen:
        return {**chosen, "modality": chosen["modality"]}
    from .player import prowess

    return {"modality": mod, "magnitude": 1 + (prowess(w) / 4 if mod == "blunt" else 0), "precision": 2,
            "reliability": 95, "cost": 0, "label": "徒手", "improvised": True}


def apply(w, it, kind, ref):
    p = w.player
    cap = capability(w, it)
    mod = cap["modality"]
    host = ref if kind == "person" else (w.things[ref]["host"] if kind == "thing" else None)
    if host == "player":
        host = None
    contact = True
    if host:
        contact = allows_contact(w, host, it["verb"]) or it["verb"] == "strike"
        if not contact and it["purpose"] != "harm":
            sim.beat(w, "action", f"{w.name(host) if host in p['met'] else '對方'}一把推開你：「你要做什麼？」")
            record(w, it["verb"], host, None, mod, effects=["refused"], contact=False, magnitude=0)
            return sim.advance(w, 1)
    if kind == "person" and it["verb"] == "strike" and mod == "blunt":
        return strike(w, host, cap)
    if cap.get("cost"):
        w.hurt("player", cap["cost"])
    if not w.roll(cap.get("reliability", 90)):
        sim.beat(w, "action", "你凝神想照著自己記得的方式做，卻怎麼也使不出來。")
        record(w, it["verb"], host, ref if kind == "thing" else None, None, effects=["nothing"], contact=contact,
               magnitude=0)     # 什麼也沒使出來：旁人感覺不到任何作用
        return sim.advance(w, 1)
    if kind == "thing":
        out = hit_thing(w, w.things[ref], mod, cap["magnitude"], cap["precision"], contact)
    else:
        out = act_on_body(w, host or "player", mod, cap["magnitude"], cap["precision"], it["verb"])
    fid = record(w, it["verb"], host, ref if kind == "thing" else None, mod, effects=out["effects"], contact=contact,
                 magnitude=cap["magnitude"], truth_data=out)
    sim.beat(w, "action", player_sees(w, fid, it, cap, ref if kind == "thing" else None, out), fid)
    if host:
        sim.check_death(w, host, fid, "身子受了說不清的重創", attacker="player")
    sim.advance(w, 1)


def hit_thing(w, t: dict, mod: str, mag: float, prec: float, contact: bool) -> dict:
    """作用在一個東西上。只看客觀性質：硬度、會不會共振、脆不脆、蘊藏的能量與爆發性、跟宿主連著什麼。"""
    tr = t["traits"]
    hard = tr.get("hardness", 3)
    eff = mag
    if mod == "vibration":
        eff *= (1 + prec / 5) if tr.get("resonant") else 0.4
    elif mod in ("blunt", "qi"):
        eff *= 0.5 if t["internal"] else 1.0
        if mod == "qi" and tr.get("energy"):
            eff *= 1.4
    elif mod == "cut":
        eff *= 0.5 if t["internal"] else 1.2
    elif mod in ("heat", "cold"):
        eff *= 0.7
    elif mod == "chemical":
        eff *= 1.3 if tr.get("form") == "lesion" else 0.2
    else:      # care、craft 不是拿來破壞東西的
        eff *= 0.1
    dmg = eff * 12 - hard * 6 + w.rng.uniform(-8, 8)
    if dmg > 0 and t["brittle"]:
        dmg *= 1.6
    dmg = max(0.0, min(100.0, dmg))
    out = {"damage": round(dmg), "effects": [], "host_hurt": 0, "actor_hurt": 0, "events": ["vibrated"] if mod == "vibration" else []}
    host = t["host"]
    if dmg <= 0:
        out["effects"].append("nothing")
    else:
        t["integrity"] = max(0, t["integrity"] - round(dmg))
        out["effects"].append("thing_shattered" if t["integrity"] <= 0 else "thing_cracked")
    if host and t["internal"] and mod in PHYSICAL:
        # 隔著身體下手，力道多少會傷到宿主；手法越精準，傷得越少
        coll = round(mag * max(0, 10 - prec) * (0.4 if mod == "vibration" else 0.9))
        out["host_hurt"] += coll
    if dmg > 0 and tr.get("energy") and t["volatile"]:
        # 蘊藏能量的東西受損，能量會往外洩
        release = tr["energy"] * t["volatile"] * dmg / 100 * 1.2
        out["host_hurt"] += round(release * 1.5)
        out["actor_hurt"] += round(release * 0.5) if contact else 0
        out["effects"].append("heat_wave")
        out["events"].append("released")
    if dmg > 0 and t["vital"] == "power":
        out["effects"].append("power_loss")
    if dmg > 0 and t["vital"] == "life":
        out["host_hurt"] += round(dmg * 0.4)
    if t["integrity"] <= 0:
        t["active"] = False
        if t.get("cause") and host:
            out["effects"].append("relief")
            n = w.npcs.get(host)
            if n:
                n["symptom_until"] = -1
                if t["cause"] in ("fever",):
                    n["ill_days"] = 0
    if host:
        if out["host_hurt"]:
            w.hurt(host, out["host_hurt"])
            out["effects"].append("pain")
            if host in w.npcs and w.npcs[host]["condition"] == "healthy":
                w.npcs[host]["condition"] = "injured"
            if w.ent(host)["health"] < 25:
                out["effects"].append("collapse")
    if out["actor_hurt"]:
        w.hurt("player", out["actor_hurt"])
    return out


def act_on_body(w, who: str, mod: str, mag: float, prec: float, verb: str) -> dict:
    """直接作用在人身上（沒有指定體內哪個東西）。醫治會幫上忙；其他方式會傷人。"""
    e = w.ent(who)
    out = {"effects": [], "host_hurt": 0, "actor_hurt": 0, "events": ["vibrated"] if mod == "vibration" else []}
    if mod in ("care", "chemical") and verb == "treat":
        sick = who != "player" and (e["condition"] != "healthy" or e["health"] < 90)
        if not sick:
            out["effects"].append("nothing")
            return out
        heal = round(mag * (1 + prec / 5) * 2)
        w.heal(who, heal)
        if who in w.npcs:
            w.npcs[who]["doctored"] = True
            if mod == "chemical":
                w.npcs[who]["medicine_days"] += 1
            for t in mind.things_of(w, who, held=False):
                if t.get("cause") == "fever" and mod == "chemical":
                    t["integrity"] = max(0, t["integrity"] - round(mag * 15))
                    if t["integrity"] <= 0:
                        t["active"] = False
                        w.npcs[who]["ill_days"] = 0
        out["effects"].append("relief")
        return out
    hurt = round(mag * (2 if mod in PHYSICAL else 0.5) + w.rng.uniform(0, 4))
    if hurt:
        w.hurt(who, hurt)
        out["host_hurt"] = hurt
        out["effects"].append("pain")
        if e["health"] < 25:
            out["effects"].append("collapse")
    else:
        out["effects"].append("nothing")
    return out


def strike(w, nid: str, cap: dict):
    """揍人交給原本的打架規則（有目擊、會報官、會記恨）；天賦給的蠻力另外算，而且有代價。"""
    from . import behaviors

    fid, winner = behaviors.resolve_fight(w, "player", nid, w.player["location"], "")
    extra = 0
    if not cap.get("improvised") and cap.get("magnitude", 0) > 5:
        if cap.get("cost"):
            w.hurt("player", cap["cost"])
        if w.roll(cap.get("reliability", 90)):
            extra = round((cap["magnitude"] - 5) * 6)
            w.hurt(nid, extra)
    who = w.name(nid) if nid in w.player["met"] else "對方"
    if winner == "player":
        sim.beat(w, "action", f"你一拳揮了出去，{who}被打得踉蹌倒退。" + ("這一拳的力道連你自己都吃了一驚。" if extra else ""), fid)
    else:
        sim.beat(w, "action", f"你衝上去動手，卻被{who}擋了下來，反挨了幾下。", fid)
    sim.check_death(w, nid, fid, "被人打成重傷", attacker="player")
    sim.advance(w, 1)


# ---------------------------------------------------------------- 記錄真實＋分發各人的版本
def record(w, verb, host, tid, mod, effects, contact, magnitude, truth_data=None) -> str:
    p = w.player
    loc = p["location"]
    harmful = any(e in ("pain", "collapse", "power_loss", "thing_cracked", "thing_shattered", "bleed") for e in effects) \
        and host is not None
    watchers = [x for x in sim.witnesses_at(w, loc, exclude=("player", host), notice_pct=60 if verb != "examine" else 30)
                if x != "player"]
    fid = w.add_fact("act", {"actor": "player", **({"target": host} if host else {})}, place=loc,
                     data={"verb": verb, "modality": mod, "thing": tid, "effects": list(effects),
                           "truth": truth_data or {}},
                     secrecy="public" if watchers else "private", importance=4 if harmful else 1)
    ev = {"actor": "player", "host": host, "thing": tid, "verb": verb, "modality": mod, "effects": list(effects),
          "contact": contact, "magnitude": magnitude}
    for who in ["player"] + ([host] if host else []) + watchers:
        if who != "player" and (who not in w.npcs or w.npcs[who]["status"] == "dead"):
            continue
        w.learn(who, fid, "self" if who in ("player", host) else "witness", view=views.perceive(w, who, ev))
    if verb != "examine":
        p["deeds"].append(fid)
    return fid


def player_sees(w, fid, it, cap, tid, out) -> str:
    """玩家這一回合看到的：只來自玩家自己的版本與感官，不會把真相塞進玩家的腦中。"""
    p = w.player
    v = p["knows"][fid]["view"]
    host = v.get("host")
    hname = (w.name(host) if host in p["met"] else "對方") if host else "你自己"
    how = "徒手" if cap.get("improvised") else (cap.get("phrase") or f"用你的{cap.get('label') or '本事'}")
    lines = []
    b = mind.belief(p, tid) if tid else None
    before = b["label"] if b else None
    if tid:
        lines.append(f"你{how}，對準{hname}{'體內' if w.things[tid]['internal'] else ''}的{before or '那東西'}。")
    else:
        lines.append(f"你{how}，{'替' + hname + '施治' if it['verb'] == 'treat' else '對' + hname + '下手'}。")
    eff = set(v["effects"])
    if "nothing" in eff:
        lines.append("可是什麼也沒發生。")
    if "thing_cracked" in eff:
        lines.append("你感覺到那東西在你手下微微一顫，裂開了。")
    if "thing_shattered" in eff:
        lines.append("那東西在你手下碎開了。")
    if "heat_wave" in eff:
        lines.append("一股說不出的熱浪猛地從裡面衝了出來，你被震得手掌發麻。")
    if "pain" in eff:
        lines.append(f"{hname}痛得臉都白了。")
    if "collapse" in eff:
        lines.append(f"{hname}整個人軟倒下去。")
    if "relief" in eff:
        lines.append(f"{hname}長長吐了口氣，臉色好看了些。")
    if tid and b:
        # 這次作用帶來的新證據（例如被震動時才聽得出的共鳴、炸開的熱浪），讓玩家重新理解那個東西
        t = w.things[tid]
        noticed = mind.noticeable(w, p, t, contact=True, events=out.get("events", ()))
        if "released" in out.get("events", ()):
            noticed["energy"] = t["traits"].get("energy", 0)
        nb = mind.believe_thing(w, "player", tid, noticed, "self")
        if nb["label"] != before:
            lines.append(f"你愣住了：這東西，恐怕不是你以為的{before}。")
    return "".join(lines)
