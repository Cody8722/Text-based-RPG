"""玩家：開局、可做的事、做了之後世界怎麼變。

動作清單永遠由伺服器依當下 state 產生，前端只能回傳清單裡的 id——
前端（或任何 LLM）無法憑空發明一個動作，也無法讓顯示文字跟實際行為對不上。
"""

from __future__ import annotations

import math

from . import behaviors, dialogue, sim
from .content import text as T
from .content.locations import LOCATIONS, NIGHT_PERIODS
from .world import TICKS_PER_PERIOD, World

BACKGROUNDS = {
    "scholar": {"name": "落魄書生", "money": 40, "prowess": 3.0,
                "desc": "讀過幾年書，考場失意，盤纏所剩無幾。識字、會寫信，說話客氣，打聽事情比別人順利一些。"},
    "escort": {"name": "退役鏢師", "money": 55, "prowess": 6.5,
               "desc": "走了十年鏢，身上有幾道疤，拳腳比一般人硬。不太會說話，但沒人敢隨便惹你。"},
    "peddler": {"name": "走街貨郎", "money": 75, "prowess": 4.0,
                "desc": "挑著擔子走遍各鄉各鎮，耳朵尖、嘴巴甜，最會在人堆裡聽到不該聽的事。"},
    "herbalist": {"name": "遊方郎中", "money": 45, "prowess": 4.0,
                  "desc": "略懂醫術，背著一個藥箱四處行醫。看得出人的病，藥材在你手裡能多撐幾天。"},
    "heir": {"name": "離家的少爺", "money": 130, "prowess": 3.0,
             "desc": "跟家裡大吵一架之後跑了出來，身上帶著不少錢，卻不太知道一碗麵多少錢。"},
    "drifter": {"name": "流浪漢", "money": 15, "prowess": 5.0,
                "desc": "沒有家，也沒有要去的地方。在哪裡都睡得著，街頭巷尾的人反而跟你比較親。"},
}

COST = {"move": 2, "look": 1, "wait": 2, "talk": 1, "work": 2, "train": 2, "gamble": 1, "drink": 1, "notices": 1, "steal": 1}
INN_PRICE = 12
DRINK_PRICE = 5


def new_player(w: World, background: str | None) -> dict:
    bg = background if background in BACKGROUNDS else "drifter"
    b = BACKGROUNDS[bg]
    return {
        "background": bg,
        "bg_name": b["name"],
        "money": b["money"],
        "health": 100,
        "base_prowess": b["prowess"],
        "prowess_n": 0,
        "location": "gate",
        "knows": {},
        "deeds": [],
        "inventory": {"medicine": 0},
        "talking_to": None,
        "met": [],
        "last_seen": {},
        "lodging_until": 0,
        "jailed_until": 0,
        "hungry_days": 0,
        "chatted": {},
        "asked_self": {},
        "commented": [],
        "turn": 0,
    }


def offer_backgrounds(rng, k: int = 3) -> list[str]:
    keys = list(BACKGROUNDS)
    rng.shuffle(keys)
    return keys[:k]


def prowess(w: World) -> float:
    p = w.player
    base = p["base_prowess"]
    return 10 - (10 - base) * math.exp(-0.25 * p["prowess_n"])


def jailed(w: World) -> bool:
    return w.player.get("jailed_until", 0) >= w.day


def deed(w: World, fid: str):
    w.player["deeds"].append(fid)
    if fid not in w.player["knows"]:
        w.player["knows"][fid] = {"day": w.day, "src": "self"}


# ---------------- 可做的事 ----------------
def act(aid, label, group, hint=None):
    d = {"id": aid, "label": label, "group": group}
    if hint:
        d["hint"] = hint
    return d


def available_actions(w: World) -> list[dict]:
    p = w.player
    if w.pending:
        return pending_actions(w)
    if jailed(w):
        out = [act("jail_wait", "在拘房裡熬過這一天", "here")]
        if w.free("xiaoli") and p["money"] >= 30:
            out.append(act("jail_bribe", "偷偷塞三十文給看守的衙役", "here"))
        return out
    if p.get("talking_to"):
        nid = p["talking_to"]
        if nid in w.npcs and (w.free(nid) and w.npcs[nid]["location"] == p["location"] or
                              w.npcs[nid]["status"] == "jailed" and p["location"] == "yamen"):
            return dialogue.talk_actions(w, nid)
        p["talking_to"] = None
    loc = p["location"]
    out = []
    for nid in w.present_npcs(loc):
        out.append(act(f"talk:{nid}", w.name(nid) if nid in p["met"] else w.npcs[nid]["role"], "people"))
    if loc == "yamen":
        for nid, n in w.npcs.items():
            if n["status"] == "jailed":
                out.append(act(f"talk:{nid}", f"隔著木柵跟{w.name(nid)}說話", "people"))
    for nb in LOCATIONS[loc]["neighbors"]:
        opens = LOCATIONS[nb].get("open")
        if opens and w.period not in opens:
            out.append(act(f"move:{nb}", f"{LOCATIONS[nb]['name']}（門還關著）", "move", hint="closed"))
        else:
            out.append(act(f"move:{nb}", LOCATIONS[nb]["name"], "move"))
    out.append(act("look", "四處看看", "here"))
    out.append(act("wait", "待一會兒，看看會發生什麼", "here"))
    if loc == "dock" and w.period not in NIGHT_PERIODS:
        out.append(act("work_dock", "到碼頭扛貨賺點錢", "here"))
    if loc == "tavern" and p["money"] >= DRINK_PRICE:
        out.append(act("drink", f"要一壺酒，坐著聽人聊天（{DRINK_PRICE}文）", "here"))
    if loc == "den" and w.period in (3, 4, 5):
        for bet in (10, 30):
            if p["money"] >= bet:
                out.append(act(f"gamble:{bet}", f"下注{bet}文", "here"))
    if loc == "inn" and p["money"] >= INN_PRICE:
        out.append(act("rest_inn", f"要一間房，睡到天亮（{INN_PRICE}文）", "here"))
    if loc == "temple":
        out.append(act("sleep_temple", "在廟簷下將就睡一晚", "here"))
    if loc == "gate":
        out.append(act("notices", "看看告示牌上貼了什麼", "here"))
    if loc in ("market", "tavern", "inn", "pharmacy") and p["money"] < 40:
        out.append(act("steal", "趁人不注意，摸點錢", "here", hint="risky"))
    if p["inventory"].get("medicine", 0) > 0:
        out.append(act("inventory", f"身上帶著{p['inventory']['medicine']}帖藥", "self", hint="info"))
    return out


def pending_actions(w: World) -> list[dict]:
    pd = w.pending
    p = w.player
    out = []
    if pd["kind"] == "beating":
        out.append(act("pend:stop", "出手阻止", "pending"))
        ln = w.loans.get(pd.get("loan")) if pd.get("loan") else None
        if ln and ln["status"] == "open" and p["money"] >= ln["due_amount"]:
            out.append(act("pend:pay", f"替{w.name(pd['victim'])}把債還了（{ln['due_amount']}文）", "pending"))
        out.append(act("pend:talk", "上前好言相勸", "pending"))
        out.append(act("pend:watch", "袖手旁觀", "pending"))
    elif pd["kind"] == "theft_seen":
        out.append(act("pend:shout", "大喊一聲，當場揭穿", "pending"))
        out.append(act("pend:silent", "裝作沒看見", "pending"))
    elif pd["kind"] == "player_threat":
        ln = w.loans.get(pd["loan"])
        if ln and p["money"] >= ln["due_amount"]:
            out.append(act("pend:pay", f"把錢還了（{ln['due_amount']}文）", "pending"))
        elif p["money"] > 0:
            out.append(act("pend:partial", f"先把身上的{p['money']}文全給他", "pending"))
        out.append(act("pend:beg", "求他再寬限幾天", "pending"))
        out.append(act("pend:fight", "跟他動手", "pending"))
    return out


# ---------------- 執行 ----------------
class ActionError(Exception):
    pass


def perform(w: World, action_id: str, text: str | None = None) -> list[dict]:
    """玩家做一件事。回傳這一回合的所有片段（beats）。"""
    w.feed = []
    valid = {a["id"] for a in available_actions(w)}
    if action_id == "say":
        if not w.player.get("talking_to"):
            raise ActionError("現在沒有在跟誰說話")
    elif action_id not in valid:
        raise ActionError(f"現在不能這麼做：{action_id}")
    w.player["turn"] += 1
    kind, _, arg = action_id.partition(":")
    p = w.player
    if kind == "pend":
        resolve_pending(w, arg)
    elif kind == "move":
        do_move(w, arg)
    elif kind == "talk":
        dialogue.start_talk(w, arg)
    elif kind in dialogue.TALK_KINDS or action_id == "say":
        dialogue.do_talk(w, action_id, text)
    elif kind == "look":
        do_look(w)
    elif kind == "wait":
        sim.beat(w, "action", "你找了個地方站著，看著來來往往的人。")
        sim.advance(w, COST["wait"])
    elif kind == "work_dock":
        do_work_dock(w)
    elif kind == "drink":
        do_drink(w)
    elif kind == "gamble":
        do_gamble(w, int(arg))
    elif kind == "rest_inn":
        do_sleep(w, inn=True)
    elif kind == "sleep_temple":
        do_sleep(w, inn=False)
    elif kind == "notices":
        do_notices(w)
    elif kind == "steal":
        do_steal(w)
    elif kind == "jail_wait":
        sim.beat(w, "action", "拘房裡又冷又潮，你靠著牆，聽著外頭的聲音，一個時辰一個時辰地熬。")
        sim.advance_to_next_dawn(w)
        check_release(w)
    elif kind == "jail_bribe":
        w.transfer("player", "xiaoli", 30)
        p["jailed_until"] = 0
        fid = w.add_fact("bribe", {"briber": "player", "guard": "xiaoli", "prisoner": "player"}, place="yamen",
                         secrecy="secret", importance=3, known_by=["xiaoli"])
        deed(w, fid)
        sim.beat(w, "action", "小李左右看了看，把錢收進袖子裡，悄悄拉開了木柵：「快走，就當我沒看見。」")
    elif kind == "inventory":
        sim.beat(w, "system", f"你身上有{p['inventory'].get('medicine', 0)}帖藥。")
    after_action(w)
    return list(w.feed)


def after_action(w: World):
    p = w.player
    nid = p.get("talking_to")
    if nid and nid in w.npcs:
        n = w.npcs[nid]
        here = (n["status"] == "normal" and n["location"] == p["location"]) or (n["status"] == "jailed" and p["location"] == "yamen")
        if not here:
            p["talking_to"] = None
            sim.beat(w, "action", f"{w.name(nid)}說還有事要忙，先走了。")
    for nid in w.present_npcs(p["location"]):
        p["last_seen"][nid] = {"day": w.day, "place": p["location"]}
    check_collapse(w)


def spread_town_news(w: World):
    """大事會在鎮上口耳相傳：每天清晨把前一天的大消息散給所有人（包括玩家）。"""
    items = w.flags.get("_town_news", [])
    keep = []
    for fid in items:
        f = w.facts.get(fid)
        if not f:
            continue
        if f["day"] < w.day:
            for nid, n in w.npcs.items():
                if n["status"] in ("normal", "jailed") and fid not in n["knows"]:
                    n["knows"][fid] = {"day": w.day, "src": "town"}
                    from . import reactions

                    reactions.on_learn(w, nid, fid, "town")
            if fid not in w.player["knows"] and not jailed(w) and w.player.get("arrived", True):
                w.player["knows"][fid] = {"day": w.day, "src": "town"}
                sim.beat(w, "news", "鎮上都在傳：" + T.fact_text(w, f), fid)
        else:
            keep.append(fid)
    w.flags["_town_news"] = keep


def check_release(w: World):
    p = w.player
    if p.get("jailed_until") and p["jailed_until"] < w.day:
        p["jailed_until"] = 0
        p["location"] = "yamen"
        sim.beat(w, "action", "木柵打開了。小李朝外頭努了努嘴：「出去吧，別再讓我看見你。」")


def check_collapse(w: World):
    p = w.player
    if p["health"] > 0:
        return
    lost = p["money"] // 2
    p["money"] -= lost
    p["talking_to"] = None
    w.pending = None
    sim.beat(w, "system", "眼前一黑，你什麼都不知道了。")
    sim.advance_to_next_dawn(w)
    p["location"] = "pharmacy"
    p["health"] = 35
    sim.beat(w, "action", f"你在濟世堂的竹床上醒來，渾身痠痛。白大夫說是有人把你抬來的。錢袋輕了一大半——少了{lost}文。")


def do_move(w: World, dest: str):
    opens = LOCATIONS[dest].get("open")
    if opens and w.period not in opens:
        sim.beat(w, "action", f"{LOCATIONS[dest]['name']}的門關著，敲了半天也沒人應。")
        return
    p = w.player
    p["location"] = dest
    p["talking_to"] = None
    sim.advance(w, COST["move"])
    if w.pending:
        return
    # 最近剛來過的地方就不再整段描寫，免得長街這種樞紐一直重複
    visits = p.setdefault("visits", {})
    night = w.period in NIGHT_PERIODS
    last = visits.get(dest)
    if last is None or w.clock - last[0] > 12 or last[1] != night:
        desc = LOCATIONS[dest]["night" if night else "day"]
        sim.beat(w, "arrive", f"你來到{LOCATIONS[dest]['name']}。{desc}")
    else:
        sim.beat(w, "arrive", f"你來到{LOCATIONS[dest]['name']}。")
    visits[dest] = [w.clock, night]


def do_look(w: World):
    p = w.player
    loc = p["location"]
    lines = []
    for nid in w.present_npcs(loc):
        n = w.npcs[nid]
        who = w.name(nid) if nid in p["met"] else f"一個{n['role']}"
        lines.append(f"{who}，{T.demeanor(w, n)}")
    if lines:
        sim.beat(w, "action", "你四處看了看。" + "；".join(lines) + "。")
    else:
        sim.beat(w, "action", "你四處看了看，這裡現在沒什麼人。")
    find_clue(w, loc)
    sim.advance(w, COST["look"])


def find_clue(w: World, loc: str):
    """在最近出過事的地方仔細看，有機會找到線索——線索不一定指向真兇。"""
    for case in w.cases.values():
        if case["status"] not in ("open", "pending_arrest") or case["place"] != loc or w.day - case["opened_day"] > 4:
            continue
        if any(w.facts[f]["type"] == "clue" and w.facts[f]["data"].get("crime") == case["crime"] for f in w.player["knows"]):
            continue
        bonus = 10 if w.player["background"] in ("scholar", "peddler") else 0
        if not w.roll(30 + prowess(w) * 3 + bonus):
            continue
        truth = case.get("true_culprit")
        suspect = truth if truth and w.roll(70) else None
        if not suspect:
            pool = [i for i, n in w.npcs.items() if n["status"] in ("normal", "jailed") and i != case.get("victim")]
            suspect = w.rng.choice(pool) if pool else truth
        if not suspect or suspect == "player":
            continue
        what = w.rng.choice(["一小塊扯破的衣角", "半個沾著泥的腳印", "一枚掉在角落的銅扣", "一截斷掉的草繩"])
        fid = w.add_fact("clue", {"suspect": suspect}, place=loc, data={"what": what, "crime": case["crime"]},
                         secrecy="private", importance=3, truth=(suspect == truth), log=False)
        w.learn("player", fid, "self")
        sim.beat(w, "action", f"你蹲下來仔細看，在角落發現了{what}。這東西……你好像在{w.name(suspect)}身上見過類似的。", fid)
        return


def do_work_dock(w: World):
    pay = int(6 + prowess(w) * 1.5 + w.rng.randint(0, 6))
    if w.weather == "雨":
        pay //= 2
    w.add_money("player", pay)
    w.hurt("player", 4)
    fid = w.add_fact("player_work", {"who": "player"}, place="dock", secrecy="public", importance=1,
                     witnesses=sim.witnesses_at(w, "dock", exclude=("player",)), log=False)
    sim.beat(w, "action", f"你跟著苦力們扛了兩個時辰的麻包，肩膀火辣辣地疼，換來{pay}文。")
    for nid in w.present_npcs("dock"):
        w.adjust_opinion(nid, "player", 2)
    sim.advance(w, COST["work"])


def do_drink(w: World):
    owner = w.properties["tavern"]["owner"]
    if w.free(owner):
        w.transfer("player", owner, DRINK_PRICE)
        w.adjust_opinion(owner, "player", 2)
    else:
        w.add_money("player", -DRINK_PRICE)
    sim.beat(w, "action", "你要了一壺溫酒，挑了個角落坐下，豎起耳朵聽四周的人聊天。")
    overhear(w, "tavern", 0.7)
    sim.advance(w, COST["drink"])


def overhear(w: World, loc: str, chance: float):
    if w.rng.random() > chance + (0.15 if w.player["background"] == "peddler" else 0):
        return
    talkers = [i for i in w.present_npcs(loc) if not w.npcs[i].get("bedridden")]
    w.rng.shuffle(talkers)
    for t in talkers:
        opts = behaviors.shareable(w, t, "player")
        fid = w.pick_weighted(opts)
        if fid:
            w.learn("player", fid, t)
            sim.beat(w, "overheard", f"隔壁桌的{w.name(t)}說得正起勁：「{T.fact_text(w, w.facts[fid], speaker=t, listener='others')}」", fid)
            return


def do_gamble(w: World, bet: int):
    house = "qian" if w.free("qian") else None
    if w.roll(42):
        if house:
            w.transfer(house, "player", bet)
        else:
            w.add_money("player", bet)
        sim.beat(w, "action", w.rng.choice([f"骰子停下來，三個六。你贏了{bet}文。", f"「開——大！」你押對了，贏了{bet}文。"]))
    else:
        if house:
            w.transfer("player", house, bet)
        else:
            w.add_money("player", -bet)
        sim.beat(w, "action", w.rng.choice([f"碗一掀，你輸了{bet}文。", f"莊家把你的{bet}文撥了過去，連看都沒看你一眼。"]))
    overhear(w, "den", 0.3)
    sim.advance(w, COST["gamble"])


def do_sleep(w: World, inn: bool):
    p = w.player
    if inn:
        w.transfer("player", w.properties["inn"]["owner"], INN_PRICE)
        p["lodging_until"] = w.day + 1
        sim.beat(w, "action", "孫記客棧的床板硬是硬了點，被子倒是曬過的。你一躺下就睡著了。")
        heal = 25
    else:
        sim.beat(w, "action", "你縮在土地廟的屋簷下，聽著風聲和別人的鼾聲，半睡半醒地熬到天亮。")
        heal = 15 if p["background"] == "drifter" else 8
        # 睡在廟裡，錢袋可能被摸走
        thieves = [i for i in w.present_npcs("temple") if w.npcs[i]["traits"]["honesty"] <= 3]
        if thieves and p["money"] >= 10 and w.roll(35):
            t = w.rng.choice(thieves)
            got = w.transfer("player", t, max(5, p["money"] // 3))
            fid = w.add_fact("theft", {"thief": t, "victim": "player"}, place="temple", data={"amount": got},
                             secrecy="secret", importance=3, known_by=[t])
            w.flags.setdefault("_undiscovered", []).append(fid)
    p["talking_to"] = None
    sim.advance_to_next_dawn(w)
    if not w.pending:
        w.heal("player", heal)


def do_notices(w: World):
    p = w.player
    found = 0
    for fid in reversed(w.event_log[-200:]):
        f = w.facts[fid]
        if f["day"] < w.day - 6 or f["secrecy"] != "public" or f["importance"] < 3:
            continue
        if f["type"] not in ("arrest", "evicted", "death", "trader", "property_seized", "fled", "theft_report", "fire"):
            continue
        if w.learn("player", fid, "notice"):
            sim.beat(w, "news", "告示牌上寫著：" + T.fact_text(w, f), fid)
            found += 1
        if found >= 3:
            break
    if not found:
        sim.beat(w, "action", "告示牌上都是些舊告示，沒什麼新鮮事。")
    if p["background"] == "scholar":
        w.adjust_opinion("wu", "player", 2)
    sim.advance(w, COST["notices"])


def do_steal(w: World):
    p = w.player
    loc = p["location"]
    owners = [pr["owner"] for pr in w.properties.values() if pr["place"] == loc and pr["owner"] in w.npcs]
    victim = next((o for o in owners if w.npcs[o]["status"] != "dead" and w.money(o) >= 10), None)
    if not victim:
        sim.beat(w, "action", "你看了一圈，沒找到下手的機會。")
        sim.advance(w, COST["steal"])
        return
    here = w.free(victim) and w.npcs[victim]["location"] == loc
    chance = 55 + prowess(w) * 2 - (25 if here else 0)
    watchers = sim.witnesses_at(w, loc, exclude=("player", victim), notice_pct=20)
    if w.roll(chance) and not (here and w.roll(30)):
        got = w.transfer(victim, "player", max(5, min(60, w.money(victim) // 5)))
        fid = w.add_fact("theft", {"thief": "player", "victim": victim}, place=loc, data={"amount": got},
                         secrecy="secret", importance=4, witnesses=watchers)
        deed(w, fid)
        w.flags.setdefault("_undiscovered", []).append(fid)
        sim.beat(w, "action", f"你的手指輕輕一勾，{got}文錢滑進了袖子。心跳得厲害，但沒有人回頭。" +
                 ("……你好像感覺到有一道視線落在你背上。" if watchers else ""), fid)
    else:
        fid = w.add_fact("caught_stealing", {"thief": "player", "victim": victim}, place=loc, importance=4,
                         known_by=[victim] if here else [], witnesses=sim.witnesses_at(w, loc, exclude=("player",)))
        deed(w, fid)
        if here:
            w.adjust_opinion(victim, "player", -50)
            w.npcs[victim].setdefault("to_report", []).append(fid)
        w.flags.setdefault("_town_news", []).append(fid)
        sim.beat(w, "action", "你的手才剛伸出去，就被人一把抓住——「好啊，青天白日的做賊！」四周的目光全落在你身上。", fid)
    sim.advance(w, COST["steal"])


def player_daily(w: World):
    p = w.player
    if jailed(w) or not p.get("arrived", True):
        return
    if p["money"] >= 3:
        p["money"] -= 3
        p["hungry_days"] = 0
    else:
        p["hungry_days"] += 1
        w.hurt("player", 8)
        sim.beat(w, "system", "你的肚子餓得咕咕叫。身上的錢已經不夠吃一頓飯了。")
    if w.player["health"] < 100 and not p.get("hungry_days"):
        w.heal("player", 3)


# ---------------- 介入（玩家在場時的分岔點） ----------------
def resolve_pending(w: World, choice: str):
    pd = w.pending
    w.pending = None
    if not pd:
        return
    if pd["kind"] == "beating":
        resolve_beating(w, pd, choice)
    elif pd["kind"] == "theft_seen":
        resolve_theft_seen(w, pd, choice)
    elif pd["kind"] == "player_threat":
        resolve_player_threat(w, pd, choice)


def resolve_beating(w: World, pd: dict, choice: str):
    a, v, loc = pd["attacker"], pd["victim"], pd["place"]
    ln = w.loans.get(pd.get("loan")) if pd.get("loan") else None
    roles = {"helper": "player", "target": v, "attacker": a}
    if choice == "stop":
        mine = behaviors.strength(w, "player") + w.rng.uniform(0, 6)
        theirs = behaviors.strength(w, a) + w.rng.uniform(0, 6)
        if mine >= theirs:
            w.hurt(a, w.rng.randint(15, 30))
            w.npcs[a]["condition"] = "injured"
            w.hurt("player", w.rng.randint(0, 10))
            fid = w.add_fact("rescue", roles, place=loc, importance=4, known_by=[a, v],
                             witnesses=sim.witnesses_at(w, loc, exclude=(a, v, "player")))
            deed(w, fid)
            w.adjust_opinion(a, "player", -45)
            if ln:
                w.adjust_opinion("qian", "player", -25)
                ln["due_day"] = w.day + 1
            sim.beat(w, "action", f"你一把扣住{w.name(a)}的手腕，反手一推，{w.name(a)}踉蹌著撞上了牆，瞪著你，捂著肩膀退開了。", fid)
            sim.emit(w, fid, loc)
            return
        dmg = w.rng.randint(20, 35)
        w.hurt("player", dmg)
        sim.beat(w, "action", f"你衝上去，卻被{w.name(a)}一肘撞在胸口，眼前一陣發黑。")
        w.adjust_opinion(a, "player", -20)
        w.adjust_opinion(v, "player", 15)
        _proceed(w, pd, ln, extra_witness=["player"])
    elif choice == "pay" and ln and ln["status"] == "open" and w.money("player") >= ln["due_amount"]:
        fid = sim.repay(w, ln, payer="player")
        deed(w, fid)
        for x in sim.witnesses_at(w, loc, exclude=("player",)):
            w.learn(x, fid, "witness")
        w.adjust_opinion(a, "player", 5)
        sim.beat(w, "action", f"你把錢數出來，遞到{w.name(a)}面前。對方掂了掂，咧嘴一笑：「爽快。」轉身走了。{w.name(v)}愣愣地看著你。", fid)
    elif choice == "talk":
        a_n = w.npcs[a]
        chance = 20 + w.opinion(a, "player") / 2 + a_n["traits"]["kind"] * 3 + (10 if w.player["background"] == "scholar" else 0)
        if w.roll(chance):
            fid = w.add_fact("persuade", roles, place=loc, importance=3, known_by=[a, v],
                             witnesses=sim.witnesses_at(w, loc, exclude=(a, v, "player")))
            deed(w, fid)
            if ln:
                ln["due_day"] = w.day + 2
                ln["stage"] = max(0, ln["stage"] - 1)
            sim.beat(w, "action", f"你擋在兩人中間，好說歹說。{w.name(a)}盯著你看了半晌，啐了一口：「看在你的面子上，再寬限兩天。」", fid)
            sim.emit(w, fid, loc)
        else:
            sim.beat(w, "action", f"{w.name(a)}根本不聽你說話，一把把你推開。")
            _proceed(w, pd, ln, extra_witness=["player"])
    else:
        _proceed(w, pd, ln, extra_witness=["player"])


def _proceed(w: World, pd: dict, ln: dict | None, extra_witness=()):
    a, v, loc = pd["attacker"], pd["victim"], pd["place"]
    if pd["mode"] == "fight":
        behaviors.resolve_fight(w, a, v, loc, pd.get("reason", ""), extra_witness=extra_witness)
    elif pd["mode"] == "threat" and ln:
        fid = w.add_fact("debt_threat", {"collector": a, "debtor": v, "lender": ln["lender"]}, place=loc, importance=3,
                         causes=[ln.get("fact")], known_by=[a, v], witnesses=list(sim.witnesses_at(w, loc, exclude=(a, v))))
        w.stress(v, 25)
        sim.emit(w, fid, loc)
    elif ln:
        sim.do_debt_beating(w, a, v, loc, ln)


def resolve_theft_seen(w: World, pd: dict, choice: str):
    thief, victim, loc, fid = pd["thief"], pd["victim"], pd["place"], pd["fact"]
    if choice == "shout":
        amt = w.facts[fid]["data"].get("amount", 0)
        w.transfer(thief, victim, amt)
        if fid in w.flags.get("_undiscovered", []):
            w.flags["_undiscovered"].remove(fid)
        cid = w.add_fact("caught_stealing", {"thief": thief, "victim": victim}, place=loc, importance=4,
                         causes=[fid], known_by=[thief] + ([victim] if victim != "player" else []),
                         witnesses=sim.witnesses_at(w, loc, exclude=(thief,)))
        deed(w, cid)
        w.adjust_opinion(thief, "player", -40)
        if victim != "player":
            w.adjust_opinion(victim, "player", 30)
            w.npcs[victim].setdefault("to_report", []).append(cid)
        w.flags.setdefault("_town_news", []).append(cid)
        sim.beat(w, "action", f"「站住！」你一聲大喝，{w.name(thief)}渾身一僵，錢撒了一地。所有人都轉過頭來。", cid)
    else:
        sim.beat(w, "action", f"你移開了視線，假裝什麼都沒看見。這件事，現在只有你和{w.name(thief)}知道。")


def collector_confronts_player(w: World, ln: dict, collector: str, stage: int):
    if stage <= 1:
        fid = w.add_fact("debt_warning", {"collector": collector, "debtor": "player", "lender": ln["lender"]},
                         place=w.player["location"], secrecy="private", importance=2, known_by=[collector])
        w.learn("player", fid, "witness")
        sim.beat(w, "witness", f"{w.name(collector)}不知道什麼時候站到了你身後：「錢三爺讓我提醒你，那筆錢該還了。{ln['due_amount']}文，一文都不能少。」", fid)
        return
    w.pending = {"kind": "player_threat", "collector": collector, "loan": ln["id"], "stage": stage,
                 "place": w.player["location"]}
    sim.beat(w, "witness", f"{w.name(collector)}擋住你的去路，手往你肩上一搭：「躲得了初一，躲不過十五。今天這筆帳，怎麼算？」")


def resolve_player_threat(w: World, pd: dict, choice: str):
    ln = w.loans.get(pd["loan"])
    c = pd["collector"]
    loc = pd["place"]
    if not ln or ln["status"] != "open":
        return
    if choice == "pay" and w.money("player") >= ln["due_amount"]:
        sim.repay(w, ln)
        sim.beat(w, "action", f"你把錢數給{w.name(c)}。他點了點，滿意地拍拍你的臉：「這才對嘛。」")
    elif choice == "partial":
        paid = w.transfer("player", ln["lender"], w.money("player"))
        ln["due_amount"] -= paid
        ln["due_day"] = w.day + 2
        sim.beat(w, "action", f"你把身上的{paid}文全掏了出來。{w.name(c)}哼了一聲：「剩下的，兩天。」")
    elif choice == "beg":
        if w.roll(35 + w.opinion(c, "player") / 2):
            ln["due_day"] = w.day + 2
            sim.beat(w, "action", f"{w.name(c)}盯著你看了一會兒，嘆了口氣：「就兩天。兩天後再拿不出來，別怪我。」")
        else:
            _beat_player(w, c, ln, loc)
    elif choice == "fight":
        mine = behaviors.strength(w, "player") + w.rng.uniform(0, 6)
        theirs = behaviors.strength(w, c) + w.rng.uniform(0, 6)
        if mine >= theirs:
            w.hurt(c, w.rng.randint(15, 30))
            w.npcs[c]["condition"] = "injured"
            fid = w.add_fact("fight", {"attacker": "player", "victim": c}, place=loc, data={"winner": "player"},
                             importance=3, known_by=[c], witnesses=sim.witnesses_at(w, loc, exclude=(c,)))
            deed(w, fid)
            w.adjust_opinion("qian", "player", -40)
            ln["due_day"] = w.day + 1
            sim.beat(w, "action", f"你搶先一拳打在{w.name(c)}的下巴上，他摔進了路邊的水溝。爬起來時，他的眼神很難看。", fid)
        else:
            _beat_player(w, c, ln, loc)


def _beat_player(w: World, c: str, ln: dict, loc: str):
    dmg = w.rng.randint(25, 40)
    w.hurt("player", dmg)
    fid = w.add_fact("debt_beating", {"attacker": c, "victim": "player", "lender": ln["lender"]}, place=loc,
                     importance=4, known_by=[c], witnesses=sim.witnesses_at(w, loc, exclude=(c,)))
    w.learn("player", fid, "self")
    sim.beat(w, "action", f"{w.name(c)}的拳頭落在你的肚子上，你彎下腰，又挨了兩腳。「這是利息。」", fid)
