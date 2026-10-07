"""命令列工具（開發／除錯／備用介面）。

  python -m rpg.cli sim --seed 7 --days 60 [--chains] [--all]   不需玩家，讓世界自己跑，印出編年史（會劇透）
  python -m rpg.cli play [--seed 7]                              終端機版遊玩（網頁介面的備用品）
"""

from __future__ import annotations

import argparse
import sys

from . import devtools, sim
from .game import Game
from .narrator import Narrator
from .player import ActionError, BACKGROUNDS
from .world import new_world

GROUP_TITLES = {"pending": "此刻", "people": "這裡的人", "talk": "交談", "ask": "打聽", "tell": "說出你知道的事",
                "money": "錢與東西", "role": "其他", "accuse": "指認", "here": "此地", "move": "前往", "self": "自己"}


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cmd_sim(a):
    w = new_world(a.seed, "drifter")
    w.player["location"] = "inn"
    for _ in range(a.days):
        sim.advance_to_next_dawn(w)
        w.pending = None
    s = devtools.summarize(w)
    print(f"seed={w.seed} day={s['day']} genes={s['genes']}")
    print(f"alive={s['alive']} dead={s['dead']} fled={s['fled']} jailed={s['jailed']} seized={s['owners']} max_chain={s['max_chain']}")
    types = None if a.all else {"death", "fled", "arrest", "theft", "caught_stealing", "debt_beating", "property_seized",
                                "evicted", "debt_transferred", "fight", "fired", "quit_job", "revenge_vow", "debt_paid_by",
                                "help_money", "fire", "arrival", "bribe"}
    for line in devtools.chronicle(w, types=types):
        print(line)
    if a.chains:
        print("\n== 最長的因果鏈 ==")
        for ch in devtools.longest_chains(w, 5):
            print("  " + "\n   → ".join(devtools.T.fact_text(w, w.facts[f]) for f in ch))
            print()


def read_choice(prompt: str, n: int) -> int | None:
    try:
        raw = input(prompt).strip()
    except EOFError:
        return None
    if raw in ("q", "quit", "exit"):
        return None
    if raw.isdecimal():
        try:
            k = int(raw)
        except ValueError:
            return -1
        return k if 1 <= k <= n else -1
    return -1


def show(resp):
    v = resp["view"]
    for b in v["beats"]:
        if b["kind"] == "ambient":
            print(f"  （{b['text']}）")
        else:
            print(b["text"])
    print(f"\n—— 第{v['day']}日 {v['period']}｜{v['location']['name']}｜{v['weather']}｜錢 {v['player']['money']} 文｜{v['player']['health_word']}")


def cmd_play(a):
    game = Game(save_dir=a.save_dir, narrator=Narrator(mode="off"), autosave=True)
    keys = list(BACKGROUNDS)
    for i, k in enumerate(keys, 1):
        print(f"{i}. {BACKGROUNDS[k]['name']}——{BACKGROUNDS[k]['desc']}")
    c = read_choice("選一個出身：", len(keys))
    if not c or c < 0:
        return
    resp = game.new(keys[c - 1], a.seed)
    while True:
        show(resp)
        acts = resp["view"]["actions"]
        group = None
        for i, x in enumerate(acts, 1):
            if x["group"] != group:
                group = x["group"]
                print(f"  [{GROUP_TITLES.get(group, group)}]")
            print(f"   {i:>2}. {x['label']}")
        c = read_choice("> ", len(acts))
        if c is None:
            print("（離開遊戲，進度已自動存檔）")
            return
        if c < 0:
            print("（請輸入清單上的數字，q 離開）")
            continue
        try:
            resp = game.act(acts[c - 1]["id"])
        except ActionError as e:
            print(f"（{e}）")


def main(argv=None):
    from .config import load_dotenv

    utf8_stdout()
    load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m rpg.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sim")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--days", type=int, default=60)
    s.add_argument("--chains", action="store_true")
    s.add_argument("--all", action="store_true")
    p = sub.add_parser("play")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--save-dir", default=None)
    a = ap.parse_args(argv)
    {"sim": cmd_sim, "play": cmd_play}[a.cmd](a)


if __name__ == "__main__":
    main()
