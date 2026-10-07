"""玩家視角投影：前端唯一能拿到的資料。

這是「不讓 UI 破壞世界未知性」的防線：
- 只放玩家角色能知道的東西：他看得到的人、外表看得出的狀態、他聽過的事、他自己的處境。
- 絕不放：NPC 的性格數值、金錢、好感度數字、別人知道什麼、事實的真假、基因、案件、未來排程。
- 事實只以「一句話」呈現，不帶 truth / data / roles 原始欄位。
tests/test_view_hiding.py 會掃整包輸出，確認沒有內部欄位外洩。
"""

from __future__ import annotations

from . import player as player_mod
from .content import text as T
from .content.locations import LOCATIONS, NIGHT_PERIODS, PERIODS


def src_label(w, src: str) -> str:
    if src in ("witness",):
        return "親眼所見"
    if src == "self":
        return "親身經歷"
    if src == "town":
        return "街坊傳聞"
    if src == "notice":
        return "告示"
    if src in w.npcs:
        return f"聽{w.name(src)}說"
    return "聽說"


def journal(w, limit: int = 80) -> list[dict]:
    out = []
    for fid, info in w.player["knows"].items():
        f = w.facts.get(fid)
        if not f or f["type"] in ("player_work",):
            continue
        people = sorted({w.name(r) for r in f["roles"].values() if r in w.npcs})
        out.append({
            "key": fid,
            "day": w.display_day(f["day"]),
            "text": T.fact_text(w, f),
            "source": src_label(w, info["src"]),
            "people": people,
        })
    out.sort(key=lambda e: (e["day"], e["key"]), reverse=True)
    return out[:limit]


def people(w) -> list[dict]:
    p = w.player
    out = []
    for nid in p["met"]:
        n = w.npcs.get(nid)
        if not n:
            continue
        seen = p["last_seen"].get(nid)
        status = None
        if n["status"] == "dead" and any(w.facts[f]["type"] == "death" and w.facts[f]["roles"].get("who") == nid
                                         for f in p["knows"] if f in w.facts):
            status = "已過世"
        elif n["status"] == "fled" and any(w.facts[f]["type"] == "fled" and w.facts[f]["roles"].get("who") == nid
                                           for f in p["knows"] if f in w.facts):
            status = "已離開青石鎮"
        elif n["status"] == "jailed" and any(w.facts[f]["type"] == "arrest" and w.facts[f]["roles"].get("suspect") == nid
                                             for f in p["knows"] if f in w.facts):
            status = "關在巡檢所"
        out.append({
            "key": nid,
            "name": n["call"],
            "role": n["role"],
            "attitude": T.attitude_word(w.opinion(nid, "player")),
            "last_seen": ({"day": w.display_day(seen["day"]), "place": LOCATIONS[seen["place"]]["name"]} if seen else None),
            "status": status,
        })
    return out


def present(w) -> list[dict]:
    p = w.player
    loc = p["location"]
    out = []
    for nid in w.present_npcs(loc):
        n = w.npcs[nid]
        known = nid in p["met"]
        out.append({
            "key": nid,
            "name": n["call"] if known else None,
            "label": n["call"] if known else f"一個{n['role']}",
            "look": T.demeanor(w, n),
            "appearance": n["appearance"],
        })
    return out


def player_panel(w) -> dict:
    p = w.player
    pw = player_mod.prowess(w)
    debts = [{"to": w.name(ln["lender"]), "amount": ln["due_amount"], "due_day": w.display_day(ln["due_day"])}
             for ln in w.open_loans(borrower="player")]
    owed = [{"by": w.name(ln["borrower"]), "amount": ln["due_amount"], "due_day": w.display_day(ln["due_day"])}
            for ln in w.open_loans(lender="player")]
    return {
        "background": p["bg_name"],
        "money": p["money"],
        "health": p["health"],
        "health_word": T.health_word(p["health"]),
        "prowess_word": "身手了得" if pw >= 8 else "練過幾年" if pw >= 6 else "略懂拳腳" if pw >= 4.5 else "手無縛雞之力",
        "medicine": p["inventory"].get("medicine", 0),
        "debts": debts,
        "owed": owed,
        "jailed": player_mod.jailed(w),
    }


def build(w, beats: list[dict] | None = None) -> dict:
    p = w.player
    loc = p["location"]
    night = w.period in NIGHT_PERIODS
    actions = player_mod.available_actions(w)   # 先算動作：NPC 走掉時這裡會結束對話
    talking = p.get("talking_to")
    convo = None
    if talking and talking in w.npcs:
        n = w.npcs[talking]
        convo = {"key": talking, "name": n["call"], "role": n["role"], "look": T.demeanor(w, n),
                 "attitude": T.attitude_word(w.opinion(talking, "player"))}
    pending = None
    if w.pending:
        pd = w.pending
        pending = {"kind": pd["kind"]}
    return {
        "day": w.display_day(w.day),
        "period": PERIODS[w.period],
        "night": night,
        "weather": w.weather,
        "location": {"key": loc, "name": LOCATIONS[loc]["name"], "desc": LOCATIONS[loc]["night" if night else "day"],
                     "exits": [LOCATIONS[x]["name"] for x in LOCATIONS[loc]["neighbors"]]},
        "present": present(w),
        "player": player_panel(w),
        "conversation": convo,
        "pending": pending,
        "actions": actions,
        "journal": journal(w),
        "people": people(w),
        "deeds": [T.fact_text(w, w.facts[f]) for f in reversed(p["deeds"][-30:]) if f in w.facts],
        "beats": [{"kind": b["kind"], "text": b["text"], **({"speaker": w.name(b["speaker"])} if b.get("speaker") else {})}
                  for b in (beats or [])],
        "turn": p["turn"],
    }
