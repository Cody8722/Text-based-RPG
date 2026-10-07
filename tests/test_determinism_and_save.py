"""seed 機制與存檔：同樣的 seed + 同樣的動作 = 同樣的世界；存檔再讀回來，世界接著跑出一模一樣的結果。"""

import json
import random
import tempfile
import unittest

from support import new_world

from rpg import player as player_mod
from rpg.game import Game
from rpg.narrator import Narrator
from rpg.world import World


def scripted_play(w, n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        acts = player_mod.available_actions(w)
        player_mod.perform(w, rng.choice(acts)["id"])


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_actions_same_world(self):
        a, b = new_world(77, "peddler"), new_world(77, "peddler")
        self.assertEqual(a.state_hash(), b.state_hash())
        scripted_play(a, 150, 5)
        scripted_play(b, 150, 5)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_different_seeds_differ(self):
        self.assertNotEqual(new_world(1, "peddler").state_hash(), new_world(2, "peddler").state_hash())

    def test_save_load_mid_game_continues_identically(self):
        straight = new_world(31, "escort")
        scripted_play(straight, 80, 9)
        snap = json.loads(json.dumps(straight.to_dict(), ensure_ascii=False))   # 走一次真正的 JSON
        resumed = World.from_dict(snap)
        self.assertEqual(straight.state_hash(), resumed.state_hash())
        scripted_play(straight, 80, 10)
        scripted_play(resumed, 80, 10)
        self.assertEqual(straight.state_hash(), resumed.state_hash())

    def test_game_autosave_and_continue_through_a_new_process_object(self):
        d = tempfile.mkdtemp()
        g1 = Game(save_dir=d, narrator=Narrator(mode="off"))
        r = g1.new("scholar", 5)
        for _ in range(25):
            r = g1.act(r["view"]["actions"][0]["id"])
        g2 = Game(save_dir=d, narrator=Narrator(mode="off"))
        self.assertTrue(g2.has_save())
        r2 = g2.resume()
        self.assertEqual(r2["view"]["day"], r["view"]["day"])
        self.assertEqual(r2["view"]["period"], r["view"]["period"])
        self.assertEqual(g2.world.state_hash(), g1.world.state_hash())

    def test_corrupt_or_old_save_is_ignored_not_crashing(self):
        d = tempfile.mkdtemp()
        g = Game(save_dir=d, narrator=Narrator(mode="off"))
        g.new("scholar", 5)
        with open(g.save_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(Game(save_dir=d, narrator=Narrator(mode="off")).load())
        with open(g.save_path, "w", encoding="utf-8") as f:
            json.dump({"version": 999}, f)
        self.assertIsNone(Game(save_dir=d, narrator=Narrator(mode="off")).load())

    def test_rng_is_the_only_source_of_randomness(self):
        """引擎不准用全域 random：把全域 random 弄亂，同 seed 的世界仍然一致。"""
        import random as global_random

        a = new_world(12, "heir")
        scripted_play(a, 60, 3)
        global_random.seed(999)
        for _ in range(1000):
            global_random.random()
        b = new_world(12, "heir")
        scripted_play(b, 60, 3)
        self.assertEqual(a.state_hash(), b.state_hash())


if __name__ == "__main__":
    unittest.main()
