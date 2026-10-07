"""固定的世界情境：每次餵給模型的世界條件都一樣（同 seed、同時辰天氣、同一批人在同一個地方、同樣的動作）。

片段（beats）一律由真正的遊戲動作產生（`player.perform`），不是手寫的假片段——
這樣測到的就是玩家實際會遇到的輸入。模型的輸出永遠不會回饋進世界，所以每個情境的輸入序列是確定的。
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Callable

from rpg import player as P
from rpg.content.npcs import NPCS
from rpg.world import TICKS_PER_DAY, TICKS_PER_PERIOD, new_world


class ScenarioError(RuntimeError):
    pass


@dataclass
class Scenario:
    name: str
    about: str
    setup: Callable
    script: list = field(default_factory=list)        # 動作 id 或前綴，依序執行
    policy: Callable | None = None                    # 長時間遊玩用：(acts, rng) -> 動作 id
    turns: int = 0                                    # policy 模式：要湊到幾個「送給說書人」的回合
    seed: int = 0
    expect: dict = field(default_factory=dict)


def stage(seed: int, bg: str, place: str, period: int, weather: str, cast: dict[str, str], met=()):
    """建一個世界，把時間撥到某個時辰的開頭、指定天氣，讓指定的人站在指定的地方；不在名單上的人離開這個地點。"""
    w = new_world(seed, bg)
    w.pending = None
    w.clock = (w.day - 1) * TICKS_PER_DAY + period * TICKS_PER_PERIOD
    w.weather = weather
    p = w.player
    p["location"] = place
    p["talking_to"] = None
    for nid, n in w.npcs.items():
        if nid in cast:
            n["status"] = "normal"
            n["bedridden"] = False
            n["location"] = cast[nid]
        elif n["location"] == place:
            n["location"] = n["home"] if n["home"] != place else "street"
    for nid in met:
        if nid not in p["met"]:
            p["met"].append(nid)
    return w


def choose(w, step, rng=None, policy=None) -> str | None:
    acts = [a["id"] for a in P.available_actions(w)]
    if w.pending:          # 世界不等人：途中撞見的介入，一律選第一個選項（確定性）
        return acts[0]
    if policy:
        return policy(acts, rng)
    if step in acts:
        return step
    for a in acts:
        if a.startswith(step + ":") or a.startswith(step):
            return a
    return None   # 世界自己在動：例如要談話的人剛好走開了。這一步就跳過（確定性的），覆蓋度由快速測試把關


# ---------------------------------------------------------------- 情境
def _arrive():
    return stage(101, "drifter", "street", 1, "晴", {"wu": "gate"})


def _dialogue():
    return stage(102, "scholar", "gate", 2, "陰", {"wu": "gate"})


def _absent():
    w = stage(103, "peddler", "gate", 1, "晴", {"wu": "gate", "sun": "inn"}, met=("sun",))
    wu = w.npcs["wu"]
    wu["traits"]["gossip"] = 10
    wu["opinions"]["player"] = 90
    wu["opinions"]["sun"] = 0
    fid = w.add_fact("theft_report", {"victim": "sun"}, place="inn", data={"amount": 27, "crime": None},
                     secrecy="public", importance=4, known_by=["wu"], log=False)
    w.facts[fid]["day"] = w.day - 1
    return w


def _crowd():
    return stage(104, "drifter", "tavern", 3, "雨",
                 {"wang": "tavern", "ayue": "tavern", "liu6": "tavern", "zhou": "tavern"},
                 met=("wang", "ayue", "liu6", "zhou"))


def _private():
    return stage(105, "heir", "tavern", 2, "晴", {"ayue": "tavern", "wang": "tavern"})


def _time(period, weather):
    return lambda: stage(110 + period, "drifter", "gate", period, weather, {"wu": "gate"})


WEIGHTS = {"talk": 3, "chat": 3, "ask_news": 2, "ask_about": 1, "ask_self": 1, "look": 2, "wait": 1, "move": 2,
           "drink": 1, "end_talk": 1, "work_dock": 0.5, "rest_inn": 0.3, "sleep_temple": 0.3, "notices": 0.5,
           "give": 0.3, "tell": 0.5, "jail_wait": 1}


def play_policy(acts, rng):
    """長時間遊玩：像一個好奇、愛聊天的玩家。不偷東西（免得一直被關），其他都可能做。"""
    opts = [(a, WEIGHTS.get(a.split(":")[0], 0.2)) for a in acts if not a.startswith(("steal", "say", "inventory"))]
    total = sum(wt for _, wt in opts)
    x = rng.random() * total
    for a, wt in opts:
        x -= wt
        if x <= 0:
            return a
    return opts[-1][0]


def long_turns() -> int:
    return int(os.environ.get("RPG_LLM_LONG_TURNS", "60"))


TIME_SWEEP = [(0, "晴"), (1, "雨"), (2, "陰"), (3, "晴"), (4, "雨"), (5, "晴")]

SCENARIOS = [
    Scenario("arrive_then_stay", "剛走進鎮口，接著在同一個地方待了好幾個回合（場景不該被重新介紹）",
             _arrive, ["move:gate", "look", "talk:wu", "chat", "ask_news", "end_talk", "wait", "look"],
             expect={"arrival_first": True}),
    Scenario("dialogue_only", "一連串只有台詞的回合（應該完全不經過模型）",
             _dialogue, ["talk:wu", "ask_self", "ask_self", "ask_self"], expect={"dialogue_only": True}),
    Scenario("absent_mentioned", "吳伯在場，談到不在場的孫掌櫃（孫掌櫃不能被寫成走過來）",
             _absent, ["talk:wu", "ask_about:sun", "chat"], expect={"absent": "孫掌櫃"}),
    Scenario("crowded_tavern", "傍晚下雨的酒館，好幾個人在場", _crowd,
             ["look", "drink", "talk:wang", "chat", "end_talk", "talk:ayue", "chat"], expect={"crowd": 3}),
    Scenario("private_persona", "在場的人有私密設定、世界裡有玩家不知道的祕密（都不能被講出來）",
             _private, ["talk:ayue", "chat", "ask_self", "chat", "end_talk", "look"], expect={"private": True}),
] + [
    Scenario(f"time_{p}", f"時間一致性：{['清晨', '上午', '午後', '傍晚', '入夜', '深夜'][p]}，{wx}",
             _time(p, wx), ["talk:wu", "chat", "end_talk"], expect={"period": p, "weather": wx})
    for p, wx in TIME_SWEEP
] + [
    Scenario("long_play", "固定 seed 連續遊玩（看長時間下的退回率與越界）", lambda: new_world(7, "drifter"),
             policy=play_policy, seed=2026, turns=-1),
]

BY_NAME = {s.name: s for s in SCENARIOS}


def iterate(sc: Scenario, action_cap: int = 600):
    """跑一個情境，逐回合產生 (world, 動作 id, beats)。世界在 yield 之後才會繼續往前；
    policy 模式會一直玩下去（最多 action_cap 個動作），由呼叫端決定何時停。"""
    w = sc.setup()
    rng = random.Random(sc.seed)
    if sc.policy:
        for _ in range(action_cap):
            aid = choose(w, None, rng, sc.policy)
            yield w, aid, P.perform(w, aid)
        return
    for step in sc.script:
        while w.pending:
            aid = choose(w, step)
            yield w, aid, P.perform(w, aid)
        aid = choose(w, step)
        if aid:
            yield w, aid, P.perform(w, aid)


def personas_present(w) -> list[str]:
    return [n["persona"] for i, n in w.npcs.items() if i in NPCS and n.get("persona")]
