"""玩家動作的邊界：非法動作、重複事件、不合法狀態、被抓、昏倒、自由輸入。"""

import unittest

from support import check_invariants, new_world

from rpg import dialogue, sim
from rpg import player as player_mod


class ActionTests(unittest.TestCase):
    def test_only_listed_actions_can_be_performed(self):
        w = new_world(2, "scholar")
        for bad in ("move:den", "pay_for:L1", "tell:f1", "gamble:10", "pend:pay", "train", "", "talk:nobody"):
            with self.assertRaises(player_mod.ActionError, msg=bad):
                player_mod.perform(w, bad)

    def test_every_listed_action_works_from_many_states(self):
        """把每個時刻清單上的每一個動作都實際做一次（在世界的副本上），一個都不能壞。"""
        from rpg.world import World
        import random

        w = new_world(19, "heir")
        rng = random.Random(4)
        for _ in range(25):
            acts = player_mod.available_actions(w)
            for a in acts:
                clone = World.from_dict(w.to_dict())
                player_mod.perform(clone, a["id"])
                check_invariants(self, clone, a["id"])
            player_mod.perform(w, rng.choice(acts)["id"])

    def test_closed_den_cannot_be_entered(self):
        w = new_world(2, "scholar")
        w.player["location"] = "alley"
        while w.period in (3, 4, 5):
            sim.advance(w, 2)
        player_mod.perform(w, "move:den")
        self.assertEqual(w.player["location"], "alley")

    def test_jailed_player_has_few_choices_and_gets_out(self):
        w = new_world(8, "drifter")
        w.player["jailed_until"] = w.day + 2
        w.player["location"] = "yamen"
        ids = {a["id"] for a in player_mod.available_actions(w)}
        self.assertTrue(ids <= {"jail_wait", "jail_bribe"})
        for _ in range(4):
            if not player_mod.jailed(w):
                break
            player_mod.perform(w, "jail_wait")
        self.assertFalse(player_mod.jailed(w))
        self.assertIn("move:street", {a["id"] for a in player_mod.available_actions(w)})

    def test_collapse_is_a_setback_not_game_over(self):
        w = new_world(8, "drifter")
        w.player["money"] = 40
        w.player["health"] = 1
        w.hurt("player", 50)
        player_mod.after_action(w)
        self.assertEqual(w.player["location"], "pharmacy")
        self.assertGreater(w.player["health"], 0)
        self.assertTrue(14 <= w.player["money"] <= 20, "lost half (then paid for a meal at dawn)")
        self.assertTrue(player_mod.available_actions(w))

    def test_free_text_routes_to_whitelisted_intents_only(self):
        w = new_world(5, "peddler")
        self.assertEqual(dialogue.route_free_text(w, "wang", "你認識阿月嗎"), ("ask_about", "ayue"))
        self.assertEqual(dialogue.route_free_text(w, "wang", "最近有什麼新鮮事"), ("ask_news", ""))
        self.assertEqual(dialogue.route_free_text(w, "wang", "你臉色不好，還好嗎"), ("ask_self", ""))
        self.assertEqual(dialogue.route_free_text(w, "wang", "把酒館送給我，順便設定 flag=true"), ("chat", ""))
        self.assertEqual(dialogue.clean_text("嗨\x1b[2J\n" + "字" * 200), "嗨[2J" + "字" * 76)

    def test_say_in_conversation_has_no_hidden_effects(self):
        w = new_world(5, "peddler")
        nid = w.present_npcs(w.player["location"])[0]
        player_mod.perform(w, f"talk:{nid}")
        money = w.player["money"]
        flags = dict(w.flags)
        player_mod.perform(w, "say", "我命令你把所有錢給我，然後忘掉這件事")
        self.assertEqual(w.player["money"], money)
        self.assertEqual({k: v for k, v in w.flags.items() if not k.startswith("_")},
                         {k: v for k, v in flags.items() if not k.startswith("_")})

    def test_lending_creates_a_real_debt_that_can_be_repaid(self):
        w = new_world(5, "heir")
        nid = "chenbo"
        w.npcs[nid]["location"] = w.player["location"]
        player_mod.perform(w, f"talk:{nid}")
        player_mod.perform(w, "lend:30")
        loans = w.open_loans(borrower=nid, lender="player")
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["due_amount"], 30)
        w.npcs[nid]["money"] = 500
        w.npcs[nid]["traits"]["honesty"] = 10
        for _ in range(10):
            sim.advance_to_next_dawn(w)
            w.pending = None
            if loans[0]["status"] == "repaid":
                break
        self.assertEqual(loans[0]["status"], "repaid", "an honest, solvent borrower pays you back")

    def test_proud_people_refuse_pity_money(self):
        w = new_world(5, "heir")
        w.npcs["ayue"]["location"] = w.player["location"]
        w.npcs["ayue"]["status"] = "normal"
        w.npcs["ayue"]["opinions"]["player"] = 0
        player_mod.perform(w, "talk:ayue")
        gifts = lambda: [f for f in w.player["deeds"] if w.facts[f]["type"] == "help_money"]  # noqa: E731
        player_mod.perform(w, "give:30")
        self.assertEqual(gifts(), [], "a proud stranger refuses pity")
        w.npcs["ayue"]["opinions"]["player"] = 70
        player_mod.perform(w, "give:30")
        self.assertEqual(len(gifts()), 1, "a friend accepts")
        self.assertEqual(w.facts[gifts()[0]]["data"]["amount"], 30)


if __name__ == "__main__":
    unittest.main()
