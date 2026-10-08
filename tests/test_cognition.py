"""世界真實、角色認知、天賦、自由行動——測的是通用機制，不是某一個案例。

- 真實隔離：玩家與 NPC 都拿不到上帝視角（東西的真實身分、別人的真實數值）。
- 認知差異：同一個東西，不同見識、不同感官的人理解成不同的東西；理解會隨證據與別人的說法改變。
- 情報傳播：沒人看見的事不會自己公開；看見的人各有版本；轉述會走樣；每一份知識都有來源。
- 天賦：固定技能與任意文字的天賦共存；天賦被世界裁定（有上限、有代價），不會直接變成世界結果。
- 自由行動：沒有預設 id 的行動也能處理；LLM 宣稱的結果被丟掉；推測只留在玩家腦中。
- NPC 自主：沒有玩家介入，世界照常運作；NPC 依自己相信的版本行動。
"""

import json
import random
import unittest

from support import check_invariants, check_provenance, idle_days, new_world

from rpg import act, behaviors, intent, mind, reactions, talents, view, views
from rpg import player as player_mod
from rpg.content.nature import CONCEPTS, KINDS
from rpg.world import World

INTERNAL_KINDS = [k for k, v in KINDS.items() if v.get("internal")]

VARIED_TALENTS = [
    "前世是一名專門研究超聲波碎石術的泌尿科醫生。",
    "我是一名機械工程師。",
    "我擁有龍族血統。",
    "我可以看到普通人看不到的東西。",
    "我帶著一把陪伴我轉生的老菜刀。",
    "我死前吃了一顆不知道是什麼的藥，轉生後身體發生了變化。",
    "我能一拳打爆任何東西。",
    "我永遠不會迷路。",
    "我天生極度不信任陌生人。",
    "轉生前是某個世界的王族，保留了完整的記憶。",
    "我會說貓的語言，而且每到月圓就會長出尾巴。",
    "嗶嗶嗶，量子糖霜螺旋。",
    "前世是一名研究核融合的物理學家。",
]


def stage(w, place, cast, met=()):
    """讓指定的人站在 place，其他人離開；玩家也站在那裡。"""
    w.pending = None
    w.player["location"] = place
    w.player["talking_to"] = None
    for nid, n in w.npcs.items():
        if nid in cast:
            n["status"], n["location"], n["bedridden"] = "normal", place, False
        elif n["location"] == place:
            n["location"] = "street" if place != "street" else "market"
    for nid in met:
        if nid not in w.player["met"]:
            w.player["met"].append(nid)
            w.npcs[nid]["met_player"] = True


def give_mind(w, nid, domains, senses):
    n = w.npcs[nid]
    n["mind"] = {"domains": [], "things": {}, "learned": [], "self": []}
    n["senses"] = {"sight": 1, "touch": 1, "listen": 1}
    mind.init_mind(n, domains, senses)


def give_ability(w, modality, magnitude=5, precision=6):
    return talents.add_ability(w.player, {"modality": modality, "magnitude": magnitude, "precision": precision,
                                          "reliability": 100, "label": "測試用的本事", "source": "test"})


def player_notices(w, tid):
    """讓玩家用自己的感官察覺這個東西（像是做過一次觸診）。"""
    return mind.believe_thing(w, "player", tid, mind.noticeable(w, w.player, w.things[tid], contact=True), "self")


# ---------------------------------------------------------------- 真實隔離
class TruthIsolationTests(unittest.TestCase):
    def test_player_projection_never_contains_world_truth(self):
        w = new_world(31, "herbalist", ["medicine"], "前世是一名研究超聲波的醫生。我擁有龍族血統。我能一拳打爆任何東西。")
        stage(w, "tavern", ["wang", "ayue"], met=["wang"])
        mind.add_thing(w, "core_dense", host="wang")
        player_mod.perform(w, "talk:wang")
        for text in ("我想檢查他的身體，看看他體內有什麼異常", "我想用震波把那個東西震碎", "我懷疑那就是病因"):
            player_mod.perform(w, "do", text)
        dump = json.dumps(view.build(w, []), ensure_ascii=False)
        for secret in [*KINDS, "integrity", "volatile", "vital", "claimed_magnitude", "magnitude", "reliability",
                       "abilities", "true_culprit", "traits\""]:
            self.assertNotIn(secret, dump, f"truth leaked to the player view: {secret}")
        self.assertIn(w.player["talent_text"], dump, "the player sees their own words, not the adjudicated truth")

    def test_npc_estimates_do_not_read_hidden_numbers(self):
        w = new_world(32, "drifter")
        idle_days(w, 3)
        for target in ("wang", "chenbo", "player"):
            w.ent(target)["money"] = 0
            low = [mind.perceived_wealth(w, o, target) for o in ("liu6", "xiaohu")]
            t_low = behaviors.steal_targets(w, w.npcs["xiaohu"])
            w.ent(target)["money"] = 10000
            high = [mind.perceived_wealth(w, o, target) for o in ("liu6", "xiaohu")]
            t_high = behaviors.steal_targets(w, w.npcs["xiaohu"])
            self.assertEqual(low, high, f"{target}'s purse leaked into how others see {target}")
            self.assertEqual(t_low, t_high)

    def test_players_attitude_panel_shows_behaviour_not_feelings(self):
        w = new_world(33, "drifter")
        sly = next(i for i, n in w.npcs.items() if n["traits"]["honesty"] <= 3)
        w.npcs[sly]["opinions"]["player"] = -60
        self.assertGreater(mind.shown_attitude(w, sly), w.opinion(sly, "player"))


# ---------------------------------------------------------------- 同一個東西，不同的理解
class CognitionTests(unittest.TestCase):
    OBSERVERS = {
        "bai": (["medicine_trad"], {"touch": 3}),
        "tie": (["neigong"], {"qi": 2}),
        "zhou": (["lore"], {"qi": 1}),
        "banxian": (["mystic"], {"touch": 2}),
        "chenbo": ([], {}),
    }

    def test_one_thing_many_understandings(self):
        diverse = 0
        for kind in INTERNAL_KINDS:
            w = new_world(41, "drifter")
            tid = mind.add_thing(w, kind, host="aniu")
            labels = {}
            for nid, (domains, senses) in self.OBSERVERS.items():
                give_mind(w, nid, domains, senses)
                noticed = mind.noticeable(w, w.npcs[nid], w.things[tid], contact=True)
                if nid == "chenbo":
                    self.assertEqual(noticed, {}, f"an ordinary sense of touch cannot feel inside a body ({kind})")
                if noticed:
                    labels[nid] = mind.believe_thing(w, nid, tid, noticed, "self")["label"]
            for label in labels.values():
                self.assertNotIn(kind, label)
            if len(set(labels.values())) >= 2:
                diverse += 1
        self.assertGreaterEqual(diverse, len(INTERNAL_KINDS) // 2, "the same thing should read differently to different people")

    def test_understanding_changes_with_evidence_and_is_never_silently_corrected(self):
        """證據不矛盾就保留原本的理解；出現矛盾的證據才改觀，而且改觀的過程留在記憶裡。"""
        changed = 0
        for kind in INTERNAL_KINDS:
            w = new_world(42, "drifter", ["medicine"])
            tid = mind.add_thing(w, kind, host="aniu")
            first = player_notices(w, tid)
            label0 = first["label"]
            truth = w.things[tid]["traits"]
            b = mind.believe_thing(w, "player", tid, {k: v for k, v in truth.items() if k in ("energy", "resonant")}, "self")
            if b["label"] != label0:
                changed += 1
                self.assertEqual(b["history"][-1]["label"], label0, "the old understanding is remembered")
            self.assertTrue(b["concept"] is None or b["concept"] in mind.concepts_of(w.player),
                            "a belief only uses concepts the character actually has")
        self.assertGreater(changed, 0)

    def test_names_travel_through_each_listeners_own_knowledge(self):
        w = new_world(43, "drifter")
        tid = mind.add_thing(w, "core_dense", host="aniu")
        give_mind(w, "aniu", ["cultivation"], {"qi": 3})
        mind.believe_thing(w, "aniu", tid, mind.noticeable(w, w.npcs["aniu"], w.things[tid], contact=True), "self")
        give_mind(w, "zhou", ["lore"], {})
        give_mind(w, "chenbo", [], {})
        give_mind(w, "su", [], {})
        scholar = mind.tell_name(w, "aniu", "zhou", tid)
        plain = mind.tell_name(w, "aniu", "chenbo", tid)
        second = mind.tell_name(w, "chenbo", "su", tid)
        self.assertEqual(scholar["concept"], "legend_core", "a reader maps the word onto what the books say")
        self.assertIsNone(plain["concept"], "someone without the concept only learns a word")
        self.assertIn("金丹", plain["label"])
        self.assertEqual(second["named"]["word"], plain["named"]["word"], "a heard word is passed on, not nested")

    def test_learning_a_concept_changes_how_old_observations_are_read(self):
        w = new_world(44, "drifter", ["medicine"])
        tid = mind.add_thing(w, "core_dense", host="aniu")
        w.player["senses"]["qi"] = 2
        before = player_notices(w, tid)["label"]
        mind.learn_concept(w, "player", "golden_core")
        after = mind.belief(w.player, tid)
        self.assertNotEqual(after["label"], before)
        self.assertEqual(after["concept"], "golden_core")


# ---------------------------------------------------------------- 情報傳播
class PropagationTests(unittest.TestCase):
    def _hit(self, w, host, tid=None, modality="blunt"):
        give_ability(w, modality, magnitude=6, precision=6)
        target = f"t:{tid}" if tid else f"p:{host}"
        act.resolve(w, {"verb": "apply", "target": target, "modality": modality, "means": None, "purpose": "harm",
                        "text": "", "deep": True})
        return next(f for f in reversed(list(w.facts)) if w.facts[f]["type"] == "act")

    def test_an_unwitnessed_act_is_known_only_through_causal_channels(self):
        w = new_world(51, "drifter")
        stage(w, "alley", ["aniu"], met=["aniu"])
        fid = self._hit(w, "aniu")
        knowers = {k for k, e in [("player", w.player), *w.npcs.items()] if fid in e["knows"]}
        self.assertEqual(knowers, {"player", "aniu"}, "nobody else saw it")
        idle_days(w, 6)
        check_provenance(self, w, "after an unwitnessed act")
        for nid, n in w.npcs.items():
            if fid in n["knows"] and nid != "aniu":
                self.assertNotEqual(n["knows"][fid]["src"], "witness")

    def test_witnessed_act_spreads_as_different_versions(self):
        versions, exaggerated = set(), 0
        for seed in (52, 53, 54):
            w = new_world(seed, "drifter")
            cast = ["aniu", "chenbo", "su", "banxian", "zhou", "shitou"]
            stage(w, "market", cast, met=["aniu"])
            tid = mind.add_thing(w, "core_dense", host="aniu")
            give_mind(w, "aniu", ["cultivation"], {"qi": 3})
            mind.believe_thing(w, "aniu", tid, mind.noticeable(w, w.npcs["aniu"], w.things[tid], contact=True), "self")
            player_notices(w, tid)
            fid = self._hit(w, "aniu", tid, "vibration")
            idle_days(w, 8)
            check_provenance(self, w, f"seed {seed}")
            for nid, n in w.npcs.items():
                info = n["knows"].get(fid)
                if info:
                    versions.add(views.render(w, w.facts[fid], info["view"], speaker=nid, listener="others"))
                    exaggerated += info["view"].get("exag", 0) > 0
        self.assertGreaterEqual(len(versions), 3, "one event, several versions in town")
        self.assertGreater(exaggerated, 0, "retelling embellishes")

    def test_a_face_seen_is_not_a_name_known_until_recognised(self):
        w = new_world(55, "drifter")
        stage(w, "market", ["aniu", "su"], met=["aniu"])
        w.npcs["su"]["met_player"] = False
        fid = self._hit(w, "aniu")
        if fid not in w.npcs["su"]["knows"]:
            w.learn("su", fid, "witness", view=views.perceive(w, "su", {
                "actor": "player", "host": "aniu", "thing": None, "verb": "apply", "modality": "blunt",
                "effects": ["pain"], "contact": True, "magnitude": 6}))
        v = w.npcs["su"]["knows"][fid]["view"]
        self.assertIsNone(v["actor"])
        self.assertEqual(v["face"], "player")
        stage(w, "market", ["su"])
        player_mod.see_faces(w)
        self.assertEqual(w.npcs["su"]["knows"][fid]["view"]["actor"], "player")

class GuardBeliefTests(unittest.TestCase):
    def test_the_guard_follows_his_version_not_the_truth(self):
        w = new_world(56, "drifter")
        stage(w, "alley", ["aniu"], met=["aniu"])
        give_ability(w, "blunt", 6, 6)
        act.resolve(w, {"verb": "apply", "target": "p:aniu", "modality": "blunt", "means": None, "purpose": "harm",
                        "text": "", "deep": False})
        fid = next(f for f in reversed(list(w.facts)) if w.facts[f]["type"] == "act")
        wrong = dict(w.npcs["aniu"]["knows"][fid]["view"], actor="liu6")
        w.learn("zhao", fid, "aniu", view=wrong)
        case = next(c for c in w.cases.values() if c["crime"] == fid)
        scores = reactions.suspicion(w, case)
        self.assertIn("liu6", scores)
        self.assertNotIn("player", scores, "the guard cannot suspect someone nobody told him about")


# ---------------------------------------------------------------- 固定技能 × 自訂天賦
class TalentTests(unittest.TestCase):
    def test_any_text_becomes_initial_conditions(self):
        for text in VARIED_TALENTS:
            with self.subTest(text=text):
                w = new_world(61, "drifter", ["medicine", "trade"], text)
                p = w.player
                self.assertEqual(p["skills"], ["medicine", "trade"], "fixed skills stay")
                self.assertTrue(p["talents"], "every talent text is kept as at least one claim")
                self.assertEqual([s["text"] for s in p["mind"]["self"]], [c["text"] for c in p["talent_claims"]])
                check_invariants(self, w, text)

    def test_claims_are_adjudicated_not_obeyed(self):
        w = new_world(62, "drifter", [], "我能一拳打爆任何東西。")
        ab = next(a for a in w.player["abilities"] if a.get("claimed_magnitude"))
        self.assertEqual(ab["claimed_magnitude"], 10)
        self.assertLess(ab["magnitude"], 10, "the world grants a bounded version")
        self.assertTrue(ab["cost"] > 0 or ab["reliability"] < 100, "and it comes with a price or a doubt")
        self.assertIn("一拳打爆任何東西", w.player["mind"]["self"][0]["text"], "the player still believes the claim")

    def test_talents_do_not_change_how_the_town_lived_before_you(self):
        a = new_world(63, "drifter", [], "")
        b = new_world(63, "drifter", ["medicine"], "前世是物理學家。我擁有龍族血統。我帶著一把刀。")
        story = lambda w: [(w.facts[f]["type"], w.facts[f]["roles"]) for f in w.event_log]  # noqa: E731
        self.assertEqual(story(a), story(b), "talent adjudication never consumes the world's dice")

    def test_a_talent_needs_no_matching_skill(self):
        w = new_world(64, "drifter", [], "我擁有龍族血統。")
        mine = mind.things_of(w, "player", held=False)
        self.assertTrue(mine, "a bloodline is something real in the body")

    def test_llm_reading_of_a_talent_cannot_add_claims(self):
        text = "我帶著一把刀。"
        self.assertIsNone(talents.validate_claims([{"text": "我是天下第一高手", "facet": "ability"}], text))
        ok = talents.validate_claims([{"text": "我帶著一把刀", "facet": "item", "power": 99, "result": "無敵"}], text)
        self.assertEqual(set(ok[0]), {"text", "facet", "facets", "domains", "modality", "magnitude"})
        got = talents.parse(text, llm=lambda t: [{"text": "幻想出來的天賦", "facet": "ability"}])
        self.assertEqual([c["text"] for c in got], ["我帶著一把刀"], "invalid LLM output falls back to the rules")


# ---------------------------------------------------------------- 自由行動
FREE_TEXTS = ["我想檢查這個人", "我想看看他體內有什麼異常", "我想敲敲他的肚子聽聽聲音", "我想用火燒那個東西",
              "我想把手放在他頭上祈禱", "我懷疑那是病因", "我想對著月亮唱歌", "給他一點錢", "我想去長街", "休息一下",
              "幫他治一治", "揍他", "我想研究一下我帶著的東西", "我想感覺一下自己的身體"]


class FreeActionTests(unittest.TestCase):
    def test_unscripted_phrasings_always_get_a_world_response(self):
        w = new_world(71, "herbalist", ["medicine"], "前世是一名研究超聲波的醫生。我帶著一把老菜刀。")
        stage(w, "inn", ["sun"], met=["sun"])
        mind.add_thing(w, "calculus", host="sun")
        player_mod.perform(w, "talk:sun")
        for text in FREE_TEXTS:
            with self.subTest(text=text):
                if w.pending:
                    player_mod.perform(w, player_mod.available_actions(w)[0]["id"])
                beats = player_mod.perform(w, "do", text)
                self.assertTrue(beats, "something is always reported back")
                opts = [a["id"] for a in player_mod.available_actions(w) if a["id"].startswith("do_opt:")]
                if opts:
                    player_mod.perform(w, opts[0])
                check_invariants(self, w, text)
                if w.player["location"] != "inn":
                    stage(w, "inn", ["sun"])

    def test_the_rules_follow_properties_not_names(self):
        """同一個作用，套在性質不同的東西上，結果不同——規則裡沒有任何東西的名字。"""
        outcomes = {}
        for kind in INTERNAL_KINDS:
            for modality in ("vibration", "blunt", "heat", "chemical", "cut", "qi"):
                w = new_world(72, "drifter")
                stage(w, "temple", ["aniu"], met=["aniu"])
                w.npcs["aniu"]["opinions"]["player"] = 60
                tid = mind.add_thing(w, kind, host="aniu")
                player_notices(w, tid)
                give_ability(w, modality, 5, 7)
                act.resolve(w, {"verb": "apply", "target": f"t:{tid}", "modality": modality, "means": None,
                                "purpose": "help", "text": "", "deep": True})
                check_invariants(self, w, f"{kind}/{modality}")
                f = w.facts[next(f for f in reversed(list(w.facts)) if w.facts[f]["type"] == "act")]
                outcomes[(kind, modality)] = tuple(sorted(f["data"]["effects"]))
        by_mod = {}
        for (kind, modality), eff in outcomes.items():
            by_mod.setdefault(modality, set()).add(eff)
        self.assertTrue(any(len(effs) >= 2 for effs in by_mod.values()), "different properties, different outcomes")
        self.assertGreaterEqual(len(set(outcomes.values())), 4)

    def test_an_llm_cannot_decide_what_happens(self):
        def run(extra):
            w = new_world(73, "drifter", ["medicine"], "前世是研究超聲波的醫生。")
            stage(w, "temple", ["aniu"], met=["aniu"])
            w.npcs["aniu"]["opinions"]["player"] = 60
            tid = mind.add_thing(w, "core_dense", host="aniu")
            player_notices(w, tid)
            fake = lambda system, user: {"verb": "apply", "target": f"t:{tid}", "modality": "vibration",  # noqa: E731
                                         "means": None, "purpose": "help", **extra}
            player_mod.perform(w, "do", "我想把它震碎", llm=fake)
            return w
        honest = run({})
        boasting = run({"result": "金丹被完美地震碎了", "effects": ["thing_shattered", "relief"], "success": True,
                        "integrity": 0})
        self.assertEqual(honest.state_hash(), boasting.state_hash(), "claims of outcome are thrown away")
        cands = intent.candidates(honest)
        self.assertIsNone(intent.validate_llm_intent({"verb": "apply", "target": "t:invented"}, cands, "x"))
        self.assertIsNone(intent.validate_llm_intent({"verb": "summon_dragon"}, cands, "x"))

    def test_a_guess_stays_in_the_players_head(self):
        w = new_world(74, "drifter", ["medicine"])
        stage(w, "inn", ["sun"], met=["sun"])
        tid = mind.add_thing(w, "calculus", host="sun")
        player_notices(w, tid)
        w.player["focus_thing"] = tid
        world_before = json.dumps([w.things, w.facts, w.npcs], sort_keys=True, ensure_ascii=False)
        player_mod.perform(w, "do", "我懷疑那個東西其實是一顆金丹")
        self.assertEqual(json.dumps([w.things, w.facts, w.npcs], sort_keys=True, ensure_ascii=False), world_before)
        self.assertIn("金丹", mind.belief(w.player, tid)["hypothesis"])
        self.assertNotEqual(mind.belief(w.player, tid)["concept"], "golden_core", "a guess is not knowledge")

    def test_a_mistaken_understanding_is_kept(self):
        w = new_world(75, "drifter", ["medicine"])
        stage(w, "temple", ["aniu"], met=["aniu"])
        w.npcs["aniu"]["opinions"]["player"] = 60
        tid = mind.add_thing(w, "core_dense", host="aniu")
        player_mod.perform(w, "talk:aniu")
        player_mod.perform(w, "do", "我想檢查他的身體，看看他體內有什麼")
        b = mind.belief(w.player, tid)
        self.assertIsNotNone(b, "a doctor's hands find the mass")
        self.assertIn(b["concept"], mind.concepts_of(w.player), "understood only in the player's own terms")
        dump = json.dumps(view.build(w, []), ensure_ascii=False)
        self.assertNotIn(CONCEPTS["golden_core"]["label"], dump, "nobody slipped the true name into the player's head")


# ---------------------------------------------------------------- NPC 自主、存讀檔
class AutonomyTests(unittest.TestCase):
    def test_the_world_lives_without_the_player(self):
        w = new_world(81, "drifter")
        events, gossip = len(w.event_log), w.stats.get("gossip", 0)
        idle_days(w, 20)
        self.assertGreater(len(w.event_log), events + 10)
        self.assertGreater(w.stats.get("gossip", 0), gossip)
        check_invariants(self, w, "idle")

    def test_looking_at_the_screen_never_changes_the_world(self):
        w = new_world(83, "drifter", ["medicine"], "前世是醫生。")
        rng = random.Random(3)
        for _ in range(40):
            before = w.state_hash()
            view.build(w, [])
            view.build(w, [])
            self.assertEqual(w.state_hash(), before, "building the player's view mutated the world")
            player_mod.perform(w, rng.choice([a["id"] for a in player_mod.available_actions(w)]))

    def test_minds_and_things_survive_save_and_load(self):
        w = new_world(82, "drifter", ["medicine"], "前世是研究超聲波的醫生。我帶著一把老菜刀。")
        stage(w, "inn", ["sun"], met=["sun"])
        mind.add_thing(w, "calculus", host="sun")
        player_mod.perform(w, "talk:sun")
        player_mod.perform(w, "do", "我想檢查他的身體")
        clone = World.from_dict(json.loads(json.dumps(w.to_dict())))
        self.assertEqual(clone.state_hash(), w.state_hash())
        rng = random.Random(1)
        for _ in range(20):
            acts = [a["id"] for a in player_mod.available_actions(w)]
            a = rng.choice(acts)
            player_mod.perform(w, a)
            player_mod.perform(clone, a)
        self.assertEqual(clone.state_hash(), w.state_hash())


if __name__ == "__main__":
    unittest.main()


class FreeActionFuzzTests(unittest.TestCase):
    """隨機混著自由行動玩很久：不能壞、不變量不能破、知識來源不能斷。"""

    WORDS = ["我想", "仔細", "看看", "檢查", "用震波", "用火", "用刀", "把", "那個東西", "他", "她", "體內", "打碎", "治一治",
             "敲敲", "揍", "給", "休息", "懷疑", "它", "自己", "東西", "去", "長街", "結石", "肚子", "唱歌", "祈禱"]

    def test_long_random_play_with_free_actions(self):
        for seed in (91, 92, 93):
            rng = random.Random(seed)
            w = new_world(seed, rng.choice(list(player_mod.BACKGROUNDS)), rng.sample(list(talents.SKILLS), 2),
                          rng.choice(VARIED_TALENTS))
            for step in range(220):
                acts = [a["id"] for a in player_mod.available_actions(w) if not a["id"].startswith("steal")]
                if not w.pending and rng.random() < 0.4:
                    text = "".join(rng.choice(self.WORDS) for _ in range(rng.randint(2, 6)))
                    player_mod.perform(w, "do", text)
                else:
                    player_mod.perform(w, rng.choice(acts))
                if step % 40 == 0:
                    check_invariants(self, w, f"fuzz {seed}/{step}")
            check_invariants(self, w, f"fuzz {seed} end")
