"""測試共用工具。所有外部服務（Ollama）都用本機假伺服器取代，不需要網路。"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rpg import player as player_mod  # noqa: E402
from rpg import sim  # noqa: E402
from rpg.world import World, new_world  # noqa: E402

VALID_STATUS = {"normal", "jailed", "fled", "dead", "away"}
ACTING_ROLES = ("thief", "attacker", "giver", "collector", "briber", "payer", "accuser")


def idle_days(w: World, days: int):
    """玩家待在客棧不動，讓世界自己跑。"""
    w.player["location"] = "inn"
    for _ in range(days):
        sim.advance_to_next_dawn(w)
        w.pending = None


def random_play(w: World, steps: int, rng: random.Random, avoid=("steal",)) -> list[str]:
    """用真實的 perform() 隨機遊玩；動作一律從當下的 available_actions 取（跟前端同一個來源）。"""
    done = []
    for _ in range(steps):
        acts = [a for a in player_mod.available_actions(w) if not a["id"].startswith(avoid) and a.get("hint") != "info"]
        a = rng.choice(acts)
        player_mod.perform(w, a["id"])
        done.append(a["id"])
    return done


def check_invariants(tc, w: World, where: str = ""):
    """世界在任何時刻都必須成立的事。tc 是 unittest.TestCase。"""
    msg = f"[seed={w.seed} day={w.day}{' ' + where if where else ''}]"
    p = w.player
    tc.assertIsInstance(p["money"], int, msg)
    tc.assertGreaterEqual(p["money"], 0, msg)
    tc.assertTrue(0 <= p["health"] <= 100, msg)
    tc.assertTrue(0 <= w.medicine_stock <= sim.MAX_MED_STOCK, msg)
    for nid, n in w.npcs.items():
        tc.assertIn(n["status"], VALID_STATUS, f"{msg} {nid}")
        tc.assertIsInstance(n["money"], int, f"{msg} {nid} money type")
        tc.assertGreaterEqual(n["money"], 0, f"{msg} {nid} money")
        tc.assertTrue(0 <= n["health"] <= 100, f"{msg} {nid} health")
        tc.assertTrue(0 <= n["stress"] <= 100, f"{msg} {nid} stress")
        for o, v in n["opinions"].items():
            tc.assertTrue(-100 <= v <= 100, f"{msg} {nid}->{o}")
        if n["status"] == "jailed":
            tc.assertEqual(n["location"], "yamen", f"{msg} {nid} jailed elsewhere")
        if n["status"] in ("dead", "fled", "away"):
            tc.assertIsNone(n["location"], f"{msg} {nid} gone but located")
        for fid, info in n["knows"].items():
            tc.assertIn(fid, w.facts, f"{msg} {nid} knows missing fact")
    for fid in p["knows"]:
        tc.assertIn(fid, w.facts, msg)
    for ln in w.loans.values():
        tc.assertIn(ln["status"], {"open", "repaid", "defaulted", "forgiven"}, msg)
        if ln["status"] == "open" and ln["borrower"] != "player" and not ln.get("garnish"):
            tc.assertGreater(ln["due_amount"], 0, msg)
    for prop in w.properties.values():
        tc.assertIn(prop["owner"], w.npcs, msg)
    # 事實：原因只能指向更早的事實；傳聞一定是假的，而且指回一條真的原始事實
    for fid, f in w.facts.items():
        num = int(fid[1:])
        for c in f["causes"]:
            tc.assertLess(int(c[1:]), num, f"{msg} {fid} caused by later {c}")
        if f["rumor_of"]:
            tc.assertFalse(f["truth"], f"{msg} rumor {fid} marked true")
            tc.assertTrue(w.facts[f["rumor_of"]]["truth"], f"{msg} rumor root not true")
    # 死人不會再做事；同一個人不會死兩次
    death_day = {}
    for fid in w.event_log:
        f = w.facts[fid]
        if f["type"] == "death":
            who = f["roles"]["who"]
            tc.assertNotIn(who, death_day, f"{msg} {who} died twice")
            death_day[who] = (f["day"], int(fid[1:]))
    for fid in w.event_log:
        f = w.facts[fid]
        for role in ACTING_ROLES:
            actor = f["roles"].get(role)
            if actor in death_day and int(fid[1:]) > death_day[actor][1]:
                tc.fail(f"{msg} dead {actor} acted in {fid} ({f['type']})")
    if w.pending:
        tc.assertIn(w.pending["kind"], {"beating", "theft_seen", "player_threat"}, msg)


# ---------------- 假 Ollama ----------------
class FakeOllama:
    """在本機開一個假的 Ollama：/api/tags 回模型清單，/api/chat 依 responder(body) 回內容。"""

    def __init__(self, responder, model="qwen3.5:9b"):
        self.responder = responder
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"models": [{"name": model}]})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n))
                outer.requests.append(body)
                content = outer.responder(body)
                self._send({"message": {"content": content}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def template_from_request(body: dict) -> str:
    user = body["messages"][-1]["content"]
    return user.split("【本段已發生的事】\n", 1)[1]


__all__ = ["World", "new_world", "idle_days", "random_play", "check_invariants", "FakeOllama", "template_from_request"]
