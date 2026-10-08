"""真模型整合測試：接上本機 Ollama（預設 qwen3.5:9b），在固定的世界情境下讓說書人真的跑。

不檢查模型說了「哪一句話」——模型可以自由表達。檢查的是邊界：
- 顯示給玩家的文字，一條契約都不能越過（越界的輸出必須被擋下、退回模板）。
- 說書人永遠不改變世界狀態。
- 只有台詞的回合不經過模型。
- 統計模型實際的接受率／退回率／各類越界次數，寫成報告。

連不上 Ollama 或模型不存在 → 整個模組 SKIP（環境問題，不是遊戲錯誤）。
執行：python -m tests_llm      （或 pytest -m llm）
"""

from __future__ import annotations

import os
import unittest

from rpg.narrator import Narrator

from . import harness, ollama_env, scenarios

_RESULTS: dict[str, dict] = {}
_NARRATOR: Narrator | None = None
_ENV = {}


def setUpModule():
    ok, why = ollama_env.availability()
    if not ok:
        raise unittest.SkipTest(f"LLM UNAVAILABLE — {why}")
    global _NARRATOR
    s = ollama_env.settings()
    _ENV.update(s, banner=why)
    _NARRATOR = Narrator(mode="ollama", url=s["url"], model=s["model"], timeout=s["timeout"])
    print(f"\n[llm] {why}; long play = {scenarios.long_turns()} narrated turns", flush=True)


def tearDownModule():
    if not _RESULTS:
        return
    results = [_RESULTS[s.name] for s in scenarios.SCENARIOS if s.name in _RESULTS]
    summary = harness.summarize(results, model=_ENV.get("model", ""))
    path = harness.save(results, summary)
    print("\n" + harness.format_report(summary), flush=True)
    print(f"[llm] full transcript: {path}", flush=True)


def result(name: str) -> dict:
    if name not in _RESULTS:
        sc = scenarios.BY_NAME[name]
        print(f"[llm] running {name} …", flush=True)
        _RESULTS[name] = harness.run_scenario(sc, _NARRATOR)
    return _RESULTS[name]


def calls(r):
    return [t for t in r["turns"] if "source" in t]


class Base(unittest.TestCase):
    def assertWithinContract(self, r):
        leaked = [(t["step"], t["action"], t["shown_violations"], t["shown"]) for t in calls(r) if t["shown_violations"]]
        self.assertEqual(leaked, [], "a contract violation reached the player (validator gap)")
        self.assertEqual(r["hash_mismatch"], 0, "narration changed the world state")
        self.assertEqual(r["shadow_mismatch"], 0, "the world diverged from the same play without a storyteller")


class ScenarioTests(Base):
    def test_arrival_then_staying_in_one_place(self):
        r = result("arrive_then_stay")
        self.assertWithinContract(r)
        c = calls(r)
        self.assertTrue(c and c[0]["arrived"], "the first narrated turn is the arrival")
        self.assertTrue(all(not t["arrived"] for t in c[1:]), "later turns are not arrivals")
        self.assertFalse([t for t in c[1:] if "scene_reintro" in t["shown_violations"]])

    def test_dialogue_only_turns_never_reach_the_model(self):
        r = result("dialogue_only")
        self.assertWithinContract(r)
        only = [t for t in r["turns"] if t["kind"] == "dialogue_only"]
        self.assertTrue(only, "scenario must contain dialogue-only turns")
        self.assertTrue(all("source" not in t for t in only))

    def test_mentioned_person_stays_off_stage(self):
        r = result("absent_mentioned")
        self.assertWithinContract(r)
        self.assertTrue(any("孫掌櫃" in t["absent"] for t in calls(r)), "scenario must mention an absent person")

    def test_crowded_room(self):
        r = result("crowded_tavern")
        self.assertWithinContract(r)
        self.assertTrue(any(len(t["on_stage"]) >= 3 for t in calls(r)))

    def test_private_notes_and_secrets_are_not_told(self):
        r = result("private_persona")
        self.assertWithinContract(r)
        w = scenarios.BY_NAME["private_persona"].setup()
        for t in calls(r):
            for persona in scenarios.personas_present(w):
                self.assertNotIn(persona, t["prompt"], "persona notes never go into the prompt")

    def test_time_of_day_and_weather_hold(self):
        for p, wx in scenarios.TIME_SWEEP:
            with self.subTest(period=p, weather=wx):
                r = result(f"time_{p}")
                self.assertWithinContract(r)
                c = calls(r)
                self.assertTrue(c)
                self.assertTrue(all(t["period"] == p and t["weather"] == wx for t in c), "scenario stayed in its time slot")


class LongPlayTests(Base):
    def test_long_play_stays_within_contract(self):
        r = result("long_play")
        self.assertWithinContract(r)
        self.assertGreaterEqual(len(calls(r)), min(10, scenarios.long_turns()))


class ModelUsefulnessTests(unittest.TestCase):
    """契約之外：模型有沒有真的在講故事。下限可以用環境變數收緊。"""

    def test_model_output_is_actually_used(self):
        for s in scenarios.SCENARIOS:
            result(s.name)
        summary = harness.summarize(list(_RESULTS.values()))
        n = summary["llm_calls"]
        self.assertGreater(n, 0)
        rate = summary["accepted"] / n
        floor = float(os.environ.get("RPG_LLM_MIN_ACCEPT", "0"))
        self.assertGreater(summary["accepted"], 0, "the model never produced a usable narration")
        self.assertGreaterEqual(rate, floor, f"acceptance {rate:.0%} below RPG_LLM_MIN_ACCEPT={floor:.0%}")
        self.assertLess(summary["errors"], n, "every call errored or timed out")
