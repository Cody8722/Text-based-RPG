"""對話與播報：同一件事不重複播、NPC 不重複說同一句話、當事人不轉述自己做的事、文字選擇不影響世界。"""

import unittest

from support import new_world

from rpg import dialogue, speech, view
from rpg import player as player_mod
from rpg.content.npcs import CHATTER
from rpg.world import TICKS_PER_DAY


def bring(w, nid, opinion=0):
    n = w.npcs[nid]
    n["status"] = "normal"
    n["location"] = w.player["location"]
    n["opinions"]["player"] = opinion
    w.pending = None


def speeches(beats):
    return [b["text"] for b in beats if b["kind"] == "speech"]


def thefts_by(w, thief, victims, days_ago=1):
    out = []
    for v in victims:
        fid = w.add_fact("caught_stealing", {"thief": thief, "victim": v}, place="market", importance=4, log=False)
        w.facts[fid]["day"] = w.day - days_ago
        out.append(fid)
    return out


class StoryTests(unittest.TestCase):
    def test_dawn_news_tells_one_story_once(self):
        w = new_world(4, "drifter")
        fids = thefts_by(w, "xiaohu", ["chenbo", "wang", "bai"])
        w.flags["_town_news"] = list(fids)
        w.feed = []
        player_mod.spread_town_news(w)
        news = [b["text"] for b in w.feed if b["kind"] == "news"]
        self.assertTrue(all(f in w.player["knows"] for f in fids), "the player hears all of it")
        self.assertEqual(sum("小虎" in t for t in news), 1, f"one story, one telling: {news}")
        self.assertTrue(any("三回" in t for t in news), f"the telling sums it up: {news}")

    def test_journal_has_one_entry_per_story(self):
        w = new_world(4, "drifter")
        for fid in thefts_by(w, "xiaohu", ["chenbo", "wang", "bai"]):
            w.learn("player", fid, "town")
        keys = {speech.story_key(w.facts[f]) for f in w.player["knows"] if w.facts[f]["type"] != "player_work"}
        self.assertEqual(len(view.journal(w, limit=999)), len(keys))

    def test_sharing_a_story_tells_all_of_it_once(self):
        w = new_world(6, "peddler")
        bring(w, "wu", opinion=60)
        w.npcs["wu"]["opinions"]["xiaohu"] = 0
        fids = thefts_by(w, "xiaohu", ["chenbo", "wang", "bai"])
        for fid in fids:
            w.npcs["wu"]["knows"][fid] = {"day": w.day, "src": "town"}
        w.feed = []
        self.assertTrue(dialogue.share_one(w, "wu", "xiaohu"))
        self.assertTrue(all(f in w.player["knows"] for f in fids), "the whole story comes out at once")
        self.assertEqual(len(speeches(w.feed)), 1)


class SpeechTests(unittest.TestCase):
    def test_pestering_gets_different_answers_then_ends_the_talk(self):
        w = new_world(3, "drifter")
        bring(w, "wu")
        player_mod.perform(w, "talk:wu")
        said = []
        for _ in range(3):
            if not w.player.get("talking_to"):
                break
            said += speeches(player_mod.perform(w, "ask_self"))
        self.assertEqual(len(said), len(set(said)), f"no line twice: {said}")
        self.assertIsNone(w.player.get("talking_to"), "asked three times, the old man has had enough")

    def test_small_talk_lines_are_not_repeated(self):
        w = new_world(8, "drifter")
        heard = []
        for _ in range(4):
            bring(w, "wang", opinion=20)
            w.player["location"] = w.npcs["wang"]["location"]
            player_mod.perform(w, "talk:wang")
            for _ in range(2):
                if w.player.get("talking_to") == "wang":
                    heard += [t for t in speeches(player_mod.perform(w, "chat")) if any(c in t for c in CHATTER["wang"])]
            w.player["talking_to"] = None
        self.assertEqual(len(heard), len(set(heard)), f"{heard}")

    def test_npc_brings_up_your_deed_once(self):
        w = new_world(5, "drifter")
        bring(w, "wang", opinion=-10)
        fid = w.add_fact("caught_stealing", {"thief": "player", "victim": "wang"}, place="tavern", importance=4,
                         known_by=["wang"], log=False)
        player_mod.deed(w, fid)
        first = speeches(player_mod.perform(w, "talk:wang"))
        player_mod.perform(w, "end_talk")
        bring(w, "wang", opinion=-10)
        second = speeches(player_mod.perform(w, "talk:wang"))
        remark = lambda lines: [t for t in lines if any(v in t for v in speech.VICTIM_OF_PLAYER)]  # noqa: E731
        self.assertEqual(len(remark(first)), 1, f"{first}")
        self.assertEqual(remark(second), [], f"{second}")

    def test_the_arresting_guard_does_not_report_his_own_arrest(self):
        w = new_world(5, "drifter")
        bring(w, "zhao", opinion=-10)
        c = w.add_fact("caught_stealing", {"thief": "player", "victim": "wang"}, place="tavern", importance=4,
                       known_by=["zhao"], log=False)
        a = w.add_fact("arrest", {"guard": "zhao", "suspect": "player"}, place="tavern", data={"charge": "偷竊"},
                       importance=4, causes=[c], known_by=["zhao"], log=False)
        player_mod.deed(w, c)
        w.learn("player", a, "self")
        lines = speeches(player_mod.perform(w, "talk:zhao"))
        self.assertFalse(any("我以" in t or "抓進" in t for t in lines), f"{lines}")
        self.assertTrue(any(g in t for t in lines for g in speech.GUARD_AFTER), f"{lines}")

    def test_text_choices_do_not_touch_the_world_rng(self):
        w = new_world(9, "drifter")
        state = w.rng.getstate()
        for i in range(20):
            speech.pick(w, "wu", ["甲", "乙", "丙"])
            speech.chance(w, "wu", 50)
        self.assertEqual(w.rng.getstate(), state)


class StealTests(unittest.TestCase):
    def test_caught_stealing_gets_you_thrown_out_and_watched(self):
        w = new_world(7, "drifter")
        w.player["location"] = "market"
        w.player["money"] = 5
        w.pending = None
        w.roll = lambda *a, **k: False   # 這次一定失手
        self.assertIn("steal", [a["id"] for a in player_mod.available_actions(w)])
        player_mod.perform(w, "steal")
        del w.roll
        self.assertEqual(w.player["location"], "street", "thrown out")
        w.player["location"] = "market"
        w.pending = None
        self.assertNotIn("steal", [a["id"] for a in player_mod.available_actions(w)], "everyone is watching you here")
        w.clock += TICKS_PER_DAY * 2 + 1
        self.assertIn("steal", [a["id"] for a in player_mod.available_actions(w)], "people forget, eventually")


if __name__ == "__main__":
    unittest.main()
