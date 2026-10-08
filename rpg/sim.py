"""世界模擬：時間、作息、每日規則、催收、辦案、行商、調皮事件、新面孔。

世界不只在玩家動的時候動：玩家每做一件事都會花時間，時間一過，所有 NPC 照自己的作息與需要行動，
每天清晨結算一次經濟、債務、病情與案件。玩家只是世界裡的其中一個行動者。
"""

from __future__ import annotations

from . import behaviors, mind, reactions
from .content import text as T
from .content.locations import LOCATIONS, NIGHT_PERIODS
from .content.npcs import DRIFTER_GIVEN, DRIFTER_ROLES, DRIFTER_SURNAMES
from .world import TICKS_PER_DAY, TICKS_PER_PERIOD, World, make_npc

MEDICINE_PRICE = 30
DOCTOR_FEE = 15
MAX_MED_STOCK = 6
MISCHIEF_CHANCE = 3   # %，每天


# ---------------- 對玩家的輸出片段 ----------------
def beat(w: World, kind: str, text: str, fid: str | None = None):
    w.feed.append({"kind": kind, "text": text, "fid": fid})


def player_here(w: World, place: str) -> bool:
    p = w.player
    return p["location"] == place and p.get("jailed_until", 0) < w.day


def emit(w: World, fid: str, place: str | None):
    """事件發生後，決定玩家看不看得到、聽不聽得到。"""
    f = w.facts[fid]
    if place and w.player["location"] == place and fid in w.player["knows"]:
        tpl = T.WITNESS.get(f["type"])
        if tpl:
            beat(w, "witness", fmt(w, w.rng.choice(tpl), f), fid)
        else:
            beat(w, "witness", T.fact_text(w, f), fid)
    elif place and w.player["location"] and f["type"] in T.DISTANT and place in LOCATIONS.get(w.player["location"], {}).get("neighbors", []):
        beat(w, "distant", T.DISTANT[f["type"]], None)


def fmt(w: World, tpl: str, f: dict) -> str:
    vals = {k: w.name(v) for k, v in f["roles"].items()}
    vals.update({k: v for k, v in f["data"].items() if isinstance(v, (str, int))})
    try:
        return tpl.format(**vals)
    except (KeyError, IndexError):
        return T.fact_text(w, f)


def witnesses_at(w: World, place: str, exclude=(), notice_pct: float = 100) -> list[str]:
    out = []
    for nid in w.present_npcs(place):
        if nid in exclude or w.npcs[nid].get("bedridden"):
            continue
        if notice_pct >= 100 or w.roll(notice_pct + w.npcs[nid]["traits"]["gossip"] * 2):
            out.append(nid)
    if player_here(w, place) and "player" not in exclude:
        if notice_pct >= 100 or w.roll(notice_pct + 10):
            out.append("player")
    return out


# ---------------- 作息 ----------------
def npc_location(w: World, n: dict, period: int) -> str | None:
    if n["status"] == "jailed":
        return "yamen"
    if n["status"] != "normal":
        return None
    if n.get("bedridden") or n["condition"] == "ill" or n["health"] < 40:
        return n["home"]
    if n.get("grief_until", 0) >= w.day:
        return "tavern" if period in (3, 4) and n["traits"]["vice"] >= 3 else n["home"]
    if not n.get("employed", True):
        day_spot = "dock" if n["money"] < 10 else "street"
        return [n["home"], day_spot, day_spot, "tavern", "den" if n["traits"]["vice"] >= 5 else "tavern", n["home"]][period]
    loc = n["schedule"][period]
    if w.weather == "雨" and loc in ("market", "dock") and period not in NIGHT_PERIODS and w.rng.random() < 0.5:
        loc = "tavern" if n["traits"]["vice"] >= 3 else n["home"]
    return loc


def place_npcs(w: World):
    for n in w.npcs.values():
        n["location"] = npc_location(w, n, w.period)


# ---------------- 時間推進 ----------------
def advance(w: World, ticks: int):
    for _ in range(max(0, ticks)):
        if w.pending:
            return
        w.clock += 1
        if w.clock % TICKS_PER_PERIOD == 0:
            if w.clock % TICKS_PER_DAY == 0:
                day_start(w)
            period_tick(w)


def advance_to_next_dawn(w: World):
    while not w.pending:
        w.clock += 1
        if w.clock % TICKS_PER_PERIOD == 0:
            if w.clock % TICKS_PER_DAY == 0:
                day_start(w)
                period_tick(w)
                return
            period_tick(w)


def period_tick(w: World):
    place_npcs(w)
    run_scheduled(w)
    order = [i for i, n in w.npcs.items() if n["status"] == "normal"]
    w.rng.shuffle(order)
    for nid in order:
        if w.pending:
            break
        if w.npcs[nid]["status"] != "normal" or w.npcs[nid].get("bedridden"):
            continue
        behaviors.maybe_act(w, nid)
    ambient(w)


def ambient(w: World):
    loc = w.player["location"]
    if loc is None or w.player.get("jailed_until", 0) >= w.day:   # 關在拘房裡看不到外頭
        return
    from . import speech

    if loc in LOCATIONS and speech.chance(w, "_amb", 25):   # 純文字：不消耗 world.rng

        pool = LOCATIONS[loc]["ambient"]
        line = speech.pick(w, f"_amb:{loc}", pool, optional=True, keep=max(1, len(pool) - 1))
        if line:   # 剛出現過的路人景象不馬上重演
            beat(w, "ambient", line)


# ---------------- 排程的事件（催收上門、抓人） ----------------
def schedule(w: World, period: int, kind: str, **data):
    w.flags.setdefault("_sched", [])
    w.flags["_sched"].append({"day": w.day, "period": period, "kind": kind, **data})


def run_scheduled(w: World):
    items = w.flags.get("_sched", [])
    keep = []
    for it in items:
        if it["day"] < w.day:
            continue
        if it["day"] == w.day and it["period"] == w.period:
            if it["kind"] == "collect":
                collection_visit(w, it["loan"])
            elif it["kind"] == "arrest":
                do_arrest(w, it["case"], it["suspect"])
        else:
            keep.append(it)
    w.flags["_sched"] = keep


# ---------------- 每日清晨 ----------------
def day_start(w: World):
    w.weather = "雨" if w.rng.random() < 0.15 else ("陰" if w.rng.random() < 0.25 else "晴")
    w.prosperity += (50 - w.prosperity) // 6
    from . import speech

    if w.player.get("jailed_until", 0) >= w.day:
        pool = T.DAY_OPENERS_JAIL
    else:
        pool = T.DAY_OPENERS_RAIN if w.weather == "雨" else T.DAY_OPENERS
    beat(w, "day", speech.pick(w, "_day", pool))
    for n in w.npcs.values():
        n["talks_today"] = 0
    from . import player as player_mod

    player_mod.spread_town_news(w)
    releases(w)
    economy(w)
    if w.day % 7 == 0:
        rent_day(w)
    loans_daily(w)
    health_daily(w)
    update_needs(w)
    discover_thefts(w)
    investigate(w)
    trader(w)
    mischief(w)
    drifters(w)
    for n in w.npcs.values():
        if n["status"] == "normal":
            base = 4 if n.get("grief_until", 0) < w.day else 0
            n["stress"] = max(0, n["stress"] - base)
        for k in list(n["blame"]):
            n["blame"][k] = int(n["blame"][k] * 0.9)
            if n["blame"][k] < 10:
                del n["blame"][k]
        # 時間會沖淡怨氣：很深的成見會非常緩慢地回到中間（不碰正面感情，也不碰仇人的血債）
        for o, v in n["opinions"].items():
            if v < -30 and o not in n["blame"] and w.rng.random() < 0.4:
                n["opinions"][o] = v + 1
    player_mod.player_daily(w)


def releases(w: World):
    for nid, n in w.npcs.items():
        if n["status"] == "jailed" and n["jail_until"] <= w.day:
            n["status"] = "normal"
            fid = w.add_fact("release", {"who": nid}, place="yamen", importance=1, known_by=[nid, "zhao", "xiaoli"])
            emit(w, fid, "yamen")


def owner_of(w: World, prop: str) -> str | None:
    p = w.properties.get(prop)
    return p["owner"] if p else None


def economy(w: World):
    mult = (w.prosperity + 50) / 100
    owned = {}
    for pid, p in w.properties.items():
        owned.setdefault(p["owner"], []).append(pid)
    for nid, n in w.npcs.items():
        if n["status"] != "normal":
            continue
        # 自己開的店若被收走，原本的收入就沒了（收入改由新東家拿）
        works = n.get("employed", True) and not n.get("bedridden") and n["health"] >= 40
        if works and n["income"] > 0:
            own_prop = [pid for pid, p in w.properties.items() if p["place"] == n["work"] and p.get("orig_owner", p["owner"]) == nid]
            if own_prop and owner_of(w, own_prop[0]) != nid:
                pass
            else:
                inc = int(n["income"] * mult)
                if w.weather == "雨" and n["work"] in ("market", "dock"):
                    inc //= 2
                garnish = n.get("garnished_by")
                if garnish and w.free(garnish):
                    take = inc // 2
                    w.add_money(garnish, take)
                    inc -= take
                    for ln in w.open_loans(borrower=nid, lender=garnish):
                        if ln.get("garnish"):
                            ln["due_amount"] -= take
                            if ln["due_amount"] <= 0:
                                ln["status"] = "repaid"
                                ln["repaid_by"] = "garnish"
                                n.pop("garnished_by", None)
                            break
                w.add_money(nid, inc)
        if works and n.get("wage_from") and n["wage"]:
            emp = n["wage_from"]
            if emp in w.npcs and w.npcs[emp]["status"] == "normal" and w.money(emp) >= n["wage"]:
                w.transfer(emp, nid, n["wage"])
                n["unpaid_wage_days"] = 0
                if n.get("garnished_by") == emp:
                    for ln in w.open_loans(borrower=nid, lender=emp):
                        if ln.get("garnish"):
                            take = w.transfer(nid, emp, n["wage"] // 2 + 1)
                            ln["due_amount"] -= take
                            if ln["due_amount"] <= 0:
                                ln["status"] = "repaid"
                                ln["repaid_by"] = "garnish"
                                n.pop("garnished_by", None)
                            break
            else:
                n["unpaid_wage_days"] = n.get("unpaid_wage_days", 0) + 1
                w.stress(nid, 4)
                if n["unpaid_wage_days"] == 3 and emp in w.npcs:
                    fid = w.add_fact("wages_unpaid", {"employer": emp, "who": nid}, place=n["work"],
                                     secrecy="private", importance=2, known_by=[nid, emp])
                    w.adjust_opinion(nid, emp, -15)
        # 被收走的產業，收入歸新東家
        for pid in owned.get(nid, []):
            p = w.properties[pid]
            if p.get("orig_owner") and p["orig_owner"] != nid:
                w.add_money(nid, int(18 * mult))
        # 吃飯
        if not n.get("bedridden"):
            if n["money"] >= 2:
                n["money"] -= 2
                n["hungry_days"] = 0
            else:
                n["hungry_days"] = n.get("hungry_days", 0) + 1
                w.stress(nid, 6)
                if n["hungry_days"] >= 4:
                    w.hurt(nid, 6)


def rent_day(w: World):
    for nid, n in w.npcs.items():
        landlord = n.get("landlord")
        if not landlord or n["status"] != "normal" or not n.get("employed", True) or n["rent"] <= 0:
            continue
        if not w.free(landlord):
            continue
        if w.money(nid) >= n["rent"]:
            w.transfer(nid, landlord, n["rent"])
            n["unpaid_rent"] = 0
        else:
            n["unpaid_rent"] += 1
            w.stress(nid, 18)
            fid = w.add_fact("rent_unpaid", {"tenant": nid, "landlord": landlord}, place=n["work"],
                             secrecy="public", importance=2, known_by=[nid, landlord])
            emit(w, fid, n["work"])
            if n["unpaid_rent"] >= 2:
                evict(w, nid, landlord, cause=fid)


def evict(w: World, nid: str, landlord: str, cause: str | None = None):
    n = w.npcs[nid]
    n["employed"] = False
    n["income"] = 0
    for pid, p in w.properties.items():
        if p["owner"] == nid and p["place"] == n["work"]:
            p.setdefault("orig_owner", nid)
            p["owner"] = landlord
    fid = w.add_fact("evicted", {"tenant": nid, "landlord": landlord}, place=n["work"], importance=3,
                     causes=[cause] if cause else [], witnesses=witnesses_at(w, n["work"]), known_by=[nid, landlord])
    w.stress(nid, 30)
    w.adjust_opinion(nid, landlord, -40)
    emit(w, fid, n["work"])


# ---------------- 借貸與催收 ----------------
def loans_daily(w: World):
    for ln in list(w.loans.values()):
        if ln["status"] != "open":
            continue
        b, lender = ln["borrower"], ln["lender"]
        bent = w.player if b == "player" else w.npcs.get(b)
        if b != "player" and bent["status"] in ("fled", "dead"):
            handle_vanished_borrower(w, ln)
            continue
        # 有錢就還（老實的人更會還）
        if b != "player" and w.money(b) >= ln["due_amount"] and w.day >= ln["due_day"] - 1:
            if w.roll(40 + bent["traits"]["honesty"] * 7):
                repay(w, ln)
                continue
        if w.day <= ln["due_day"]:
            continue
        if lender == "qian":
            if ln.get("garnish"):
                if not bent.get("employed", True) and w.day - ln.get("garnish_day", w.day) >= 7:
                    ln["status"] = "defaulted"
                    bent.pop("garnished_by", None)
                    w.adjust_opinion("qian", b, -30)
                continue
            ln["due_amount"] += max(1, ln["principal"] // 20)   # 逾期一天加利息
            if ln.get("garnish"):
                continue
            if ln["stage"] > 0 and w.day - ln.get("last_stage_day", 0) < 2:
                continue
            collector = pick_collector(w)
            if not collector:
                continue
            if ln["stage"] < 4:
                ln["stage"] += 1
            ln["last_stage_day"] = w.day
            schedule(w, w.rng.choice([1, 2, 3]), "collect", loan=ln["id"])
        elif lender == "player":
            pass  # 玩家借出去的錢，要不要催由玩家自己決定
        else:
            overdue = w.day - ln["due_day"]
            w.adjust_opinion(lender, b, -2)
            if overdue >= 5 and w.npcs[lender]["traits"]["kind"] >= 7 and w.opinion(lender, b) >= 30:
                ln["status"] = "forgiven"
                w.add_fact("debt_forgiven", {"lender": lender, "borrower": b}, secrecy="private", importance=2,
                           known_by=[lender, b], causes=[ln.get("fact")])


def pick_collector(w: World) -> str | None:
    for cid in ("liu6", w.flags.get("collector2")):
        if cid and w.free(cid) and w.npcs[cid]["health"] >= 50:
            return cid
    # 收帳的人倒了：錢三爺過幾天會找個新的打手
    if not w.flags.get("collector2") and w.rng.random() < 0.3:
        nid = spawn_drifter(w, role_index=4)
        if nid:
            w.flags["collector2"] = nid
            w.npcs[nid]["wage_from"] = "qian"
            w.npcs[nid]["wage"] = 6
            w.npcs[nid]["schedule"] = ["den", "street", "market", "tavern", "den", "den"]
    return None


def repay(w: World, ln: dict, payer: str | None = None):
    b = ln["borrower"]
    payer = payer or b
    amount = w.transfer(payer, ln["lender"], ln["due_amount"])
    ln["status"] = "repaid"
    ln["repaid_by"] = payer
    if payer == b:
        fid = w.add_fact("loan_repaid", {"borrower": b, "lender": ln["lender"]}, secrecy="private", importance=1,
                         known_by=[b, ln["lender"]] + (["liu6"] if ln["lender"] == "qian" else []),
                         causes=[ln.get("fact")])
    else:
        fid = w.add_fact("debt_paid_by", {"payer": payer, "debtor": b, "lender": ln["lender"]},
                         data={"amount": amount}, secrecy="private", importance=3,
                         known_by=[payer, ln["lender"]], causes=[ln.get("fact")])
        w.learn(b, fid, ln["lender"]) if b != "player" else None
    for n in (w.npcs.get(b),):
        if n:
            n.pop("garnished_by", None)
    return fid


def able(w: World, nid: str) -> bool:
    return w.free(nid) and not w.npcs[nid].get("bedridden")


def handle_vanished_borrower(w: World, ln: dict):
    b = ln["borrower"]
    heir = ln.get("guarantor")
    if not heir or not able(w, heir):
        fam = [x for x in w.family_of(b) if able(w, x)]
        heir = fam[0] if fam and ln["lender"] == "qian" else None
    if heir:
        ln["borrower"] = heir
        ln["guarantor"] = None
        ln["due_day"] = w.day + 3
        ln["stage"] = 0
        fid = w.add_fact("debt_transferred", {"debtor": b, "lender": ln["lender"], "guarantor": heir},
                         secrecy="public", importance=4, causes=[ln.get("fact")],
                         known_by=[heir, ln["lender"]] + (["liu6"] if ln["lender"] == "qian" else []))
        ln["fact"] = fid
        w.stress(heir, 30)
        w.adjust_opinion(heir, b, -50)
    else:
        ln["status"] = "defaulted"
        if ln["lender"] in w.npcs:
            w.adjust_opinion(ln["lender"], b, -60)


def collection_visit(w: World, loan_id: str):
    ln = w.loans.get(loan_id)
    if not ln or ln["status"] != "open":
        return
    collector = pick_collector(w)
    if not collector:
        return
    debtor = ln["borrower"]
    if debtor == "player":
        loc = w.player["location"]
        if w.player.get("jailed_until", 0) >= w.day:
            return
    else:
        if not w.free(debtor):
            return
        if w.npcs[debtor].get("bedridden"):
            handle_vanished_borrower(w, ln)
            return
        loc = w.npcs[debtor]["location"]
    if collector == debtor:
        # 收帳的人自己欠錢：錢三爺直接扣他的工錢，不用自己打自己
        ln["garnish"] = True
        ln["garnish_day"] = w.day
        w.npcs[debtor]["garnished_by"] = ln["lender"]
        w.stress(debtor, 15)
        return
    w.npcs[collector]["location"] = loc
    stage = ln["stage"]
    cause = [ln.get("fact")]
    roles = {"collector": collector, "debtor": debtor, "lender": ln["lender"]}
    if debtor == "player":
        from . import player as player_mod

        player_mod.collector_confronts_player(w, ln, collector, stage)
        return
    if stage <= 1:
        fid = w.add_fact("debt_warning", roles, place=loc, secrecy="private", importance=2, causes=cause,
                         known_by=[collector, debtor], witnesses=[x for x in witnesses_at(w, loc, exclude=(collector, debtor), notice_pct=30)])
        w.stress(debtor, 15)
        emit(w, fid, loc)
    elif stage == 2:
        if player_here(w, loc):
            open_pending_beating(w, collector, debtor, loc, ln, mode="threat")
            return
        fid = w.add_fact("debt_threat", roles, place=loc, importance=3, causes=cause,
                         known_by=[collector, debtor], witnesses=witnesses_at(w, loc, exclude=(collector, debtor)))
        w.stress(debtor, 25)
        emit(w, fid, loc)
    elif stage == 3:
        if player_here(w, loc):
            open_pending_beating(w, collector, debtor, loc, ln, mode="beat")
            return
        do_debt_beating(w, collector, debtor, loc, ln)
    else:
        seize_or_garnish(w, ln, collector, loc)


def do_debt_beating(w: World, collector: str, debtor: str, loc: str, ln: dict, extra_witness=()):
    # 收帳的人要的是錢，不是人命：下手有分寸
    dmg = w.rng.randint(15, 28)
    w.npcs[debtor]["health"] = max(8, w.npcs[debtor]["health"] - dmg)
    w.npcs[debtor]["condition"] = "injured"
    roles = {"attacker": collector, "victim": debtor, "lender": ln["lender"]}
    fid = w.add_fact("debt_beating", roles, place=loc, importance=4, causes=[ln.get("fact")],
                     known_by=[collector, debtor], witnesses=list(witnesses_at(w, loc, exclude=(collector, debtor))) + list(extra_witness))
    w.stress(debtor, 30)
    check_death(w, debtor, fid, "被打成重傷，沒能撐過去", attacker=collector)
    emit(w, fid, loc)
    return fid


def seize_or_garnish(w: World, ln: dict, collector: str, loc: str):
    debtor = ln["borrower"]
    props = [pid for pid, p in w.properties.items() if p["owner"] == debtor]
    if ln.get("secured") and ln["secured"] in props:
        props = [ln["secured"]]
    if props:
        pid = props[0]
        p = w.properties[pid]
        p.setdefault("orig_owner", debtor)
        p["owner"] = ln["lender"]
        ln["status"] = "repaid"
        ln["repaid_by"] = "seizure"
        fid = w.add_fact("property_seized", {"lender": ln["lender"], "debtor": debtor}, place=p["place"],
                         data={"property": p["name"]}, importance=5, causes=[ln.get("fact")],
                         known_by=[debtor, ln["lender"], collector], witnesses=witnesses_at(w, p["place"]))
        w.npcs[debtor]["employed"] = False
        w.stress(debtor, 40)
        w.adjust_opinion(debtor, ln["lender"], -50)
        # 新東家對店裡的夥計：貪心的人會把人辭掉
        for eid, e in w.npcs.items():
            if e.get("wage_from") == debtor and e["work"] == p["place"] and e["status"] == "normal":
                if w.npcs[ln["lender"]]["traits"]["greed"] >= 7 and w.rng.random() < 0.6:
                    e["employed"] = False
                    e["wage_from"] = None
                    f2 = w.add_fact("fired", {"owner": ln["lender"], "who": eid}, place=p["place"], importance=3,
                                    causes=[fid], known_by=[eid, ln["lender"]], witnesses=witnesses_at(w, p["place"]))
                    w.stress(eid, 25)
                    emit(w, f2, p["place"])
                else:
                    e["wage_from"] = ln["lender"]
        emit(w, fid, p["place"])
    else:
        # 沒有產業可收：從此每天的收入被抽走一半，直到還清
        w.npcs[debtor]["garnished_by"] = ln["lender"]
        ln["garnish"] = True
        ln["garnish_day"] = w.day
        fid = w.add_fact("debt_threat", {"collector": collector, "debtor": debtor, "lender": ln["lender"]}, place=loc,
                         data={"garnish": True}, importance=3, causes=[ln.get("fact")], known_by=[collector, debtor],
                         witnesses=witnesses_at(w, loc, exclude=(collector, debtor)))
        w.stress(debtor, 20)
        emit(w, fid, loc)


def open_pending_beating(w: World, attacker: str, victim: str, loc: str, ln: dict | None, mode: str, reason: str = ""):
    w.pending = {
        "kind": "beating",
        "mode": mode,
        "attacker": attacker,
        "victim": victim,
        "place": loc,
        "loan": ln["id"] if ln else None,
        "reason": reason,
    }


def check_death(w: World, nid: str, cause_fid: str | None, cause_text: str, attacker: str | None = None):
    n = w.npcs[nid]
    if n["health"] > 0 or n["status"] == "dead":
        return None
    n["status"] = "dead"
    loc = n["location"]
    n["location"] = None
    roles = {"who": nid}
    if attacker:
        roles["culprit"] = attacker
    fid = w.add_fact("death", roles, place=loc, data={"cause_text": cause_text}, importance=5,
                     causes=[cause_fid] if cause_fid else [], known_by=w.family_of(nid),
                     witnesses=witnesses_at(w, loc) if loc else [])
    # 大事：一天之內全鎮都會知道（透過街坊口耳相傳，算是公開消息）
    w.flags.setdefault("_town_news", []).append(fid)
    for fam in w.family_of(nid):
        if w.npcs[fam]["status"] == "normal":
            w.npcs[fam]["grief_until"] = w.day + 7
            w.npcs[fam]["grief_for"] = nid
    emit(w, fid, loc)
    return fid


# ---------------- 健康 ----------------
def things_daily(w: World):
    """體內的東西會發作：有成因的病灶偶爾造成症狀（看得到的是症狀，成因要診察才知道）。"""
    from .content.nature import CAUSES

    for t in list(w.things.values()):
        if not t["active"] or not t["host"] or t["host"] not in w.npcs:
            continue
        n = w.npcs[t["host"]]
        c = CAUSES.get(t.get("cause") or "")
        if n["status"] != "normal" or not c or not c["flare_pct"]:
            continue
        if w.roll(c["flare_pct"], lo=0, hi=50):
            w.hurt(n["id"], c["hurt"])
            n["symptom_until"] = w.day + 1
            w.stress(n["id"], 8)
            check_death(w, n["id"], None, "舊疾發作")


def health_daily(w: World):
    for nid, n in w.npcs.items():
        if n["status"] not in ("normal", "jailed"):
            continue
        if n.get("bedridden"):
            if n.get("patron_of") is None:
                pass
            # 慢性病：吃藥只能撐住，停藥就往下掉；身子最多恢復到八成
            if n["medicine_days"] > 0:
                n["medicine_days"] -= 1
                if n["health"] < 80:
                    w.heal(nid, 1)
            else:
                w.hurt(nid, n.get("decay", 3))
                if n["health"] < 30 and not n.get("worse_noted"):
                    n["worse_noted"] = True
                    fid = w.add_fact("worse", {"who": nid}, place=n["home"], secrecy="private", importance=3,
                                     known_by=[nid] + w.family_of(nid) + ["bai"])
            if n["health"] >= 40:
                n["worse_noted"] = False
            check_death(w, nid, None, "病沒熬過去")
            continue
        if n["condition"] == "ill":
            if n["medicine_days"] > 0:
                n["medicine_days"] -= 1
                w.heal(nid, 12)
            else:
                w.hurt(nid, 4)
            n["ill_days"] = n.get("ill_days", 0) - 1
            if n["ill_days"] <= 0 and n["health"] >= 50:
                n["condition"] = "healthy"
                for t in mind.things_of(w, nid, held=False):
                    if t["kind"] == "inflamed":
                        t["active"] = False
                w.add_fact("recovered", {"who": nid}, secrecy="private", importance=1, known_by=[nid])
            check_death(w, nid, None, "一場急病")
        elif n["condition"] == "injured" or n["health"] < 100:
            w.heal(nid, 6 + (6 if n.get("doctored") else 0))
            n["doctored"] = False
            if n["health"] >= 75:
                n["condition"] = "healthy"
        if n["status"] == "normal" and n["condition"] == "healthy" and w.rng.random() < 0.004:
            n["condition"] = "ill"
            n["ill_days"] = w.rng.randint(3, 6)
            w.hurt(nid, 25)
            # 病有成因：一個真實存在、診察得到的病灶（好了就會消失）
            mind.add_thing(w, "inflamed", host=nid, origin="ill")
            w.add_fact("ill", {"who": nid}, place=n["home"], secrecy="public", importance=2,
                       known_by=[nid] + w.family_of(nid))
    things_daily(w)
    # 暗中的資助者：每隔幾天替病人買藥
    for nid, n in w.npcs.items():
        pat = n.get("patron_of")
        if not pat or n["status"] != "normal" or pat not in w.npcs or w.npcs[pat]["status"] != "normal":
            continue
        if w.day % 3 == 0 and w.npcs[pat]["medicine_days"] <= 1 and w.medicine_stock > 0 and w.money(nid) >= MEDICINE_PRICE + 10:
            w.transfer(nid, "bai", MEDICINE_PRICE)
            w.medicine_stock -= 1
            w.npcs[pat]["medicine_days"] += 3
            w.add_fact("medicine", {"giver": nid, "receiver": pat}, place="pharmacy", secrecy="secret",
                       importance=2, known_by=[nid, "bai"])


# ---------------- 需要（驅動借錢、偷、求助） ----------------
def update_needs(w: World):
    for nid, n in w.npcs.items():
        if n["status"] != "normal" or n.get("bedridden"):
            n["needs"] = []
            continue
        needs = []
        for fam in w.family_of(nid):
            fn = w.npcs[fam]
            if fn["status"] == "normal" and fn.get("bedridden") and fn["medicine_days"] <= 1 and fn["health"] < 75:
                needs.append({"type": "medicine", "amount": MEDICINE_PRICE, "for": fam, "cause": last_fact_about(w, fam, ("worse", "ill"))})
        if n["condition"] in ("ill", "injured") and n["health"] < 60:
            needs.append({"type": "medicine", "amount": DOCTOR_FEE, "for": nid,
                          "cause": last_fact_about(w, nid, ("ill", "debt_beating", "fight", "dog_bite"))})
        if n.get("landlord") and n.get("employed", True) and (7 - w.day % 7) <= 2 and n["money"] < n["rent"]:
            needs.append({"type": "rent", "amount": n["rent"] - n["money"], "cause": last_fact_about(w, nid, ("rent_unpaid", "fire"))})
        for ln in w.open_loans(borrower=nid):
            if ln["due_day"] - w.day <= 2 and n["money"] < ln["due_amount"] and not ln.get("garnish"):
                needs.append({"type": "debt", "amount": ln["due_amount"] - n["money"], "loan": ln["id"], "cause": ln.get("fact")})
        if n.get("hungry_days", 0) >= 2:
            needs.append({"type": "food", "amount": 10})
        # 賭徒輸光了想翻本：這是債務最常見的來源
        recent_losses = [f for f in n.get("losses", []) if w.facts.get(f, {}).get("day", 0) >= w.day - 3]
        if n["traits"]["vice"] >= 6 and n["money"] < 10 and recent_losses and not w.open_loans(borrower=nid, lender="qian"):
            needs.append({"type": "stake", "amount": 40, "cause": recent_losses[-1]})
        n["needs"] = needs
        # 把「有難處」這件事變成一條事實（自己和家人知道；交情夠的人問得出來）
        for nd in needs:
            key = f"need:{nd['type']}"
            if n.get("need_fact", {}).get(key) and w.facts.get(n["need_fact"][key], {}).get("day", 0) >= w.day - 6:
                continue
            fid = w.add_fact("need", {"who": nid}, data={"text": T.NEED_TEXT[nd["type"]], "need": nd["type"]},
                             secrecy="private", importance=3 if nd["type"] in ("medicine", "debt") else 2,
                             causes=[nd.get("cause")],
                             known_by=[nid] + [f for f in w.family_of(nid) if w.npcs[f]["status"] == "normal"] +
                             [o for o, on in w.npcs.items() if o != nid and on["status"] == "normal"
                              and on["opinions"].get(nid, 0) >= 55], log=False)
            n.setdefault("need_fact", {})[key] = fid


def last_fact_about(w: World, nid: str, types) -> str | None:
    for fid in reversed(list(w.npcs[nid]["knows"]) if nid in w.npcs else []):
        f = w.facts.get(fid)
        if f and f["type"] in types and nid in f["roles"].values():
            return fid
    return None


def unmet_need(n: dict) -> dict | None:
    for nd in n.get("needs", []):
        if nd["amount"] > n["money"]:
            return nd
    return None


# ---------------- 竊案：失主隔天發現，報官 ----------------
def discover_thefts(w: World):
    for fid in list(w.flags.get("_undiscovered", [])):
        f = w.facts[fid]
        victim = f["roles"]["victim"]
        rid = w.add_fact("theft_report", {"victim": victim}, place=f["place"],
                         data={"amount": f["data"]["amount"], "crime": fid, "thief": f["roles"]["thief"]},
                         secrecy="public", importance=3, causes=[fid], known_by=[victim] if victim != "player" else [])
        if victim == "player":
            w.learn("player", rid, "self")
            beat(w, "notice", f"你摸了摸錢袋，心裡一沉——少了{f['data']['amount']}文。", rid)
        elif victim in w.npcs and w.npcs[victim]["status"] == "normal" and w.opinion(victim, "zhao") >= -30:
            w.learn("zhao", rid, victim)
        w.flags.setdefault("_town_news", []).append(rid)
    w.flags["_undiscovered"] = []


def investigate(w: World):
    if not w.free("zhao"):
        return
    lazy = 20 if w.npcs["zhao"].get("lazy") else 0
    for case in w.cases.values():
        if case["status"] != "open":
            continue
        if w.day - case["opened_day"] > 10:
            case["status"] = "cold"
            continue
        scores = reactions.suspicion(w, case)
        if not scores:
            continue
        suspect, score = max(scores.items(), key=lambda kv: kv[1])
        if suspect != "player" and (suspect not in w.npcs or w.npcs[suspect]["status"] != "normal"):
            continue
        if score >= 60 + lazy and w.roll(30 + score / 2 - lazy):
            schedule(w, w.rng.choice([1, 2]), "arrest", case=case["id"], suspect=suspect)
            case["status"] = "pending_arrest"


def do_arrest(w: World, case_id: str, suspect: str):
    case = w.cases.get(case_id)
    if not case or case["status"] != "pending_arrest" or not w.free("zhao"):
        if case:
            case["status"] = "open"
        return
    charge = {"theft": "偷竊", "theft_report": "偷竊", "caught_stealing": "偷竊", "debt_beating": "傷人", "act": "傷人",
              "fight": "鬥毆傷人", "smuggling": "私運"}.get(case["type"], "犯事")
    if suspect == "player":
        if w.player.get("jailed_until", 0) >= w.day:
            return
        loc = w.player["location"]
        days = w.rng.randint(2, 3)
        w.player["jailed_until"] = w.day + days
        w.player["location"] = "yamen"
        fine = w.transfer("player", "zhao", 20)
        fid = w.add_fact("arrest", {"guard": "zhao", "suspect": "player"}, place=loc, data={"charge": charge},
                         importance=4, causes=[case["crime"]], witnesses=witnesses_at(w, loc), known_by=["zhao"])
        w.learn("player", fid, "self")
        beat(w, "witness", f"趙捕頭攔住你，鐵尺往你肩上一搭：「有人看見了。跟我走一趟吧。」你被押進巡檢所的拘房，身上被搜走了{fine}文。", fid)
    else:
        n = w.npcs[suspect]
        if n["status"] != "normal":
            case["status"] = "open"
            return
        loc = n["location"]
        n["status"] = "jailed"
        n["jail_until"] = w.day + (w.rng.randint(5, 8) if case["type"] == "smuggling" else w.rng.randint(3, 5))
        w.transfer(suspect, "zhao", 20)
        fid = w.add_fact("arrest", {"guard": "zhao", "suspect": suspect}, place=loc, data={"charge": charge},
                         importance=4, causes=[case["crime"]], witnesses=witnesses_at(w, loc), known_by=["zhao", suspect])
        w.flags.setdefault("_town_news", []).append(fid)
        n["location"] = "yamen"
        w.stress(suspect, 30)
        emit(w, fid, loc)
        if case.get("true_culprit") == suspect:
            crime = w.facts[case["crime"]]
            amt = crime["data"].get("amount", 0)
            if amt and case.get("victim") in w.npcs:
                w.transfer(suspect, case["victim"], amt)
        else:
            # 冤枉：被抓的人會恨那些他知道在背後說他的人
            for nid2, info in w.npcs["zhao"]["knows"].items():
                f2 = w.facts.get(nid2)
                if f2 and w.culprit_of(f2) == suspect and info["src"] in w.npcs:
                    w.adjust_opinion(suspect, info["src"], -40)
            if suspect != "player":
                w.adjust_opinion(suspect, "zhao", -40)
    case["status"] = "closed"
    case["arrested"] = suspect


# ---------------- 行商 ----------------
def trader(w: World):
    hu = w.npcs.get("hu")
    if not hu or hu["status"] == "dead":
        return
    if hu["status"] == "normal" and hu.get("leave_day", 0) <= w.day:
        hu["status"] = "away"
        hu["location"] = None
        w.trader_next_day = w.day + w.rng.randint(4, 6)
        return
    if hu["status"] == "away" and w.day >= w.trader_next_day:
        hu["status"] = "normal"
        hu["leave_day"] = w.day + 2
        w.medicine_stock = min(MAX_MED_STOCK, w.medicine_stock + w.rng.randint(3, 5))
        w.prosperity = min(90, w.prosperity + 8)
        hu["money"] += 100
        fid = w.add_fact("trader", {"trader": "hu"}, place="gate", importance=2, known_by=["hu", "wu", "bai"])
        w.flags.setdefault("_town_news", []).append(fid)
        news = w.add_fact("news", {}, data={"text": w.rng.choice(T.OUTSIDE_NEWS)}, importance=1, known_by=["hu"])
        if w.player["location"] == "gate":
            emit(w, fid, "gate")


# ---------------- 調皮的故事編織者（白盒版：觸發與內容都由骰子決定，只對玩家隱藏） ----------------
def mischief(w: World):
    if not w.roll(MISCHIEF_CHANCE, lo=0.5, hi=50):
        return
    kinds = ["rain", "found_purse", "dog_bite", "recovery", "fire", "stranger_rumor", "letter", "windfall_loss"]
    kind = w.rng.choice(kinds)
    alive = [i for i, n in w.npcs.items() if n["status"] == "normal" and not n.get("bedridden")]
    if not alive:
        return
    who = w.rng.choice(alive)
    entry = {"day": w.day, "kind": kind, "who": who}
    if kind == "rain":
        w.weather = "雨"
        w.prosperity = max(10, w.prosperity - 10)
    elif kind == "found_purse":
        amt = w.rng.randint(3, 7) * 10
        w.add_money(who, amt)
        w.add_fact("found_purse", {"who": who}, data={"amount": amt}, secrecy="private", importance=2, known_by=[who])
    elif kind == "dog_bite":
        w.hurt(who, 20)
        w.npcs[who]["condition"] = "injured"
        w.add_fact("dog_bite", {"who": who}, importance=1, known_by=[who])
    elif kind == "recovery":
        sick = [i for i, n in w.npcs.items() if n["status"] == "normal" and (n.get("bedridden") or n["condition"] != "healthy")]
        if sick:
            who = w.rng.choice(sick)
            entry["who"] = who
            w.heal(who, 30)
            w.npcs[who]["medicine_days"] += 2
            w.add_fact("recovered", {"who": who}, importance=2, known_by=[who] + w.family_of(who))
    elif kind == "fire":
        props = [p for p in w.properties.values() if p["owner"] in w.npcs and w.free(p["owner"])]
        if props:
            p = w.rng.choice(props)
            loss = w.money(p["owner"]) // 3
            w.add_money(p["owner"], -loss)
            w.stress(p["owner"], 25)
            fid = w.add_fact("fire", {"owner": p["owner"]}, place=p["place"], data={"property": p["name"]},
                             importance=3, known_by=[p["owner"]], witnesses=witnesses_at(w, p["place"]))
            w.flags.setdefault("_town_news", []).append(fid)
            entry["who"] = p["owner"]
    elif kind == "stranger_rumor":
        # 一條無中生有的傳聞：某個人「被看見」做了某件事。沒有原始事實，純屬子虛烏有。
        victim = w.rng.choice(alive)
        accused = w.rng.choice([a for a in alive if a != victim] or alive)
        fid = w.add_fact("accusation", {"accuser": w.rng.choice(alive), "accused": accused, "victim": victim},
                         secrecy="public", importance=2, truth=False, known_by=[w.rng.choice(alive)])
        entry.update({"accused": accused, "victim": victim})
    elif kind == "letter":
        w.stress(who, -30)
        w.add_fact("letter", {"who": who}, importance=1, known_by=[who])
    elif kind == "windfall_loss":
        loss = w.money(who) // 4
        w.add_money(who, -loss)
        w.stress(who, 10)
    w.mischief_log.append(entry)
    beat(w, "mischief", w.rng.choice(T.MISCHIEF_NOTICE))


# ---------------- 新面孔（懶惰生成的最小版本） ----------------
def drifters(w: World):
    pop = sum(1 for n in w.npcs.values() if n["status"] in ("normal", "jailed") and not n.get("traveler"))
    if (pop < 18 and w.rng.random() < 0.18) or (pop < 26 and w.rng.random() < 0.025):
        spawn_drifter(w)


def spawn_drifter(w: World, role_index: int | None = None) -> str | None:
    w.drifter_seq += 1
    nid = f"d{w.drifter_seq}"
    role, work, traits, look = DRIFTER_ROLES[role_index if role_index is not None else w.rng.randrange(len(DRIFTER_ROLES))]
    from .content.nature import DRIFTER_NATURE
    name = w.rng.choice(DRIFTER_SURNAMES) + w.rng.choice(DRIFTER_GIVEN)
    base = {"kind": 5, "greed": 5, "temper": 5, "courage": 5, "honesty": 5, "gossip": 4, "pride": 5, "vice": 3}
    base.update(traits)
    for k in base:
        base[k] = max(0, min(10, base[k] + w.rng.randint(-2, 2)))
    spec = {
        "name": name, "call": name, "aliases": [name], "role": role, "home": "temple", "work": work,
        "schedule": ["temple", work, work, "tavern", "den" if base["vice"] >= 5 else "tavern", "temple"],
        "traits": base, "money": (5, 30), "income": 6, "appearance": look,
        "persona": f"剛到青石鎮的{role}，沒人知道底細。",
    }
    n = make_npc(w, nid, spec)
    n["voice_key"] = "generic"
    n["location"] = "gate"
    w.npcs[nid] = n
    domains, senses, kinds = DRIFTER_NATURE.get(role, ([], {}, []))
    mind.init_mind(n, domains, senses)
    for kind in kinds:
        tid = mind.add_thing(w, kind, host=nid, origin="arrival")
        noticed = mind.noticeable(w, n, w.things[tid], contact=True)
        if noticed:
            mind.believe_thing(w, nid, tid, noticed, "self")
    fid = w.add_fact("arrival", {"who": nid}, place="gate", data={"role": role}, importance=1,
                     known_by=[nid, "wu"], witnesses=witnesses_at(w, "gate", exclude=(nid,)))
    emit(w, fid, "gate")
    return nid
