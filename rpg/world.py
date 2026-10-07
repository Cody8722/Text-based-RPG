"""世界狀態：唯一的 authoritative state。

設計原則（吸收自 docs/reviews/ 的歷次審查）：
- 所有會改變遊戲因果的東西都在這裡，全部是 JSON 原生型別（dict/list/int/str/bool），可以整包存檔、整包比對。
- 所有隨機都走 world.rng（以 seed 建立），存檔時連 rng 狀態一起存，所以同樣 seed + 同樣玩家動作 = 同樣的世界。
- 「事實」(facts) 由 Python 產生，是世界記憶的唯一來源。LLM 寫的文字永遠不會變成事實。
- 知識是結構化的：誰知道哪條事實、從誰那裡聽來的。傳聞是另一條 truth=False 的事實，指向原始事實。
"""

from __future__ import annotations

import copy
import json
import random

from .content.npcs import FAMILY, NPCS, RELATIONS, TENANTS

TICKS_PER_PERIOD = 2           # 一個時辰 = 2 刻
PERIODS_PER_DAY = 6
TICKS_PER_DAY = TICKS_PER_PERIOD * PERIODS_PER_DAY
SAVE_VERSION = 1

OPINION_MIN, OPINION_MAX = -100, 100
HEALTH_MAX = 100


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class World:
    """世界狀態容器。屬性皆可 JSON 序列化（rng 例外，存檔時轉成 state list）。"""

    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.world_id = f"{self.rng.getrandbits(64):016x}"
        self.clock = 0
        self.npcs: dict[str, dict] = {}
        self.player: dict = {}
        self.facts: dict[str, dict] = {}
        self.fact_seq = 0
        self.loans: dict[str, dict] = {}
        self.loan_seq = 0
        self.cases: dict[str, dict] = {}
        self.case_seq = 0
        self.properties: dict[str, dict] = {}
        self.event_log: list[str] = []      # 真實事件的 fact id，依發生順序（開發者用）
        self.feed: list[dict] = []          # 這一回合玩家看得到的片段（beats）
        self.pending: dict | None = None    # 玩家在場、需要玩家決定是否介入的情況
        self.weather = "晴"
        self.prosperity = 50
        self.medicine_stock = 3
        self.trader_next_day = 4
        self.genes: list[dict] = []         # 這個世界抽到的基因（開發者用，絕不送到前端）
        self.mischief_log: list[dict] = []  # 調皮事件的隱藏日誌
        self.stats: dict[str, int] = {}
        self.drifter_seq = 0
        self.flags: dict[str, bool] = {}
        self.day_offset = 0                 # 玩家抵達前，世界先自己跑了幾天

    def display_day(self, d: int) -> int:
        return d - self.day_offset

    # ---------------- 時間 ----------------
    @property
    def day(self) -> int:
        return self.clock // TICKS_PER_DAY + 1

    @property
    def period(self) -> int:
        return (self.clock % TICKS_PER_DAY) // TICKS_PER_PERIOD

    # ---------------- 骰子（白盒） ----------------
    def roll(self, pct: float, lo: float = 3, hi: float = 97) -> bool:
        """判定：成功率 pct（%），永遠夾在 lo～hi 之間——世界上沒有絕對的 0% 或 100%。"""
        return self.rng.random() * 100 < clamp(pct, lo, hi)

    def pick_weighted(self, items: list[tuple[object, float]]):
        items = [(x, w) for x, w in items if w > 0]
        if not items:
            return None
        total = sum(w for _, w in items)
        r = self.rng.random() * total
        for x, w in items:
            r -= w
            if r <= 0:
                return x
        return items[-1][0]

    def bump(self, key: str, n: int = 1):
        self.stats[key] = self.stats.get(key, 0) + n

    # ---------------- 實體 ----------------
    def ent(self, ref: str) -> dict:
        return self.player if ref == "player" else self.npcs[ref]

    def name(self, ref: str) -> str:
        if ref == "player":
            return "你"
        n = self.npcs.get(ref)
        return n["call"] if n else ref

    def active(self, npc_id: str) -> bool:
        n = self.npcs.get(npc_id)
        return bool(n) and n["status"] in ("normal", "jailed")

    def free(self, npc_id: str) -> bool:
        """在鎮上、可以自由行動（沒被關、沒死、沒走）。"""
        n = self.npcs.get(npc_id)
        return bool(n) and n["status"] == "normal"

    def present_npcs(self, loc: str) -> list[str]:
        return [i for i, n in self.npcs.items() if n["status"] == "normal" and n["location"] == loc]

    # ---------------- 金錢（永不為負） ----------------
    def money(self, ref: str) -> int:
        return self.ent(ref)["money"]

    def add_money(self, ref: str, amount: int) -> int:
        e = self.ent(ref)
        before = e["money"]
        e["money"] = max(0, before + int(amount))
        return e["money"] - before

    def transfer(self, src: str, dst: str, amount: int) -> int:
        amount = max(0, min(int(amount), self.money(src)))
        self.ent(src)["money"] -= amount
        self.ent(dst)["money"] += amount
        return amount

    # ---------------- 健康 ----------------
    def hurt(self, ref: str, amount: int) -> int:
        e = self.ent(ref)
        e["health"] = clamp(e["health"] - int(amount), 0, HEALTH_MAX)
        return e["health"]

    def heal(self, ref: str, amount: int) -> int:
        e = self.ent(ref)
        e["health"] = clamp(e["health"] + int(amount), 0, HEALTH_MAX)
        return e["health"]

    # ---------------- 人際 ----------------
    def opinion(self, who: str, of: str) -> int:
        if who == "player":
            return 0
        return self.npcs[who]["opinions"].get(of, 0)

    def adjust_opinion(self, who: str, of: str, delta: int):
        if who == "player" or who == of or who not in self.npcs:
            return
        ops = self.npcs[who]["opinions"]
        ops[of] = int(clamp(ops.get(of, 0) + int(delta), OPINION_MIN, OPINION_MAX))

    def stress(self, npc_id: str, delta: int):
        n = self.npcs.get(npc_id)
        if n:
            n["stress"] = int(clamp(n["stress"] + int(delta), 0, 100))

    def family_of(self, npc_id: str) -> list[str]:
        return list(self.npcs[npc_id].get("family", [])) if npc_id in self.npcs else []

    # ---------------- 事實與知識 ----------------
    def add_fact(
        self,
        ftype: str,
        roles: dict[str, str],
        place: str | None = None,
        data: dict | None = None,
        secrecy: str = "public",
        importance: int = 2,
        causes: list[str] | tuple = (),
        truth: bool = True,
        rumor_of: str | None = None,
        witnesses: list[str] | tuple = (),
        known_by: list[str] | tuple = (),
        log: bool = True,
    ) -> str:
        self.fact_seq += 1
        fid = f"f{self.fact_seq}"
        self.facts[fid] = {
            "id": fid,
            "type": ftype,
            "day": self.day,
            "period": self.period,
            "roles": dict(roles),
            "place": place,
            "data": dict(data or {}),
            "secrecy": secrecy,
            "importance": importance,
            "causes": [c for c in causes if c and c in self.facts],
            "truth": truth,
            "rumor_of": rumor_of,
        }
        if truth and log:
            self.event_log.append(fid)
            self.bump(f"event:{ftype}")
        for w in witnesses:
            self.learn(w, fid, "witness")
        for k in known_by:
            self.learn(k, fid, "self")
        return fid

    def knows(self, who: str, fid: str) -> bool:
        return fid in self.ent(who)["knows"]

    def learn(self, who: str, fid: str, src: str) -> bool:
        """讓 who 知道 fid。回傳是否是新知道的。知道後會觸發白盒反應（見 reactions.on_learn）。"""
        if who != "player" and who not in self.npcs:
            return False
        e = self.ent(who)
        if fid in e["knows"]:
            return False
        e["knows"][fid] = {"day": self.day, "src": src}
        from . import reactions  # 延遲匯入，避免循環

        reactions.on_learn(self, who, fid, src)
        return True

    def facts_known(self, who: str) -> list[dict]:
        return [self.facts[f] for f in self.ent(who)["knows"] if f in self.facts]

    def culprit_of(self, fact: dict) -> str | None:
        r = fact["roles"]
        for key in ("thief", "attacker", "culprit", "accused"):
            if key in r:
                return r[key]
        return None

    def root_fact(self, fid: str) -> dict:
        f = self.facts[fid]
        seen = set()
        while f.get("rumor_of") and f["rumor_of"] in self.facts and f["id"] not in seen:
            seen.add(f["id"])
            f = self.facts[f["rumor_of"]]
        return f

    # ---------------- 借貸 ----------------
    def add_loan(self, lender: str, borrower: str, amount: int, days: int, interest_pct: int,
                 guarantor: str | None = None, secured: str | None = None, cause: str | None = None,
                 fact_id: str | None = None) -> str:
        self.loan_seq += 1
        lid = f"L{self.loan_seq}"
        self.loans[lid] = {
            "id": lid,
            "lender": lender,
            "borrower": borrower,
            "principal": int(amount),
            "due_amount": int(round(amount * (100 + interest_pct) / 100)),
            "due_day": self.day + days,
            "status": "open",       # open / repaid / defaulted / forgiven / transferred
            "stage": 0,             # 逾期催收階段（錢三爺的帳）
            "guarantor": guarantor,
            "secured": secured,     # 用哪個產業抵押
            "fact": fact_id,
            "cause": cause,
            "opened_day": self.day,
        }
        return lid

    def open_loans(self, borrower: str | None = None, lender: str | None = None) -> list[dict]:
        out = []
        for ln in self.loans.values():
            if ln["status"] != "open":
                continue
            if borrower and ln["borrower"] != borrower:
                continue
            if lender and ln["lender"] != lender:
                continue
            out.append(ln)
        return out

    # ---------------- 序列化 ----------------
    _FIELDS = [
        "seed", "world_id", "clock", "npcs", "player", "facts", "fact_seq", "loans", "loan_seq",
        "cases", "case_seq", "properties", "event_log", "feed", "pending", "weather", "prosperity",
        "medicine_stock", "trader_next_day", "genes", "mischief_log", "stats", "drifter_seq", "flags", "day_offset",
    ]

    def to_dict(self) -> dict:
        d = {k: copy.deepcopy(getattr(self, k)) for k in self._FIELDS}
        st = self.rng.getstate()
        d["rng_state"] = [st[0], list(st[1]), st[2]]
        d["version"] = SAVE_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        w = cls.__new__(cls)
        for k in cls._FIELDS:
            setattr(w, k, copy.deepcopy(d[k]))
        w.rng = random.Random()
        st = d["rng_state"]
        w.rng.setstate((st[0], tuple(st[1]), st[2]))
        return w

    def state_hash(self) -> str:
        import hashlib

        d = self.to_dict()
        d.pop("feed", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------------- 建立世界 ----------------
def make_npc(world: World, npc_id: str, spec: dict) -> dict:
    lo, hi = spec.get("money", (10, 20))
    return {
        "id": npc_id,
        "name": spec["name"],
        "call": spec["call"],
        "aliases": list(spec.get("aliases", [spec["call"]])),
        "role": spec["role"],
        "home": spec["home"],
        "work": spec["work"],
        "schedule": list(spec["schedule"]),
        "traits": dict(spec["traits"]),
        "money": world.rng.randint(lo, hi),
        "income": spec.get("income", 0),
        "wage_from": spec.get("wage_from"),
        "wage": spec.get("wage", 0),
        "rent": spec.get("rent", 0),
        "health": HEALTH_MAX,
        "stress": world.rng.randint(5, 25),
        "status": "normal",       # normal / jailed / fled / dead / away
        "location": spec["schedule"][0],
        "opinions": {},
        "knows": {},
        "family": [],
        "bedridden": bool(spec.get("bedridden", False)),
        "condition": "ill" if spec.get("bedridden") else "healthy",   # healthy / ill / injured
        "medicine_days": 0,
        "jail_until": 0,
        "drunk_until": -1,
        "employed": True,
        "traveler": bool(spec.get("traveler", False)),
        "met_player": False,
        "talks_today": 0,
        "last_talk_day": 0,
        "appearance": spec.get("appearance", ""),
        "persona": spec.get("persona", ""),
        "voice_key": npc_id if npc_id in NPCS else "generic",
        "grief_until": 0,
        "unpaid_rent": 0,
        "blame": {},
        "plans": [],
    }


def new_world(seed: int | None = None, background: str | None = None) -> World:
    from . import genes, player as player_mod

    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    w = World(seed)
    for nid, spec in NPCS.items():
        w.npcs[nid] = make_npc(w, nid, spec)
    for a, b, v in RELATIONS:
        w.npcs[a]["opinions"][b] = v
    for a, b in FAMILY:
        w.npcs[a]["family"].append(b)
        w.npcs[b]["family"].append(a)
    w.npcs["linshen"]["health"] = w.rng.randint(48, 62)
    w.npcs["linshen"]["decay"] = w.rng.choice([3, 4, 4, 5])
    w.npcs["hu"]["status"] = "away"
    w.npcs["hu"]["location"] = None
    w.properties = {
        "tavern": {"name": "老王酒館", "owner": "wang", "place": "tavern"},
        "inn": {"name": "孫記客棧", "owner": "sun", "place": "inn"},
        "den": {"name": "後巷賭坊", "owner": "qian", "place": "den"},
        "stall_chen": {"name": "陳伯的雜貨攤", "owner": "chenbo", "place": "market"},
        "stall_su": {"name": "蘇娘子的繡攤", "owner": "su", "place": "market"},
        "pharmacy": {"name": "濟世堂", "owner": "bai", "place": "pharmacy"},
        "dojo": {"name": "鐵家武館", "owner": "tie", "place": "dojo"},
        "boat": {"name": "老何的船", "owner": "laohe", "place": "dock"},
    }
    for tenant, landlord in TENANTS.items():
        w.npcs[tenant]["landlord"] = landlord
    w.trader_next_day = w.rng.randint(3, 5)
    w.player = player_mod.new_player(w, background)
    genes.apply_genes(w)
    from . import sim

    sim.place_npcs(w)
    warm_up(w, WARMUP_DAYS)
    return w


WARMUP_DAYS = 7


def warm_up(w: World, days: int):
    """玩家抵達前，讓鎮子先自己過幾天日子：恩怨、債務、八卦都已經在發酵。"""
    from . import player as player_mod, sim

    p = w.player
    p["arrived"] = False
    real_loc = p["location"]
    p["location"] = None
    for _ in range(days):
        sim.advance_to_next_dawn(w)
        w.pending = None
    p["location"] = real_loc
    p["arrived"] = True
    p["knows"] = {}
    p["money"] = player_mod.BACKGROUNDS[p["background"]]["money"]
    p["health"] = 100
    w.day_offset = w.day - 1
    w.feed = []
    sim.place_npcs(w)
