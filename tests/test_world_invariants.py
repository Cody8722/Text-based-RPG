"""長時間世界演化：不管世界自己跑還是玩家亂玩，不變量都要成立。"""

import random
import unittest

from support import check_invariants, idle_days, new_world, random_play, sim


class WorldInvariantTests(unittest.TestCase):
    def test_idle_world_120_days_many_seeds(self):
        for seed in range(1, 13):
            w = new_world(seed, "drifter")
            for day in range(120):
                idle_days(w, 1)
                if day % 10 == 0:
                    check_invariants(self, w, "idle")
            check_invariants(self, w, "idle-end")

    def test_random_player_many_seeds(self):
        for seed in range(1, 9):
            w = new_world(seed, ["scholar", "escort", "peddler", "herbalist", "heir", "drifter"][seed % 6])
            rng = random.Random(seed * 31)
            for chunk in range(12):
                random_play(w, 40, rng, avoid=())
                check_invariants(self, w, f"play chunk {chunk}")

    def test_very_long_world_does_not_collapse_or_crash(self):
        w = new_world(4242, "escort")
        idle_days(w, 240)
        check_invariants(self, w, "240d")
        alive = sum(1 for n in w.npcs.values() if n["status"] in ("normal", "jailed"))
        self.assertGreaterEqual(alive, 12, "town should still be inhabited after 240 days")
        # 經濟沒有整個鎮子都破產
        broke = sum(1 for n in w.npcs.values() if n["status"] == "normal" and n["money"] == 0)
        self.assertLess(broke, alive * 0.6)

    def test_warmup_gives_the_town_a_past(self):
        w = new_world(7, "scholar")
        self.assertEqual(w.display_day(w.day), 1, "player arrives on display day 1")
        self.assertGreater(len(w.event_log), 5, "things happened before the player arrived")
        self.assertEqual(w.player["knows"], {}, "player arrives knowing nothing")
        self.assertEqual(w.player["location"], "gate")
        self.assertEqual(w.feed, [])

    def test_pending_freezes_time(self):
        w = new_world(3, "escort")
        w.pending = {"kind": "beating", "mode": "fight", "attacker": "liu6", "victim": "zhou", "place": "gate", "loan": None}
        clock = w.clock
        sim.advance(w, 12)
        self.assertEqual(w.clock, clock, "no time passes while the player has to decide")


if __name__ == "__main__":
    unittest.main()
