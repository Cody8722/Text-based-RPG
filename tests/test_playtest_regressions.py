"""實際遊玩時看到的問題的回歸測試（不劇透：只用結構與既有的地點／時辰資料，不寫死任何劇情句子）。

1～2 場景只在抵達時建立；同一個地方的後續回合從剛發生的事寫起
3    說書人不能自己加世界事件、人、數字
4    時辰／天氣不能被說書人改掉，環境沒變的回合不重畫
5～7 自由行動解析：target／means 一定來自伺服器候選、不接受不完整的 id、詞表可靠時不呼叫 LLM
8    autosave 本身就是縮排過的 JSON，讀回來狀態完全一樣
（9 前端不顯示 HTML 實體：在 tests/ui_e2e.js 用真的瀏覽器檢查）
"""

import json
import os
import tempfile
import unittest

from support import FakeOllama, new_world

from rpg import intent, mind
from rpg import player as player_mod
from rpg.content.locations import LOCATIONS
from rpg.game import Game, intro_beats
from rpg.narrator import (EVENT_WORDS, NAME_INDEX, TIME_ALLOWED, TIME_WORDS, WEATHER_CONTRADICTS, Narrator, check, ngrams,
                          scene_grams)


def play(w, aid):
    """跟遊戲一樣做一個動作；途中撞見要當場決定的事就先處理掉。"""
    beats = player_mod.perform(w, aid)
    while w.pending:
        pend = next(a["id"] for a in player_mod.available_actions(w) if a["id"].startswith("pend:"))
        beats += player_mod.perform(w, pend)
    return beats


def allowed_time_word(ctx):
    """這個時辰本來可以用的時間詞（寫對了時辰，只是不該在這一回合重畫環境）。"""
    return next(x for g in sorted(TIME_ALLOWED[ctx["period"]]) for x in TIME_WORDS[g] if x not in ctx["template"])


def opening():
    w = new_world(5, "herbalist")
    beats = intro_beats(w)
    w.pending = None
    return w, beats


# ---------------------------------------------------------------- 1～2 場景連續
class SceneContinuityTests(unittest.TestCase):
    def test_staying_put_is_told_from_what_just_happened(self):
        w, beats = opening()
        ctx0 = Narrator.build_context(w, beats, None)
        self.assertEqual(ctx0["mode"], "establish", "arriving at the start establishes the place")
        told = Narrator.environment(w)
        ctx = Narrator.build_context(w, play(w, "look"), told)
        self.assertEqual(ctx["mode"], "continue")
        self.assertFalse(ctx["env_changed"], "a short look keeps the same period and weather")
        system, user = Narrator.prompts(ctx)
        self.assertNotIn("【場景】", user, "the full scene line is only sent when it can change")
        self.assertNotIn("此刻的氣氛", system)
        tpl = ctx["template"]
        here = LOCATIONS[ctx["place"]]
        self.assertIsNotNone(check("你靜靜看著。" + tpl, ctx)[0], "plain retelling of what happened is fine")
        self.assertEqual(check(allowed_time_word(ctx) + "裡，" + tpl, ctx)[1], "scene_repaint")
        if here["name"] not in tpl:   # 片段自己提到地名（例如某人的身分帶著地名）時，說書人照著說不算重新介紹
            self.assertEqual(check(f"你在{here['name']}四下張望。" + tpl, ctx)[1], "scene_repaint")
        self.assertEqual(check(tpl + here["day"], ctx)[1], "scene_reintro")

    def test_a_change_of_time_can_be_mentioned_once_but_must_be_right(self):
        w, beats = opening()
        prev = (w.player["location"], (w.period - 1) % 6, w.weather)
        ctx = Narrator.build_context(w, play(w, "look"), prev)
        self.assertTrue(ctx["env_changed"] and ctx["shift"])
        system, user = Narrator.prompts(ctx)
        self.assertIn(ctx["shift"], system)
        self.assertIn("【此刻】", user)
        self.assertNotIn(LOCATIONS[ctx["place"]]["name"], user.split("【本段已發生的事】")[0], "no place name to re-establish")
        tpl = ctx["template"]
        self.assertIsNotNone(check(allowed_time_word(ctx) + "裡，" + tpl, ctx)[0])
        wrong = next(x for g, ws in TIME_WORDS.items() if g not in TIME_ALLOWED[ctx["period"]] for x in ws if x not in tpl)
        self.assertEqual(check(wrong + "裡，" + tpl, ctx)[1], "time")

    def test_first_visit_to_a_new_place_establishes_it(self):
        w, beats = opening()
        told = Narrator.environment(w)
        move = next(a["id"] for a in player_mod.available_actions(w) if a["id"].startswith("move:"))
        beats = play(w, move)
        arrive = [b for b in beats if b["kind"] == "arrive"]
        self.assertTrue(arrive and arrive[0]["scene"] == "establish")
        ctx = Narrator.build_context(w, beats, told)
        self.assertEqual(ctx["mode"], "establish")
        system, user = Narrator.prompts(ctx)
        self.assertIn("【場景】", user)
        text = allowed_time_word(ctx) + "裡，" + ctx["template"] + "四周的一切都還陌生。"
        self.assertIsNotNone(check(text, ctx)[0], check(text, ctx)[1])

    def test_coming_back_soon_is_brief(self):
        w, beats = opening()
        start = w.player["location"]
        move = next(a["id"] for a in player_mod.available_actions(w) if a["id"].startswith("move:"))
        play(w, move)
        told = Narrator.environment(w)
        beats = play(w, f"move:{start}")
        arrive = [b for b in beats if b["kind"] == "arrive"]
        self.assertEqual(arrive[0]["scene"], "return", "the opening counts as a visit")
        ctx = Narrator.build_context(w, beats, told)
        self.assertEqual(ctx["mode"], "return")
        self.assertNotIn(LOCATIONS[start]["day"], ctx["template"])
        self.assertEqual(check(ctx["template"] + LOCATIONS[start]["day"], ctx)[1], "scene_reintro")
        # 換個說法講「到了」是可以的（片段本身就是抵達）
        name = LOCATIONS[start]["name"]
        again = ctx["template"].replace(f"你來到{name}", f"你又踏入{name}") + "你放慢了腳步，左右看了看。"
        self.assertIsNotNone(check(again, ctx)[0], check(again, ctx)[1])

    def test_the_opening_describes_each_thing_once(self):
        w, beats = opening()
        place = scene_grams(w.player["location"])
        texts = [b["text"] for b in beats]
        for i, a in enumerate(texts):
            for b in texts[i + 1:]:
                self.assertFalse(ngrams(a) & ngrams(b) & place, f"described twice:\n{a}\n{b}")


# ---------------------------------------------------------------- 3 說書人不能加事件
class StorytellerAddsNothingTests(unittest.TestCase):
    def _ctx(self):
        w, beats = opening()
        told = Narrator.environment(w)
        return w, Narrator.build_context(w, play(w, "look"), told)

    def test_invented_people_numbers_and_events_are_rejected(self):
        w, ctx = self._ctx()
        tpl = ctx["template"]
        present = {NAME_INDEX[n] for n in ctx["names"] if n in NAME_INDEX}
        stranger = next(a for a, nid in NAME_INDEX.items() if nid not in present and a not in tpl)
        ambient = next(x for x in LOCATIONS[ctx["place"]]["ambient"] if x not in tpl)
        cases = {
            "extra_name": tpl + f"{stranger}從一旁走過。",
            "digits": tpl + "遠處傳來3聲響。",
            "invented_event": tpl + "遠處有人" + next(x for x in EVENT_WORDS if x not in tpl) + "。",
        }
        for want, text in cases.items():
            self.assertEqual(check(text, ctx)[1], want, text)
        # 這個地方「會自己發生的小事」只能由世界決定要不要發生
        self.assertEqual(check(tpl + ambient, ctx)[1], "invented_event")

    def test_a_rejected_invention_shows_the_template_and_changes_nothing(self):
        w, ctx = self._ctx()
        ambient = next(x for x in LOCATIONS[ctx["place"]]["ambient"] if x not in ctx["template"])
        fake = FakeOllama(lambda body: json.dumps({"narrative": ctx["template"] + ambient}, ensure_ascii=False))
        try:
            nar = Narrator(mode="ollama", url=fake.url)
            before = w.state_hash()
            rec = nar.narrate_ctx(ctx)
            self.assertEqual((rec["source"], rec["reason"]), ("template", "invented_event"))
            self.assertEqual(rec["text"], ctx["template"])
            self.assertEqual(w.state_hash(), before)
        finally:
            fake.close()


# ---------------------------------------------------------------- 4 時辰與天氣
class TimeAndWeatherTests(unittest.TestCase):
    def test_one_passage_cannot_hold_two_times_of_day(self):
        w, beats = opening()
        ctx = Narrator.build_context(w, beats, None)
        ok = allowed_time_word(ctx)
        other = next(x for g, ws in TIME_WORDS.items() if g not in TIME_ALLOWED[ctx["period"]] for x in ws)
        self.assertIsNotNone(check(ok + "未散。" + ctx["template"], ctx)[0])
        self.assertEqual(check(ok + "未散。" + ctx["template"] + other + "的光照在地上。", ctx)[1], "time")

    def test_weather_cannot_be_rewritten(self):
        w, beats = opening()
        ctx = Narrator.build_context(w, beats, None)
        clash = WEATHER_CONTRADICTS[ctx["weather"]][0]
        self.assertEqual(check(ctx["template"] + clash + "的街上。", ctx)[1], "weather")


# ---------------------------------------------------------------- 5～7 自由行動解析
def staged():
    w = new_world(301, "herbalist", ["medicine"], "前世是一名研究超聲波的醫生。我帶著一把老菜刀。")
    w.pending = None
    w.player["location"] = "inn"
    for nid, n in w.npcs.items():
        if nid == "sun":
            n["status"], n["location"] = "normal", "inn"
        elif n["location"] == "inn":
            n["location"] = "street"
    w.player["met"].append("sun")
    tid = mind.add_thing(w, "calculus", host="sun")
    mind.believe_thing(w, "player", tid, mind.noticeable(w, w.player, w.things[tid], contact=True), "self")
    player_mod.perform(w, "talk:sun")
    return w, tid


class ParserTests(unittest.TestCase):
    def test_schema_only_allows_this_requests_candidates(self):
        w, _ = staged()
        cands = intent.candidates(w)
        system, user, schema = intent.llm_prompt("隨便做點什麼", cands)
        props = schema["properties"]
        self.assertEqual(props["target"]["enum"], [c["id"] for c in cands["targets"]] + [None])
        self.assertEqual(props["means"]["enum"], [m["id"] for m in cands["means"]] + [None])
        self.assertEqual(props["modality"]["enum"], intent.MODALITIES + [None])
        self.assertEqual(props["purpose"]["enum"], intent.PURPOSES + [None])
        for c in cands["targets"]:
            self.assertIn(c["id"], user)

    def test_an_id_must_be_copied_exactly(self):
        w, tid = staged()
        cands = intent.candidates(w)
        short = f"t:{tid}"[2:]
        self.assertIsNone(intent.validate_llm_intent({"verb": "apply", "target": short}, cands, "x"))
        self.assertIsNone(intent.validate_llm_intent({"verb": "apply", "target": "p:nobody"}, cands, "x"))
        self.assertIsNone(intent.validate_llm_intent({"verb": "apply", "target": f"t:{tid}", "means": "a:zz"}, cands, "x"))
        got = intent.validate_llm_intent({"verb": "apply", "target": f"t:{tid}", "outcome": "shattered"}, cands, "x")
        self.assertEqual(got["target"], f"t:{tid}")
        self.assertNotIn("outcome", got, "nothing beyond the closed fields survives")

    def test_a_bad_llm_answer_falls_back_without_breaking(self):
        w, tid = staged()
        text = "利用超音波碎石術破壞金丹"
        it, opts = intent.parse(w, text, llm=lambda *a: {"verb": "treat", "target": f"t:{tid}"[2:], "purpose": "harm"})
        ids = {c["id"] for c in intent.candidates(w)["targets"]}
        self.assertTrue(it is None or it["target"] in ids | {None})
        self.assertTrue(it or opts is not None)

    def test_plain_inputs_the_rules_understand_do_not_call_the_llm(self):
        w, _ = staged()
        calls = []

        def llm(system, user, schema):
            calls.append(user)
            return {"verb": "other", "target": None}

        for text in ("我想檢查這個人", "我想敲敲他的腰", "我想摸摸我帶著的那把刀", "我想用震波把石淋打碎"):
            with self.subTest(text=text):
                calls.clear()
                it, _ = intent.parse(w, text, llm=llm)
                self.assertTrue(it, "the rules understood it")
                self.assertEqual(calls, [], "no LLM call for an input the rules handle reliably")
        # 開放式的說法、一句話裡有兩種動作、指代不明：才交給 LLM
        for text in ("利用超音波碎石術破壞金丹", "我想對著月亮唱歌", "我想敲敲他的腰，聽聽裡面的聲音", "我想用震波把那顆東西打碎"):
            with self.subTest(text=text):
                calls.clear()
                intent.parse(w, text, llm=llm)
                self.assertEqual(len(calls), 1, "open-ended input goes to the LLM once")


# ---------------------------------------------------------------- 8 存檔
class AutosaveTests(unittest.TestCase):
    def test_autosave_is_indented_readable_json_and_round_trips(self):
        g = Game(save_dir=tempfile.mkdtemp(), narrator=Narrator(mode="off"))
        g.new("herbalist", seed=11)
        for _ in range(4):
            aid = next(a["id"] for a in player_mod.available_actions(g.world) if a["id"] in ("wait", "look")
                       or a["id"].startswith("pend:"))
            g.act(aid)
        with open(g.save_path, encoding="utf-8") as f:
            raw = f.read()
        self.assertTrue(raw.startswith('{\n  "'), "indented with two spaces")
        self.assertNotIn("\\u", raw, "Chinese is written as-is, not escaped")
        self.assertTrue(any("一" <= ch <= "鿿" for ch in raw))
        self.assertEqual(json.loads(raw), g.world.to_dict(), "same data as the world")
        loaded = g.load()
        self.assertEqual(loaded.to_dict(), g.world.to_dict())
        # 讀回來之後繼續玩，跟沒存讀檔的世界走得一模一樣
        aid = next(a["id"] for a in player_mod.available_actions(loaded) if a["id"] == "wait")
        player_mod.perform(loaded, aid)
        player_mod.perform(g.world, aid)
        self.assertEqual(loaded.state_hash(), g.world.state_hash())
        self.assertFalse(os.path.exists(g.save_path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
