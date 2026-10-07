"""前端拿到的資料不能洩漏世界的祕密。整包掃描，不是只看幾個欄位。"""

import json
import random
import unittest

from support import new_world, random_play

from rpg import player as player_mod
from rpg import view
from rpg.content import text as T

FORBIDDEN_KEYS = {"traits", "opinions", "knows", "stress", "genes", "truth", "roles", "data", "rumor_of", "causes",
                  "cases", "loans", "blame", "schedule", "seed", "rng_state", "mischief_log", "true_culprit",
                  "secrecy", "importance", "need_fact", "income", "wage", "patron_of", "admires", "smuggler",
                  "hoarder", "garnished_by", "to_report", "decay", "medicine_days", "jail_until", "status"}


def walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + (k,), k, v
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))


class ViewHidingTests(unittest.TestCase):
    def _views(self):
        for seed in (3, 8, 21):
            w = new_world(seed, "peddler")
            rng = random.Random(seed)
            for _ in range(8):
                random_play(w, 25, rng, avoid=())
                yield w, view.build(w, w.feed)

    def test_no_internal_fields_anywhere(self):
        for w, v in self._views():
            for path, k, val in walk(v):
                if k == "money":
                    self.assertEqual(path, ("player", "money"), f"money leaked at {path}")
                    continue
                if k == "status":
                    self.assertEqual(path[0], "people", f"status leaked at {path}")
                    self.assertIn(val, (None, "已過世", "已離開青石鎮", "關在巡檢所"))
                    continue
                self.assertNotIn(k, FORBIDDEN_KEYS, f"internal key {k!r} leaked at {path}")

    def test_unknown_secrets_never_appear_in_the_payload(self):
        for w, v in self._views():
            dump = json.dumps(v, ensure_ascii=False)
            known_texts = {T.fact_text(w, w.facts[f]) for f in w.player["knows"] if f in w.facts}
            for fid, f in w.facts.items():
                if fid in w.player["knows"] or f["secrecy"] == "public":
                    continue
                txt = T.fact_text(w, f)
                if txt in known_texts or len(txt) < 12:
                    continue
                self.assertNotIn(txt, dump, f"secret {f['type']} leaked: {txt}")

    def test_tell_options_only_offer_what_the_player_knows(self):
        for w, v in self._views():
            for a in v["actions"]:
                if a["id"].startswith("tell:"):
                    self.assertIn(a["id"].split(":", 1)[1], w.player["knows"])
                if a["id"].startswith("pay_for:"):
                    ln = w.loans[a["id"].split(":", 1)[1]]
                    self.assertIn(ln["fact"], w.player["knows"], "can only pay debts you know about")

    def test_jailed_people_are_not_revealed_by_menus(self):
        w = new_world(4, "heir")
        w.player["money"] = 500
        w.npcs["zhou"]["status"] = "jailed"
        w.npcs["zhou"]["location"] = "yamen"
        w.npcs["xiaoli"]["location"] = w.player["location"] = "den"
        w.npcs["xiaoli"]["status"] = "normal"
        player_mod.perform(w, "talk:xiaoli")
        ids = [a["id"] for a in player_mod.available_actions(w)]
        self.assertNotIn("bribe_release:zhou", ids, "the player does not know zhou was arrested")

    def test_unmet_people_show_as_strangers(self):
        w = new_world(4, "heir")
        v = view.build(w, [])
        for p in v["present"]:
            if p["key"] not in w.player["met"]:
                self.assertIsNone(p["name"])
                self.assertTrue(p["label"].startswith("一個"))


if __name__ == "__main__":
    unittest.main()
