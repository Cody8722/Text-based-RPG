"""NPC 自主行為庫（白盒權重表）。

每個時辰，每個在鎮上的 NPC 有一定機率「做點什麼」。候選行為各自有：
  weight(w, n) -> float   這個人此刻有多想做這件事（性格 × 處境 × 地點）
  run(w, n)               規則決定結果、產生事實、改變世界
LLM 完全不參與這一層。
"""

from __future__ import annotations

from . import sim
from .content.locations import LOCATIONS, NIGHT_PERIODS

ACT_CHANCE = 0.33


def maybe_act(w, nid):
    n = w.npcs[nid]
    chance = ACT_CHANCE + n["stress"] / 400
    if w.rng.random() >= chance:
        return
    choice = w.pick_weighted([(b, fn_w(w, n)) for b, (fn_w, _) in BEHAVIORS.items()])
    if choice:
        BEHAVIORS[choice][1](w, n)


def others_here(w, n, include_player=False):
    out = [i for i in w.present_npcs(n["location"]) if i != n["id"] and not w.npcs[i].get("bedridden")]
    return out


def tr(n, k):
    return n["traits"][k]


# ---------------- 聊八卦（傳聞的引擎） ----------------
def w_gossip(w, n):
    if not others_here(w, n):
        return 0
    social = LOCATIONS.get(n["location"], {}).get("social")
    return tr(n, "gossip") * (1.6 if social else 0.5)


def shareable(w, teller: str, listener: str, topic: str | None = None) -> list[tuple[str, float]]:
    """teller 願意告訴 listener 的事實，附權重。隱私規則全在這裡：
    - 牽涉自己犯錯的事不說（除非是傳聞版本、而且主角不是自己）
    - secret 只對很信任的人說，或嘴碎又不老實的人才會漏
    - private 要有點交情
    """
    t = w.npcs[teller]
    trust = w.opinion(teller, listener)
    out = []
    lis = w.ent(listener)
    for fid, info in t["knows"].items():
        f = w.facts.get(fid)
        if not f or fid in lis["knows"] or f["type"] in ("need",) and f["roles"].get("who") != teller and trust < 30:
            continue
        if f["type"] == "need" and f["roles"].get("who") == teller:
            continue  # 自己的難處不會拿來閒聊，要問才說
        culprit = w.culprit_of(f)
        if culprit == teller or f["roles"].get("borrower") == teller or f["roles"].get("lover") == teller:
            continue
        if listener in f["roles"].values() and f["type"] not in ("help_money", "debt_paid_by"):
            continue
        if topic and topic not in f["roles"].values():
            continue
        sec = f["secrecy"]
        if sec == "secret":
            if not (trust >= 60 or (tr(t, "gossip") >= 7 and tr(t, "honesty") <= 4)):
                continue
        elif sec == "private":
            if trust < 15 and tr(t, "gossip") < 7:
                continue
        # 誰的事：講自己喜歡的人的壞話比較少
        if culprit and w.opinion(teller, culprit) >= 50:
            continue
        age = w.day - f["day"]
        weight = f["importance"] ** 2 + max(0, 5 - age) * 0.6 + (2 if info["src"] == "witness" else 0)
        if f["importance"] <= 1:
            weight *= 0.3
        out.append((fid, weight))
    return out


def tell(w, teller: str, listener: str, fid: str) -> str:
    """teller 把 fid 告訴 listener；嘴不牢又不老實的人可能把主角換成自己討厭的人。回傳實際傳出去的 fid。"""
    f = w.facts[fid]
    t = w.npcs[teller]
    culprit = w.culprit_of(f)
    if culprit and f["type"] in ("theft", "fight", "debt_beating", "caught_stealing", "theft_report") and \
            w.roll((10 - tr(t, "honesty")) * 4, lo=0, hi=60):
        disliked = [(o, -v) for o, v in t["opinions"].items() if v <= -25 and o in w.npcs and o != culprit
                    and w.npcs[o]["status"] in ("normal", "jailed")]
        if disliked:
            scapegoat = max(disliked, key=lambda kv: kv[1])[0]
            roles = dict(f["roles"])
            for k in ("thief", "attacker", "culprit"):
                if k in roles:
                    roles[k] = scapegoat
            rid = w.add_fact(f["type"], roles, place=f["place"], data=f["data"], secrecy=f["secrecy"],
                             importance=f["importance"], truth=False, rumor_of=w.root_fact(fid)["id"], log=False)
            w.bump("rumor_distorted")
            w.learn(listener, rid, teller)
            return rid
    if f["type"] == "theft_report" and w.roll(tr(t, "gossip") * 3 + (10 - tr(t, "honesty")) * 3, lo=0, hi=60):
        suspect = usual_suspect(w, teller, f)
        if suspect:
            # 街坊揣測：「八成是某某幹的」——這是一條新的、真假未定的指控
            crime = f["data"].get("crime")
            true_thief = w.facts[crime]["roles"].get("thief") if crime in w.facts else None
            aid = w.add_fact("accusation", {"accuser": teller, "accused": suspect, "victim": f["roles"]["victim"]},
                             place=f["place"], data={"crime": crime, "speculation": True}, secrecy="public",
                             importance=3, truth=(suspect == true_thief), causes=[fid], log=False)
            w.bump("speculation")
            w.learn(listener, fid, teller)
            w.learn(listener, aid, teller)
            t["knows"].setdefault(aid, {"day": w.day, "src": "self"})
            return aid
    w.learn(listener, fid, teller)
    return fid


def usual_suspect(w, teller: str, report: dict) -> str | None:
    """丟了錢，大家會先懷疑誰：自己討厭的人，或是聽說手腳不乾淨的人。"""
    t = w.npcs[teller]
    victim = report["roles"].get("victim")
    cands = {}
    for o, v in t["opinions"].items():
        if v <= -20 and o in w.npcs and w.npcs[o]["status"] in ("normal", "jailed") and o != victim:
            cands[o] = cands.get(o, 0) + (-v) / 10
    for fid in t["knows"]:
        f = w.facts.get(fid)
        if f and f["type"] in ("caught_stealing", "petty_theft_past", "theft", "accusation"):
            c = f["roles"].get("thief") or f["roles"].get("who") or f["roles"].get("accused")
            if c in w.npcs and c != teller and c != victim and w.npcs[c]["status"] in ("normal", "jailed"):
                cands[c] = cands.get(c, 0) + 4
    cands.pop(teller, None)
    return w.pick_weighted(list(cands.items())) if cands else None


def r_gossip(w, n):
    listeners = others_here(w, n)
    listener = w.rng.choice(listeners)
    opts = shareable(w, n["id"], listener)
    fid = w.pick_weighted(opts)
    if not fid:
        return
    shared = tell(w, n["id"], listener, fid)
    w.adjust_opinion(listener, n["id"], 1)
    w.bump("gossip")
    # 玩家在旁邊：有機會聽到一耳朵
    if sim.player_here(w, n["location"]) and w.rng.random() < 0.3:
        if w.learn("player", shared, n["id"]):
            from .content import text as T

            sim.beat(w, "overheard", f"你聽見{w.name(n['id'])}壓低聲音對{w.name(listener)}說：「{T.fact_text(w, w.facts[shared], speaker=n['id'], listener=listener)}」", shared)


# ---------------- 揣測：還沒破的竊案，大家聊著聊著就有了「嫌犯」 ----------------
def open_reports(w, n):
    out = []
    for fid in n["knows"]:
        f = w.facts.get(fid)
        if not f or f["type"] != "theft_report" or w.day - f["day"] > 6:
            continue
        crime = f["data"].get("crime")
        case = next((c for c in w.cases.values() if c["crime"] == crime), None)
        if case and case["status"] not in ("open", "pending_arrest"):
            continue
        if fid in n.get("speculated", []):
            continue
        out.append(fid)
    return out


def w_speculate(w, n):
    if not LOCATIONS.get(n["location"], {}).get("social") or not others_here(w, n):
        return 0
    if not open_reports(w, n):
        return 0
    return (tr(n, "gossip") + (10 - tr(n, "honesty"))) / 10


def r_speculate(w, n):
    rid = w.rng.choice(open_reports(w, n))
    n.setdefault("speculated", []).append(rid)
    f = w.facts[rid]
    suspect = usual_suspect(w, n["id"], f)
    if not suspect:
        return
    crime = f["data"].get("crime")
    true_thief = w.facts[crime]["roles"].get("thief") if crime in w.facts else None
    aid = w.add_fact("accusation", {"accuser": n["id"], "accused": suspect, "victim": f["roles"]["victim"]},
                     place=n["location"], data={"crime": crime, "speculation": True}, secrecy="public",
                     importance=3, truth=(suspect == true_thief), causes=[rid], log=False)
    n["knows"].setdefault(aid, {"day": w.day, "src": "self"})
    w.bump("speculation")
    for o in others_here(w, n)[:1]:
        w.learn(o, aid, n["id"])
    if sim.player_here(w, n["location"]) and w.rng.random() < 0.5:
        if w.learn("player", aid, n["id"]):
            from .content import text as T

            sim.beat(w, "overheard", f"{w.name(n['id'])}拍著桌子說：「{T.fact_text(w, w.facts[aid], speaker=n['id'], listener='others')}」", aid)


# ---------------- 喝酒 ----------------
def w_drink(w, n):
    if w.period not in (3, 4, 5) or n["money"] < 6 or n["id"] == w.properties["tavern"]["owner"]:
        return 0
    return 1 + n["stress"] / 25 + tr(n, "vice") / 3


def r_drink(w, n):
    n["location"] = "tavern"
    owner = w.properties["tavern"]["owner"]
    cost = w.rng.randint(3, 6)
    if w.free(owner):
        w.transfer(n["id"], owner, cost)
    else:
        w.add_money(n["id"], -cost)
    w.stress(n["id"], -12)
    n["drunk_until"] = w.clock + 3


# ---------------- 賭 ----------------
def w_gamble(w, n):
    if w.period not in (3, 4, 5) or n["money"] < 8 or n["id"] == "qian":
        return 0
    return tr(n, "vice") ** 1.4 / 4 * (1 + n["stress"] / 80)


def r_gamble(w, n):
    n["location"] = "den"
    bet = min(n["money"], w.rng.randint(1, 4) * 10)
    if w.roll(42):
        win = w.transfer("qian", n["id"], bet) if w.free("qian") else w.add_money(n["id"], bet)
        if win >= 30:
            fid = w.add_fact("gamble_win", {"who": n["id"]}, place="den", data={"amount": win}, secrecy="private",
                             importance=1, known_by=[n["id"]], witnesses=sim.witnesses_at(w, "den", exclude=(n["id"],), notice_pct=50))
            sim.emit(w, fid, "den")
    else:
        lost = w.transfer(n["id"], "qian", bet) if w.free("qian") else -w.add_money(n["id"], -bet)
        w.stress(n["id"], 6)
        if lost >= 20:
            fid = w.add_fact("gamble_loss", {"who": n["id"]}, place="den", data={"amount": lost}, secrecy="private",
                             importance=2, known_by=[n["id"]], witnesses=sim.witnesses_at(w, "den", exclude=(n["id"],), notice_pct=50))
            n.setdefault("losses", []).append(fid)
            sim.emit(w, fid, "den")


# ---------------- 借錢 ----------------
def w_borrow(w, n):
    nd = sim.unmet_need(n)
    if not nd or n.get("borrowed_day") == w.day:
        return 0
    return 6 + n["stress"] / 10


def find_lender(w, n, amount):
    best = []
    for lid, l in w.npcs.items():
        if lid == n["id"] or l["status"] != "normal" or lid == "qian" or l.get("bedridden") or lid in n.get("family", []):
            continue
        if w.opinion(n["id"], lid) >= 25 and w.opinion(lid, n["id"]) >= 35 and l["money"] >= amount + 30 and tr(l, "kind") >= 5:
            best.append((lid, w.opinion(lid, n["id"]) + tr(l, "kind") * 5))
    if w.free("su") and n["id"] != "su" and amount <= 60 and w.opinion("su", n["id"]) >= 0 and w.money("su") >= amount + 40:
        best.append(("su", 40))
    return w.pick_weighted(best)


def r_borrow(w, n):
    nd = sim.unmet_need(n)
    amount = max(10, ((nd["amount"] - n["money"]) // 10 + 1) * 10)
    n["borrowed_day"] = w.day
    causes = [n.get("need_fact", {}).get(f"need:{nd['type']}")] + n.get("losses", [])[-1:]
    lender = find_lender(w, n, amount)
    if lender and w.roll(tr(w.npcs[lender], "kind") * 8 + w.opinion(lender, n["id"]) / 2):
        interest = 10 if lender == "su" else 0
        days = w.rng.randint(6, 10)
        place = n["location"]
    else:
        owns = any(p["owner"] == n["id"] for p in w.properties.values())
        # 錢三爺只借給還得起的人：有收入或有產業可以抵
        cap = (n["income"] + n.get("wage", 0)) * 10 + (200 if owns else 0)
        if not w.free("qian") or w.opinion("qian", n["id"]) < -40 or w.money("qian") < amount or amount > cap:
            w.stress(n["id"], 8)
            return
        lender, interest, days, place = "qian", 30, w.rng.randint(3, 5), "den"
        n["location"] = "den"
    w.transfer(lender, n["id"], amount)
    secured = None
    if lender == "qian" and amount >= 80:
        props = [pid for pid, p in w.properties.items() if p["owner"] == n["id"]]
        secured = props[0] if props else None
    fid = w.add_fact("loan", {"lender": lender, "borrower": n["id"]}, place=place,
                     data={"amount": amount, "due": w.day + days, **({"secured": w.properties[secured]["name"]} if secured else {})},
                     secrecy="private", importance=3, causes=causes,
                     known_by=[n["id"], lender] + (["liu6"] if lender == "qian" else []))
    w.add_loan(lender, n["id"], amount, days, interest, secured=secured, cause=causes[0], fact_id=fid)
    if lender != "qian":
        w.adjust_opinion(n["id"], lender, 15)
    sim.emit(w, fid, place)


# ---------------- 買藥／看大夫 ----------------
def w_medicine(w, n):
    nd = next((x for x in n.get("needs", []) if x["type"] == "medicine"), None)
    if not nd or n["money"] < nd["amount"] or not w.free("bai") or w.period in NIGHT_PERIODS:
        return 0
    if nd["for"] != n["id"] and w.medicine_stock <= 0:
        return 0
    return 14


def r_medicine(w, n):
    nd = next((x for x in n.get("needs", []) if x["type"] == "medicine"), None)
    n["location"] = "pharmacy"
    patient = nd["for"]
    if patient == n["id"]:
        w.transfer(n["id"], "bai", sim.DOCTOR_FEE)
        w.heal(n["id"], 15)
        n["doctored"] = True
        if n["condition"] == "ill":
            n["medicine_days"] += 2
    else:
        w.transfer(n["id"], "bai", sim.MEDICINE_PRICE)
        w.medicine_stock -= 1
        w.npcs[patient]["medicine_days"] += 3
        fid = w.add_fact("medicine", {"giver": n["id"], "receiver": patient}, place="pharmacy", secrecy="private",
                         importance=2, known_by=[n["id"], patient, "bai"], causes=[n.get("need_fact", {}).get("need:medicine")])
        sim.emit(w, fid, "pharmacy")
    n["needs"] = [x for x in n["needs"] if x is not nd]
    w.stress(n["id"], -10)


# ---------------- 偷 ----------------
def w_steal(w, n):
    h = tr(n, "honesty")
    nd = sim.unmet_need(n)
    desperate = nd is not None or n["money"] < 5 or n.get("hungry_days", 0) >= 2
    if h >= 7 or not desperate:
        return 0
    if h >= 5 and n["stress"] < 85:
        return 0
    night = 2 if w.period in NIGHT_PERIODS else 0.6
    return (7 - h) * 1.3 * night * (1 + n["stress"] / 100)


def steal_targets(w, n):
    out = []
    for pid, p in w.properties.items():
        owner = p["owner"]
        if owner == n["id"] or owner not in w.npcs or w.npcs[owner]["status"] == "dead":
            continue
        if w.money(owner) >= 25 and w.opinion(n["id"], owner) < 40:
            weight = min(6, w.money(owner) / 50) + (3 if w.opinion(n["id"], owner) < 0 else 0)
            if p["place"] == "den":
                if tr(n, "courage") < 6:
                    continue   # 沒膽子的人不敢動錢三爺的錢
                weight /= 3
            out.append((p["place"], owner, weight))
    if w.money("player") >= 25 and w.player["location"] == n["location"] and w.opinion(n["id"], "player") < 30:
        out.append((n["location"], "player", 3))
    return out


def r_steal(w, n):
    choice = w.pick_weighted([((pl, ow), wt) for pl, ow, wt in steal_targets(w, n)])
    if not choice:
        return
    place, victim = choice
    n["location"] = place
    owner_here = victim == "player" or (w.free(victim) and w.npcs[victim]["location"] == place)
    alert = 30 if owner_here and w.period != 5 else 0
    if place == "den":
        alert += 25   # 賭坊裡總有幾雙眼睛盯著錢
    success = w.roll(60 - alert + (5 - tr(n, "honesty")) * 2)
    amount = max(5, int(w.money(victim) * w.rng.uniform(0.12, 0.3)))
    amount = min(amount, 90)
    if success:
        got = w.transfer(victim, n["id"], amount)
        watchers = sim.witnesses_at(w, place, exclude=(n["id"], victim), notice_pct=18)
        fid = w.add_fact("theft", {"thief": n["id"], "victim": victim}, place=place, data={"amount": got},
                         secrecy="secret", importance=4, causes=[n.get("need_fact", {}).get("need:debt")] + n.get("losses", [])[-1:],
                         known_by=[n["id"]], witnesses=watchers)
        w.flags.setdefault("_undiscovered", []).append(fid)
        w.bump("thefts")
        if "player" in watchers:
            w.pending = {"kind": "theft_seen", "thief": n["id"], "victim": victim, "place": place, "fact": fid}
            sim.emit(w, fid, place)
    else:
        watchers = sim.witnesses_at(w, place, exclude=(n["id"],))
        if victim == "player":
            watchers = list(set(watchers) | {"player"})
        fid = w.add_fact("caught_stealing", {"thief": n["id"], "victim": victim}, place=place, importance=4,
                         known_by=[n["id"]] + ([victim] if victim != "player" else []), witnesses=watchers)
        w.stress(n["id"], 25)
        if victim != "player":
            w.adjust_opinion(victim, n["id"], -40)
            w.npcs[victim].setdefault("to_report", []).append(fid)
        w.flags.setdefault("_town_news", []).append(fid)
        sim.emit(w, fid, place)


# ---------------- 接濟 ----------------
def w_help(w, n):
    if tr(n, "kind") < 5 or w.day - n.get("last_help_day", -99) < 5:
        return 0
    best = 0
    for fid in n["knows"]:
        f = w.facts.get(fid)
        if not f or f["type"] != "need" or f["day"] < w.day - 3:
            continue
        who = f["roles"].get("who")
        if who == n["id"] or not w.free(who) or w.day - w.npcs[who].get("helped_day", -99) < 4:
            continue
        op = w.opinion(n["id"], who)
        if op >= 35 and n["money"] >= 50:
            best = max(best, (tr(n, "kind") - 3) * op / 80)
    return best


def r_help(w, n):
    cands = []
    for fid in n["knows"]:
        f = w.facts.get(fid)
        if f and f["type"] == "need" and f["day"] >= w.day - 3:
            who = f["roles"].get("who")
            if who != n["id"] and w.free(who) and w.opinion(n["id"], who) >= 35:
                cands.append((fid, w.opinion(n["id"], who)))
    fid = w.pick_weighted(cands)
    if not fid:
        return
    need = w.facts[fid]
    who = need["roles"]["who"]
    amount = min(n["money"] - 20, 30 if need["data"].get("need") == "medicine" else 25)
    if amount < 10:
        return
    got = w.transfer(n["id"], who, amount)
    n["last_help_day"] = w.day
    w.npcs[who]["helped_day"] = w.day
    proud = tr(n, "pride") >= 8 or n.get("patron_of")
    if proud:
        hid = w.add_fact("help_money", {"giver": n["id"], "receiver": who}, data={"amount": got}, secrecy="secret",
                         importance=3, causes=[fid], known_by=[n["id"]])
        w.add_fact("found_purse", {"who": who}, data={"amount": got}, secrecy="private", importance=2,
                   causes=[hid], known_by=[who], log=False)
    else:
        hid = w.add_fact("help_money", {"giver": n["id"], "receiver": who}, place=w.npcs[who]["location"],
                         data={"amount": got}, secrecy="private", importance=3, causes=[fid], known_by=[n["id"], who])
        sim.emit(w, hid, w.npcs[who]["location"])
    w.stress(who, -15)
    w.bump("help")


# ---------------- 動手（恩怨、報仇、醉酒） ----------------
def fight_target(w, n):
    """動手要有私人恩怨（自己或親近的人吃過虧）；光是看不順眼，最多吵兩句。已經帶傷的人不會再被圍毆。"""
    best, bw = None, 0
    for o in others_here(w, n):
        grudge = n["blame"].get(o, 0)
        if grudge <= 0 and not (n.get("drunk_until", -1) >= w.clock and w.opinion(n["id"], o) <= -70):
            continue
        if w.npcs[o]["health"] < 60:
            continue
        score = grudge + max(0, -w.opinion(n["id"], o) - 60) * 0.5
        if score > bw:
            best, bw = o, score
    return best, bw


def w_fight(w, n):
    if tr(n, "temper") < 6 and not n["blame"]:
        return 0
    if w.day - n.get("last_fight_day", -99) < 4:
        return 0
    target, score = fight_target(w, n)
    if not target or score < 22:
        return 0
    drunk = 2 if n.get("drunk_until", -1) >= w.clock else 1
    # 打不過的人不會主動找打
    confidence = strength(w, n["id"]) / max(1.0, strength(w, target))
    if confidence < 0.75:
        return 0
    return (tr(n, "temper") - 4) * score / 30 * drunk * (0.5 + tr(n, "courage") / 10) * min(1.3, confidence)


def strength(w, ref):
    if ref == "player":
        from .player import prowess

        return prowess(w) * 1.2 + w.player["health"] / 25
    n = w.npcs[ref]
    base = tr(n, "courage") * 0.6 + tr(n, "temper") * 0.3 + n["health"] / 25
    return base + {"tie": 6, "aniu": 5, "shitou": 4, "liu6": 2, "zhao": 4}.get(ref, 0)


def r_fight(w, n):
    target, _ = fight_target(w, n)
    if not target:
        return
    loc = n["location"]
    reason = "報仇" if n["blame"].get(target, 0) >= 50 else ""
    if sim.player_here(w, loc):
        sim.open_pending_beating(w, n["id"], target, loc, None, mode="fight", reason=reason)
        return
    resolve_fight(w, n["id"], target, loc, reason)


def resolve_fight(w, a, b, loc, reason="", extra_witness=()):
    sa, sb = strength(w, a) + w.rng.uniform(0, 6), strength(w, b) + w.rng.uniform(0, 6)
    winner, loser = (a, b) if sa >= sb else (b, a)
    for x in (a, b):
        if x != "player":
            w.npcs[x]["last_fight_day"] = w.day
    # 打架通常不出人命；只有血仇（至親死在對方手上）才可能下死手
    blood = loser != "player" and winner != "player" and w.npcs[winner]["blame"].get(loser, 0) >= 120
    dmg = w.rng.randint(10, 25)
    if blood and w.roll(25):
        w.hurt(loser, dmg + 40)
    else:
        e = w.ent(loser)
        e["health"] = max(5, e["health"] - dmg)
    if loser != "player":
        w.npcs[loser]["condition"] = "injured"
    w.hurt(winner, w.rng.randint(0, 10))
    roles = {"attacker": a, "victim": b}
    cause = w.npcs[a].get("blame_src", {}).get(b) if a != "player" else None
    fid = w.add_fact("fight", roles, place=loc, data={"reason": reason, "winner": winner}, importance=3,
                     causes=[cause] if cause else [],
                     known_by=[x for x in (a, b) if x != "player"],
                     witnesses=list(sim.witnesses_at(w, loc, exclude=(a, b))) + list(extra_witness))
    for x in (a, b):
        if x != "player":
            w.stress(x, 10)
    if b != "player":
        w.adjust_opinion(b, a, -30)
        w.npcs[b].setdefault("to_report", []).append(fid)
    if a != "player":
        w.npcs[a]["blame"].pop(b, None)
        w.adjust_opinion(a, b, 12)   # 出了這口氣，火就消了一些
    w.bump("fights")
    if loser != "player":
        sim.check_death(w, loser, fid, "跟人打架受了重傷", attacker=winner)
    sim.emit(w, fid, loc)
    return fid, winner


# ---------------- 報官 ----------------
def w_report(w, n):
    pend = n.get("to_report") or []
    if not pend or not w.free("zhao") or n["id"] == "zhao":
        return 0
    fid = pend[0]
    f = w.facts.get(fid)
    if not f:
        n["to_report"] = pend[1:]
        return 0
    culprit = w.culprit_of(f)
    fear = 4 if culprit in ("qian", "liu6", w.flags.get("collector2")) and tr(n, "courage") < 6 else 0
    near = 2 if n["location"] in ("yamen", "street", w.npcs["zhao"]["location"]) else 0.6
    return max(0, (tr(n, "honesty") - 3 + n["blame"].get(culprit, 0) / 20 - fear) * near)


def r_report(w, n):
    fid = n["to_report"].pop(0)
    if w.npcs["zhao"]["location"] != n["location"]:
        n["location"] = "yamen" if w.npcs["zhao"]["location"] == "yamen" else w.npcs["zhao"]["location"]
    w.learn("zhao", fid, n["id"])
    w.bump("reports")


# ---------------- 遠走高飛 ----------------
def w_flee(w, n):
    if n["stress"] < 85 or tr(n, "courage") > 6 or n.get("traveler"):
        return 0
    if any(w.npcs[f]["status"] == "normal" for f in w.family_of(n["id"])):
        return 0
    hunted = any(ln["lender"] == "qian" and ln["stage"] >= 2 for ln in w.open_loans(borrower=n["id"]))
    grieving = n.get("grief_until", 0) >= w.day
    if not (hunted or grieving or not n.get("employed", True)):
        return 0
    return 4 + (n["stress"] - 85) / 3


def r_flee(w, n):
    via = "boat" if w.free("laohe") and n["money"] >= 20 and w.period in NIGHT_PERIODS else "gate"
    if via == "boat":
        w.transfer(n["id"], "laohe", 20)
    seen = ["laohe"] if via == "boat" else (["wu"] if w.free("wu") else [])
    n["status"] = "fled"
    n["location"] = None
    fid = w.add_fact("fled", {"who": n["id"]}, place="dock" if via == "boat" else "gate", data={"via": via},
                     importance=4, causes=[ln.get("fact") for ln in w.open_loans(borrower=n["id"])][:2],
                     known_by=seen)
    w.flags.setdefault("_town_news", []).append(fid)
    w.bump("fled")


# ---------------- 主動找玩家（委託藏在對話裡） ----------------
def w_approach(w, n):
    if not sim.player_here(w, n["location"]) or w.opinion(n["id"], "player") < 35:
        return 0
    nd = sim.unmet_need(n)
    if not nd:
        return 0
    fid = n.get("need_fact", {}).get(f"need:{nd['type']}")
    if not fid or fid in w.player["knows"]:
        return 0
    return 12


def r_approach(w, n):
    nd = sim.unmet_need(n)
    fid = n["need_fact"][f"need:{nd['type']}"]
    w.learn("player", fid, n["id"])
    from .content import text as T

    sim.beat(w, "approach", f"{w.name(n['id'])}猶豫了好一會兒，才走到你身邊，壓低聲音說：「我……{T.NEED_TEXT[nd['type']]}……」話沒說完，就別過臉去。", fid)


# ---------------- 失去至親之後 ----------------
def w_grief(w, n):
    if n.get("grief_until", 0) < w.day or n.get("grief_acted"):
        return 0
    return 10


def r_grief(w, n):
    n["grief_acted"] = True
    lost = n.get("grief_for")
    blame = max(n["blame"].items(), key=lambda kv: kv[1]) if n["blame"] else None
    if blame and blame[1] >= 50:
        fid = w.add_fact("revenge_vow", {"who": n["id"], "target": blame[0]}, place=n["location"], importance=3,
                         causes=[n.get("blame_src", {}).get(blame[0])],
                         known_by=[n["id"]], witnesses=sim.witnesses_at(w, n["location"], exclude=(n["id"],)))
        sim.emit(w, fid, n["location"])
        n["traits"]["temper"] = min(10, tr(n, "temper") + 3)
    if n.get("wage_from") and n.get("employed", True) and w.rng.random() < 0.6:
        n["employed"] = False
        fid = w.add_fact("quit_job", {"who": n["id"]}, place=n["work"], data={"place": n["work"]}, importance=2,
                         known_by=[n["id"], n["wage_from"]], witnesses=sim.witnesses_at(w, n["location"], exclude=(n["id"],)))
        sim.emit(w, fid, n["location"])
    if lost:
        w.add_fact("grieving", {"who": n["id"], "lost": lost}, importance=2, known_by=[n["id"]], log=False)


# ---------------- 找活幹 ----------------
def w_work(w, n):
    if n.get("employed", True) and not sim.unmet_need(n):
        return 0
    if w.period in NIGHT_PERIODS or w.period == 0:
        return 0
    return 3 + (4 if not n.get("employed", True) else 0)


def r_work(w, n):
    n["location"] = "dock"
    w.add_money(n["id"], w.rng.randint(5, 11))
    # 失業的人在碼頭賣力氣，偶爾會被雇走
    if not n.get("employed", True) and w.rng.random() < 0.12 and n.get("grief_until", 0) < w.day:
        n["employed"] = True
        n["work"] = "dock"
        n["income"] = 8
        n["schedule"] = [n["home"], "dock", "dock", "tavern", "tavern", n["home"]]


# ---------------- 用錢把人從拘房弄出來 ----------------
def w_bribe(w, n):
    if not w.free("xiaoli"):
        return 0
    for o in w.npcs.values():
        if o["status"] == "jailed" and (o["id"] in w.family_of(n["id"]) or w.opinion(n["id"], o["id"]) >= 60):
            if n["money"] >= 40 and tr(n, "honesty") <= 7:
                return 3
    return 0


def r_bribe(w, n):
    for o in w.npcs.values():
        if o["status"] == "jailed" and (o["id"] in w.family_of(n["id"]) or w.opinion(n["id"], o["id"]) >= 60):
            if w.roll(tr(w.npcs["xiaoli"], "greed") * 9):
                w.transfer(n["id"], "xiaoli", 30)
                o["status"] = "normal"
                o["jail_until"] = 0
                w.add_fact("bribe", {"briber": n["id"], "guard": "xiaoli", "prisoner": o["id"]}, place="yamen",
                           secrecy="secret", importance=3, known_by=[n["id"], "xiaoli", o["id"]])
                w.adjust_opinion(o["id"], n["id"], 30)
            return


BEHAVIORS = {
    "gossip": (w_gossip, r_gossip),
    "speculate": (w_speculate, r_speculate),
    "drink": (w_drink, r_drink),
    "gamble": (w_gamble, r_gamble),
    "borrow": (w_borrow, r_borrow),
    "medicine": (w_medicine, r_medicine),
    "steal": (w_steal, r_steal),
    "help": (w_help, r_help),
    "fight": (w_fight, r_fight),
    "report": (w_report, r_report),
    "flee": (w_flee, r_flee),
    "approach": (w_approach, r_approach),
    "grief": (w_grief, r_grief),
    "work": (w_work, r_work),
    "bribe": (w_bribe, r_bribe),
    "idle": (lambda w, n: 4.0, lambda w, n: None),
}
