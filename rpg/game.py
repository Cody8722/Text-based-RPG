"""遊戲 session：開局、繼續、執行動作、自動存檔、交辦說書工作。伺服器與 CLI 共用。"""

from __future__ import annotations

import json
import os
import random
import threading

from . import config
from . import player as player_mod
from . import sim, view
from .narrator import REWRITE_KINDS, Narrator
from .world import SAVE_VERSION, World, new_world



def intro_beats(w: World) -> list[dict]:
    bg = player_mod.BACKGROUNDS[w.player["background"]]
    return [
        {"kind": "intro", "text": "青石鎮"},
        {"kind": "intro", "text": f"你是一個{bg['name']}。{bg['desc']}"},
        {"kind": "intro", "text": f"官道走到盡頭，斑駁的城門出現在眼前。你摸了摸錢袋，裡頭只剩{w.player['money']}文。"
                                  "沒有人在等你，也沒有人知道你為什麼來——這個鎮子有它自己的日子要過。"},
        {"kind": "arrive", "text": "你來到鎮口。" + "斑駁的城門矗立在鎮子邊界，門邊的木牌上貼著幾張告示，有新有舊。"},
    ] + gate_hook(w)


def gate_hook(w: World) -> list[dict]:
    """守門的老兵打量新來的人，順口提一件鎮上最近的大事——從世界自己發生過的事裡挑，不是寫死的劇情。"""
    from .content import text as T

    if not w.free("wu") or w.npcs["wu"]["location"] != "gate":
        return []
    best = None
    for fid in reversed(w.event_log):
        f = w.facts[fid]
        if f["secrecy"] != "public" or f["importance"] < 3 or "wu" in f["roles"].values():
            continue
        if best is None or f["importance"] > best["importance"]:
            best = f
    if not best:
        return []
    w.learn("wu", best["id"], "town")
    w.learn("player", best["id"], "wu")
    return [{"kind": "speech", "text": f"城門洞裡，一個瘸腿的老兵從竹椅上抬起眼皮打量你：「外地來的？最近鎮上不太平——"
                                         f"{T.fact_text(w, best, speaker='wu')}你自己當心點。」"}]


class Game:
    def __init__(self, save_dir: str | None = None, narrator: Narrator | None = None, autosave: bool = True):
        self.save_dir = save_dir or config.save_dir()
        self.narrator = narrator if narrator is not None else Narrator()
        self.autosave = autosave
        self.lock = threading.RLock()
        self.world: World | None = None
        self.offered: list[str] = []

    @property
    def save_path(self) -> str:
        return os.path.join(self.save_dir, "autosave.json")

    def has_save(self) -> bool:
        return os.path.exists(self.save_path)

    def offer(self) -> list[dict]:
        with self.lock:
            self.offered = player_mod.offer_backgrounds(random.SystemRandom())
            return [{"key": k, "name": player_mod.BACKGROUNDS[k]["name"], "desc": player_mod.BACKGROUNDS[k]["desc"]}
                    for k in self.offered]

    def new(self, background: str, seed: int | None = None) -> dict:
        with self.lock:
            if background not in player_mod.BACKGROUNDS:
                raise player_mod.ActionError("沒有這種出身")
            self.world = new_world(seed, background)
            beats = intro_beats(self.world)
            self.save()
            return self.response(beats)

    def resume(self) -> dict:
        with self.lock:
            if self.world is None:
                self.world = self.load()
            if self.world is None:
                raise player_mod.ActionError("沒有可以繼續的存檔")
            beats = [{"kind": "intro", "text": "你回到了青石鎮。"}]
            return self.response(beats)

    def act(self, action_id: str, text: str | None = None) -> dict:
        with self.lock:
            if self.world is None:
                raise player_mod.ActionError("還沒開始遊戲")
            beats = player_mod.perform(self.world, action_id, text)
            self.save()
            return self.response(beats)

    def current(self) -> dict:
        with self.lock:
            if self.world is None:
                raise player_mod.ActionError("還沒開始遊戲")
            return self.response([])

    def response(self, beats: list[dict]) -> dict:
        w = self.world
        job = self.narrator.submit(w, beats) if beats else None
        return {"view": view.build(w, beats), "narration": job, "rewrite_kinds": sorted(REWRITE_KINDS)}

    # ---------- 存檔 ----------
    def save(self):
        if not self.autosave or self.world is None:
            return
        os.makedirs(self.save_dir, exist_ok=True)
        tmp = self.save_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.world.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, self.save_path)

    def load(self) -> World | None:
        if not self.has_save():
            return None
        try:
            with open(self.save_path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("version") != SAVE_VERSION:
                return None
            return World.from_dict(d)
        except (OSError, ValueError, KeyError):
            return None
