"""因果：世界真的會長出事件鏈；玩家介入真的會改變結果；傳聞真的會讓錯的人倒楣。

這裡的每一個斷言都是看 world state 與事實紀錄，不看文字。
"""

import random
import unittest

from support import check_invariants, idle_days, new_world

from rpg import behaviors, devtools, dialogue, reactions, sim
from rpg import player as player_mod

DRAMA = {"fight", "theft", "caught_stealing", "arrest", "debt_beating", "fled", "death", "property_seized",
         "evicted", "debt_threat", "fire", "fired"}


class EmergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = []
        for seed in range(1, 21):
            w = new_world(seed, "drifter")
            idle_days(w, 60)
            cls.worlds.append(w)

    def test_chains_of_causes_form_without_the_player(self):
        deep = [w for w in self.worlds if devtools.summarize(w)["max_chain"] >= 4]
        self.assertGreaterEqual(len(deep), int(len(self.worlds) * 0.7), "most worlds should grow cause chains of depth >= 4")

    def test_many_kinds_of_events_happen(self):
        kinds = set()
        for w in self.worlds:
            kinds |= {w.facts[f]["type"] for f in w.event_log}
        self.assertGreaterEqual(len(kinds), 18, sorted(kinds))

    def test_every_world_has_drama_but_not_a_massacre(self):
        for w in self.worlds:
            drama = sum(1 for f in w.event_log if w.facts[f]["type"] in DRAMA)
            self.assertGreaterEqual(drama, 3, f"seed {w.seed} too quiet")
            dead = sum(1 for n in w.npcs.values() if n["status"] == "dead")
            self.assertLessEqual(dead, 4, f"seed {w.seed} too deadly")

    def test_worlds_are_different(self):
        signatures = {tuple(sorted(g["gene"] for g in w.genes)) for w in self.worlds}
        self.assertGreaterEqual(len(signatures), 14)
        # 「同樣的 60 天」在不同世界裡，發生的大事與主角組合都不一樣
        stories = set()
        for w in self.worlds:
            stories.add(tuple(sorted({(w.facts[f]["type"], w.culprit_of(w.facts[f]) or w.facts[f]["roles"].get("who"))
                                      for f in w.event_log if w.facts[f]["type"] in DRAMA})))
        self.assertEqual(len(stories), len(self.worlds), "no two worlds should tell the same story")

    def test_rumors_get_distorted_and_can_jail_the_wrong_person(self):
        distorted = sum(w.stats.get("rumor_distorted", 0) for w in self.worlds)
        self.assertGreater(distorted, 20)
        wrongful = []
        for w in self.worlds + [self._run(s) for s in range(21, 41)]:
            for c in w.cases.values():
                if c["arrested"] and c.get("true_culprit") and c["arrested"] != c["true_culprit"]:
                    wrongful.append((w.seed, c["arrested"], c["true_culprit"]))
        self.assertTrue(wrongful, "across 40 worlds, rumors should send at least one innocent to the cells")

    def _run(self, seed):
        w = new_world(seed, "drifter")
        idle_days(w, 60)
        return w


class InterventionTests(unittest.TestCase):
    def setUp(self):
        self.w = new_world(11, "escort")

    def _overdue_loan(self, borrower="zhou", amount=60):
        w = self.w
        fid = w.add_fact("loan", {"lender": "qian", "borrower": borrower}, place="den",
                         data={"amount": amount, "due": w.day - 1}, secrecy="private", importance=3,
                         known_by=[borrower, "qian", "liu6"])
        lid = w.add_loan("qian", borrower, amount, -1, 0, fact_id=fid)
        return lid, fid

    def test_paying_someones_debt_stops_the_collectors(self):
        w = self.w
        for ln in list(w.loans.values()):
            if ln["borrower"] == "zhou":
                ln["status"] = "repaid"
        lid, fid = self._overdue_loan()
        w.player["knows"][fid] = {"day": w.day, "src": "zhou"}
        w.player["money"] = 200
        w.player["location"] = w.npcs["qian"]["location"]
        player_mod.perform(w, "talk:qian")
        before = w.opinion("zhou", "player")
        player_mod.perform(w, f"pay_for:{lid}")
        self.assertEqual(w.loans[lid]["status"], "repaid")
        self.assertEqual(w.loans[lid]["repaid_by"], "player")
        self.assertGreater(w.opinion("zhou", "player"), before, "the debtor hears who paid")
        # 這筆債不會再被催
        mark = len(w.event_log)
        idle_days(w, 10)
        for f in w.event_log[mark:]:
            fact = w.facts[f]
            if fact["type"] in ("debt_warning", "debt_threat", "debt_beating"):
                self.assertNotIn(fid, fact["causes"], "a paid loan must never be collected again")
        # 同一筆債不能付第二次（一次性：動作從清單裡消失）
        self.assertNotIn(f"pay_for:{lid}", {a["id"] for a in player_mod.available_actions(w)})
        with self.assertRaises(player_mod.ActionError):
            player_mod.perform(w, f"pay_for:{lid}")

    def test_beating_intervention_choices_have_different_consequences(self):
        outcomes = {}
        for choice in ("pay", "watch"):
            w = new_world(11, "escort")
            self.w = w
            for ln in list(w.loans.values()):
                if ln["borrower"] == "zhou":
                    ln["status"] = "repaid"
            lid, fid = self._overdue_loan()
            w.npcs["zhou"]["location"] = w.player["location"]
            w.player["money"] = 500
            sim.open_pending_beating(w, "liu6", "zhou", w.player["location"], w.loans[lid], mode="beat")
            ids = {a["id"] for a in player_mod.available_actions(w)}
            self.assertTrue(ids <= {"pend:stop", "pend:pay", "pend:talk", "pend:watch"}, "only intervention choices while pending")
            hp = w.npcs["zhou"]["health"]
            player_mod.perform(w, f"pend:{choice}")
            outcomes[choice] = (w.loans[lid]["status"], w.npcs["zhou"]["health"] < hp)
        self.assertEqual(outcomes["pay"], ("repaid", False))
        self.assertEqual(outcomes["watch"], ("open", True))

    def test_giving_medicine_changes_a_life(self):
        def run(give):
            w = new_world(5, "herbalist")
            w.npcs["linshen"]["medicine_days"] = 0
            w.npcs["linshen"]["health"] = 40
            w.npcs["linshen"]["patron_of"] = None
            for n in w.npcs.values():
                n.pop("patron_of", None)
            if give:
                w.player["inventory"]["medicine"] = 3
                w.player["location"] = "alley"
                w.npcs["linshen"]["location"] = "alley"
                player_mod.perform(w, "talk:linshen")
                for _ in range(3):
                    player_mod.perform(w, "give_med")
            return w

        helped, control = run(True), run(False)
        self.assertGreater(helped.npcs["linshen"]["medicine_days"], control.npcs["linshen"]["medicine_days"])
        idle_days(helped, 6)
        idle_days(control, 6)
        self.assertGreater(helped.npcs["linshen"]["health"], control.npcs["linshen"]["health"] - 1)
        given = [f for f in helped.player["deeds"] if helped.facts[f]["type"] == "medicine"]
        self.assertEqual(len(given), 3, "each gift is a deed the town can hear about")

    def test_witnessing_a_theft_and_shouting_returns_the_money(self):
        w = new_world(2, "escort")
        w.player["location"] = "market"
        w.npcs["xiaohu"]["location"] = "market"
        victim = "chenbo"
        w.npcs[victim]["money"] = 100
        fid = w.add_fact("theft", {"thief": "xiaohu", "victim": victim}, place="market", data={"amount": 30},
                         secrecy="secret", importance=4, known_by=["xiaohu"], witnesses=["player"])
        w.transfer(victim, "xiaohu", 30)
        w.flags.setdefault("_undiscovered", []).append(fid)
        w.pending = {"kind": "theft_seen", "thief": "xiaohu", "victim": victim, "place": "market", "fact": fid}
        player_mod.perform(w, "pend:shout")
        self.assertEqual(w.npcs[victim]["money"], 100)
        caught = [f for f in w.player["deeds"] if w.facts[f]["type"] == "caught_stealing"]
        self.assertEqual(len(caught), 1)
        self.assertNotIn(fid, w.flags.get("_undiscovered", []), "a theft that was stopped is not 'discovered' later")


class KnowledgeTests(unittest.TestCase):
    def test_low_honesty_gossip_can_frame_someone_the_teller_hates(self):
        w = new_world(9, "drifter")
        teller, listener = "xiaoli", "chenbo"
        w.npcs[teller]["traits"]["honesty"] = 0
        w.npcs[teller]["opinions"]["shitou"] = -90
        real = w.add_fact("theft", {"thief": "zhou", "victim": "sun"}, place="inn", data={"amount": 40},
                          secrecy="public", importance=4, known_by=[teller])
        framed = None
        for _ in range(40):
            w.npcs[listener]["knows"].pop(real, None)
            out = behaviors.tell(w, teller, listener, real)
            if out != real:
                framed = w.facts[out]
                break
        self.assertIsNotNone(framed, "a very dishonest gossip should eventually twist the story")
        self.assertFalse(framed["truth"])
        self.assertEqual(framed["roles"]["thief"], "shitou")
        self.assertEqual(framed["rumor_of"], real)
        self.assertLess(w.opinion(listener, "shitou"), 0, "the listener believes the rumor")

    def test_guard_only_acts_on_what_he_knows(self):
        w = new_world(4, "scholar")
        crime = w.add_fact("theft", {"thief": "zhou", "victim": "su"}, place="market", data={"amount": 40},
                           secrecy="secret", importance=4, known_by=["zhou"])
        report = w.add_fact("theft_report", {"victim": "su"}, place="market", data={"amount": 40, "crime": crime, "thief": "zhou"},
                            importance=3, known_by=["su"])
        w.learn("zhao", report, "su")
        case = next(c for c in w.cases.values() if c["crime"] == crime)
        self.assertEqual(reactions.suspicion(w, case), {}, "a report alone names nobody")
        # 玩家指控一個無辜的人：捕頭只能照他聽到的去懷疑
        w.player["knows"][report] = {"day": w.day, "src": "su"}
        w.player["met"].append("aniu")          # 玩家只能指認他認識的人
        w.player["location"] = w.npcs["zhao"]["location"] = "yamen"
        w.npcs["zhao"]["status"] = "normal"
        player_mod.perform(w, "talk:zhao")
        player_mod.perform(w, f"accuse:{report}:aniu")
        scores = reactions.suspicion(w, case)
        self.assertIn("aniu", scores)
        self.assertNotIn("zhou", scores)
        acc = [f for f in w.facts.values() if f["type"] == "accusation" and f["roles"].get("accuser") == "player"]
        self.assertFalse(acc[-1]["truth"], "the system knows the accusation is false; the guard does not")
        # 真正的目擊者作證後，懷疑會轉向真兇
        witness = w.add_fact("theft", {"thief": "zhou", "victim": "su"}, place="market", data={"amount": 40, "crime": crime},
                             secrecy="secret", importance=4, known_by=["wu"], log=False)
        w.facts[witness]["truth"] = True
        w.npcs["zhao"]["knows"][witness] = {"day": w.day, "src": "witness"}
        scores = reactions.suspicion(w, case)
        self.assertGreater(scores["zhou"], scores["aniu"])

    def test_dialogue_never_reveals_self_incriminating_facts(self):
        w = new_world(6, "peddler")
        fid = w.add_fact("theft", {"thief": "xiaohu", "victim": "wang"}, place="tavern", data={"amount": 20},
                         secrecy="public", importance=5, known_by=["xiaohu"])
        w.npcs["xiaohu"]["opinions"]["player"] = 100
        opts = dict(behaviors.shareable(w, "xiaohu", "player"))
        self.assertNotIn(fid, opts)

    def test_secrets_need_trust(self):
        w = new_world(6, "peddler")
        fid = w.add_fact("secret_love", {"lover": "sun", "beloved": "su"}, secrecy="secret", importance=3, known_by=["wu"])
        w.npcs["wu"]["opinions"]["player"] = 0
        self.assertNotIn(fid, dict(behaviors.shareable(w, "wu", "player")))
        w.npcs["wu"]["opinions"]["player"] = 80
        self.assertIn(fid, dict(behaviors.shareable(w, "wu", "player")))


class InvariantCheckerSelfTest(unittest.TestCase):
    """確認 check_invariants 真的抓得到問題（避免「測試看起來通過、其實什麼都沒檢查」）。"""

    def test_checker_catches_planted_corruption(self):
        corruptions = [
            lambda w: w.npcs["wang"].__setitem__("money", -1),
            lambda w: w.npcs["wang"].__setitem__("health", 150),
            lambda w: w.npcs["wang"].update(status="jailed", location="tavern"),
            lambda w: w.npcs["wang"]["opinions"].__setitem__("ayue", 300),
            lambda w: w.facts[w.event_log[0]].__setitem__("causes", [f"f{w.fact_seq + 5}"]),
            lambda w: w.npcs["wang"].__setitem__("money", 3.5),
        ]
        for corrupt in corruptions:
            w = new_world(1, "drifter")
            corrupt(w)
            with self.assertRaises(AssertionError):
                check_invariants(self, w)


if __name__ == "__main__":
    unittest.main()
