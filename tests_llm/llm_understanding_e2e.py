"""真模型：LLM 當「理解器」——解析自由行動與自訂天賦——時，能不能穩定工作，而且不能越權。

不檢查 LLM 理解出「哪一個」意圖（理解可以有不同的合理答案），檢查的是邊界：
- LLM 的輸出一定經過白名單：target／means 只能是伺服器列的候選，天賦主張只能是玩家原文的片段。
- 不管 LLM 怎麼理解，結果都由世界規則決定；解析不出或不合格就退回詞表解析，不會壞、不會卡。
- 世界狀態只因世界規則改變：用 LLM 理解出的意圖去做，跟把同一個意圖直接交給世界模擬器做，結果完全一樣。
另外統計：LLM 輸出可用的比例、跟詞表解析的一致程度。
"""

from __future__ import annotations

import json
import unittest

from rpg import act, intent, mind, talents
from rpg import player as player_mod
from rpg.narrator import Narrator
from rpg.world import World, new_world

from . import ollama_env

TALENT_TEXTS = [
    "前世是一名專門研究超聲波碎石術的泌尿科醫生。",
    "我擁有龍族血統，而且我帶著一把陪伴我轉生的老菜刀。",
    "我能一拳打爆任何東西。",
    "我可以看到普通人看不到的東西。",
    "我會說貓的語言，每到月圓就會長出尾巴。",
]
ACTION_TEXTS = [
    "我想檢查這個人",
    "我想看看他體內有什麼異常",
    "我懷疑那個東西就是他不舒服的原因",
    "我想用震波把那顆東西打碎",
    "我想敲敲他的腰，聽聽裡面的聲音",
    "幫他治一治",
    "我想對著月亮唱歌",
    "我想摸摸我帶著的那把刀",
]

STATS = {"talent_calls": 0, "talent_valid": 0, "intent_calls": 0, "intent_valid": 0, "agree_verb": 0,
         "agree_target": 0, "errors": 0}
_NAR: Narrator | None = None


def setUpModule():
    ok, why = ollama_env.availability()
    if not ok:
        raise unittest.SkipTest(f"LLM UNAVAILABLE — {why}")
    global _NAR
    s = ollama_env.settings()
    _NAR = Narrator(mode="ollama", url=s["url"], model=s["model"], timeout=s["timeout"])


def tearDownModule():
    if STATS["intent_calls"] or STATS["talent_calls"]:
        t, i = STATS["talent_calls"], STATS["intent_calls"]
        print("\n" + "=" * 64 + "\nLLM 理解器（解析行動與天賦）實測\n" + "=" * 64, flush=True)
        print(f"Talent parses: {t}  usable after validation: {STATS['talent_valid']}/{t}", flush=True)
        print(f"Action parses: {i}  usable after validation: {STATS['intent_valid']}/{i}  "
              f"same verb as rules: {STATS['agree_verb']}/{i}  same target as rules: {STATS['agree_target']}/{i}", flush=True)
        print(f"Errors/timeouts (fell back to rules): {STATS['errors']}\n" + "=" * 64, flush=True)


def staged():
    w = new_world(301, "herbalist", ["medicine"], "前世是一名專門研究超聲波碎石術的泌尿科醫生。我帶著一把老菜刀。")
    w.pending = None
    w.player["location"] = "inn"
    for nid, n in w.npcs.items():
        if nid == "sun":
            n["status"], n["location"] = "normal", "inn"
        elif n["location"] == "inn":
            n["location"] = "street"
    w.player["met"].append("sun")
    w.npcs["sun"]["opinions"]["player"] = 60
    tid = mind.add_thing(w, "calculus", host="sun")
    mind.believe_thing(w, "player", tid, mind.noticeable(w, w.player, w.things[tid], contact=True), "self")
    player_mod.perform(w, "talk:sun")
    return w


class TalentUnderstandingTests(unittest.TestCase):
    def test_llm_reading_of_talents_stays_within_the_players_words(self):
        llm = _NAR.talent_llm()
        for text in TALENT_TEXTS:
            with self.subTest(text=text):
                STATS["talent_calls"] += 1
                try:
                    raw = llm(text)
                except Exception:
                    STATS["errors"] += 1
                    raw = None
                got = talents.validate_claims(raw, text)
                if got:
                    STATS["talent_valid"] += 1
                    for c in got:
                        self.assertIn(c["text"], text, "a claim can only quote the player's own words")
                claims = talents.parse(text, llm=lambda t: raw)
                self.assertTrue(claims, "something usable always comes out (LLM or rules)")
                w = new_world(302, "drifter", [], "")
                talents.adjudicate(w, "player", claims)       # the world, not the LLM, decides what they mean


class ActionUnderstandingTests(unittest.TestCase):
    def test_llm_reading_of_actions_cannot_decide_outcomes(self):
        base = staged()
        snapshot = json.dumps(base.to_dict())
        llm = _NAR.intent_llm()
        for text in ACTION_TEXTS:
            with self.subTest(text=text):
                STATS["intent_calls"] += 1
                w = World.from_dict(json.loads(snapshot))
                cands = intent.candidates(w)
                raw = None
                try:
                    raw = llm(*intent.llm_prompt(text, cands))
                except Exception:
                    STATS["errors"] += 1
                llm_it = intent.validate_llm_intent(raw, cands, text)
                rule_it, _ = intent.parse_rules(w, text, cands)
                if llm_it:
                    STATS["intent_valid"] += 1
                    self.assertIn(llm_it["target"], {c["id"] for c in cands["targets"]} | {None})
                    if rule_it:
                        STATS["agree_verb"] += llm_it["verb"] == rule_it["verb"]
                        STATS["agree_target"] += llm_it["target"] == rule_it["target"]
                    # 用 LLM 理解出的意圖去做 ＝ 把同一個意圖直接交給世界：LLM 說的任何其他東西都不影響結果
                    a = World.from_dict(json.loads(snapshot))
                    b = World.from_dict(json.loads(snapshot))
                    player_mod.perform(a, "do", text, llm=lambda s, u: raw)
                    b.feed = []
                    b.player["turn"] += 1
                    player_mod.see_faces(b)
                    act.resolve(b, dict(llm_it))
                    player_mod.see_faces(b)
                    player_mod.after_action(b)
                    for x in (a, b):
                        x.flags.pop("_do_opts", None)
                        x.player.pop("last_intent", None)
                    self.assertEqual(a.things, b.things)
                    self.assertEqual({k: v["health"] for k, v in a.npcs.items()}, {k: v["health"] for k, v in b.npcs.items()})
                # 不管 LLM 怎麼回，這一步都要正常完成
                c = World.from_dict(json.loads(snapshot))
                beats = player_mod.perform(c, "do", text, llm=lambda s, u: raw)
                self.assertTrue(beats)
