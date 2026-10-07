"""真模型整合測試（tests_llm/）的測試架構本身——不需要 Ollama，跟快速測試一起跑。

真模型那一套只有在本機有 Ollama 時才會跑；這裡確保它在沒有模型時也是可信的：
- 情境是確定的、而且真的涵蓋它宣稱的條件（剛抵達、只被提到的人、多人在場、各個時辰……）。
- 契約檢查器抓得到每一類越界，也不會誤判遊戲自己的模板。
- 契約檢查器會抓的每一類越界，production 驗證器都會擋（否則越界內容就會給到玩家）。
- 用一個會故意越界的假 Ollama 跑完整條流程：越界的輸出全被擋下、世界狀態不變、統計正確。
- 連不上 Ollama 時，入口明確顯示 UNAVAILABLE、結束碼 0。
"""

import json
import os
import subprocess
import sys
import unittest

from support import ROOT, FakeOllama, template_from_request

from rpg.content.locations import LOCATIONS
from rpg.narrator import Narrator, check
from tests_llm import contract, harness, ollama_env, scenarios


def dry(name, turns=None):
    return harness.run_scenario(scenarios.BY_NAME[name], None, narrated_turns=turns)


def ctxs(r):
    return [t for t in r["turns"] if t["kind"] == "llm"]


class ScenarioTests(unittest.TestCase):
    def test_scenarios_are_deterministic(self):
        for s in scenarios.SCENARIOS:
            with self.subTest(s.name):
                a = dry(s.name, 8 if s.policy else None)
                b = dry(s.name, 8 if s.policy else None)
                self.assertEqual([t.get("template") for t in a["turns"]], [t.get("template") for t in b["turns"]])
                self.assertEqual(a["shadow_mismatch"], 0)

    def test_scenarios_cover_what_they_claim(self):
        c = ctxs(dry("arrive_then_stay"))
        self.assertTrue(c[0]["arrived"] and not any(t["arrived"] for t in c[1:]))
        self.assertGreaterEqual(len(c), 5)
        self.assertTrue(any(t["kind"] == "dialogue_only" for t in dry("dialogue_only")["turns"]))
        self.assertTrue(any("孫掌櫃" in t["absent"] and "吳伯" in t["on_stage"] for t in ctxs(dry("absent_mentioned"))))
        self.assertTrue(any(len(t["on_stage"]) >= 3 for t in ctxs(dry("crowded_tavern"))))
        for p, wx in scenarios.TIME_SWEEP:
            c = ctxs(dry(f"time_{p}"))
            self.assertTrue(c and all(t["period"] == p and t["weather"] == wx for t in c), p)
        w = scenarios.BY_NAME["private_persona"].setup()
        self.assertTrue(any(f["secrecy"] == "secret" and f["id"] not in w.player["knows"] for f in w.facts.values()))
        prompts = [t["prompt"] for t in ctxs(dry("private_persona"))]
        for persona in scenarios.personas_present(w):
            self.assertFalse(any(persona in p for p in prompts))
        self.assertEqual(len(ctxs(dry("long_play", 15))), 15)

    def test_game_templates_pass_the_contract(self):
        """退回模板時給玩家看的就是模板——模板自己必須在契約之內。"""
        for s in scenarios.SCENARIOS:
            r = scenarios.BY_NAME[s.name]
            for w, aid, beats in _walk(r, 25):
                ctx = Narrator.build_context(w, beats)
                if ctx:
                    self.assertEqual(contract.audit(ctx["template"], ctx, w), [], f"{s.name}/{aid}: {ctx['template']}")


def _walk(sc, limit):
    for i, item in enumerate(scenarios.iterate(sc)):
        if i >= limit:
            return
        yield item


def violations_for(ctx, w):
    """在一段乾淨的輸出（模板本身）上，各加一種越界。"""
    tpl = ctx["template"]
    stranger = next(n["call"] for n in w.npcs.values() if n["call"] not in tpl)
    out = {
        "length": tpl + "風" * (len(tpl) * 2 + 100),
        "digits": tpl + "他順手塞給你99文。",
        "cast_extra": tpl + f"{stranger}也坐在一旁。",
        "companions": tpl + "你們幾個人圍在一起。",
        "time": tpl + contract.TIME_CLASH[ctx["period"]][0] + "照在地上。",
        "weather": tpl + contract.WEATHER_CLASH[ctx["weather"]][0] + "的景象。",
        "invented_event": tpl + "遠處有人昏倒了。",
        "simplified": tpl + "这时风大了。",
        "format": "{" + tpl,
    }
    quotes = contract.QUOTE.findall(tpl)
    if quotes:
        q = quotes[0]
        out["dialogue"] = tpl.replace(f"「{q}」", f"「{q}吧」", 1)         # 多加了字
        out["dialogue_swap"] = tpl.replace(f"「{q}」", f"「{'啊' + q[1:]}」", 1)  # 改了字
    if ctx["absent"]:
        out["absent_on_stage"] = tpl + f"{ctx['absent'][0]}走了過來，站在你身邊。"
    if not ctx["arrived"]:
        out["scene_reintro"] = tpl + LOCATIONS[ctx["place"]]["day"]
    return out


class ContractTests(unittest.TestCase):
    def _cases(self):
        for name in ("arrive_then_stay", "absent_mentioned", "time_4", "crowded_tavern"):
            for w, aid, beats in _walk(scenarios.BY_NAME[name], 8):
                ctx = Narrator.build_context(w, beats)
                if ctx:
                    yield name, aid, ctx, w

    def test_checker_catches_every_category(self):
        seen = set()
        for name, aid, ctx, w in self._cases():
            for cat, text in violations_for(ctx, w).items():
                with self.subTest(scenario=name, action=aid, category=cat):
                    cat = cat.split("_swap")[0]
                    self.assertIn(cat, contract.audit(text, ctx, w))
                    seen.add(cat)
        self.assertGreaterEqual(seen, set(contract.CATEGORIES) - {"persona_leak", "secret_leak"})

    def test_production_validator_blocks_what_the_checker_flags(self):
        """契約的每一類越界，production 驗證器都必須擋下（否則就會給到玩家）。"""
        for name, aid, ctx, w in self._cases():
            for cat, text in violations_for(ctx, w).items():
                with self.subTest(scenario=name, action=aid, category=cat):
                    shown, reason = check(text, ctx)
                    self.assertIsNone(shown, f"validator let a '{cat}' violation through")
                    self.assertIsNotNone(reason)

    def test_free_retelling_is_not_a_violation(self):
        """自由改寫（加動作、神情、氣氛，台詞照抄）不算越界——測試不要求任何特定句子。"""
        for name, aid, ctx, w in self._cases():
            text = "你靜靜看著。" + ctx["template"].replace("\n", "") + "風輕輕吹過。"
            self.assertEqual(contract.audit(text, ctx, w), [], f"{name}/{aid}")
            self.assertIsNotNone(check(text, ctx)[0], f"{name}/{aid}: {check(text, ctx)[1]}")


class FakeModelRunTests(unittest.TestCase):
    """用會故意越界的假模型跑完整條流程（真模型測試用的就是同一個 harness）。"""

    def test_violations_never_reach_the_player_and_stats_add_up(self):
        n = {"i": 0}

        def responder(body):
            tpl = template_from_request(body)
            n["i"] += 1
            k = n["i"] % 4
            if k == 0:
                return json.dumps({"narrative": "你靜靜看著。" + tpl.replace("\n", "")}, ensure_ascii=False)
            if k == 1:
                return json.dumps({"nationale": "你靜靜看著。" + tpl.replace("\n", "")}, ensure_ascii=False)
            if k == 2:
                return json.dumps({"narrative": tpl + "你們幾個人圍在一起，月光照在地上。"}, ensure_ascii=False)
            return "抱歉，我沒辦法。"

        fake = FakeOllama(responder)
        try:
            nar = Narrator(mode="ollama", url=fake.url, timeout=5)
            results = [harness.run_scenario(scenarios.BY_NAME[x], nar) for x in ("arrive_then_stay", "absent_mentioned")]
        finally:
            fake.close()
        s = harness.summarize(results, model="fake")
        self.assertEqual(s["shown_violations"], {}, "nothing that breaks the contract is shown")
        self.assertEqual(s["hash_mismatch"] + s["shadow_mismatch"], 0)
        self.assertEqual(s["accepted"] + s["fallback"] + s["errors"], s["llm_calls"])
        self.assertGreater(s["accepted"], 0)
        self.assertGreater(s["schema_key_fixed"], 0, "a misnamed single text field is still used")
        self.assertIn("companions", s["raw_violations"])
        self.assertIn("time", s["raw_violations"])
        self.assertGreater(s["errors"], 0, "a non-JSON reply is an error, shown as the template")
        report = harness.format_report(s)
        for word in ("LLM calls", "accepted", "fallback", "Reached the player"):
            self.assertIn(word, report)


class AvailabilityTests(unittest.TestCase):
    def test_unreachable_and_missing_model_are_reported_not_failed(self):
        ok, why = ollama_env.availability("http://127.0.0.1:9", "qwen3.5:9b")
        self.assertFalse(ok)
        self.assertIn("not reachable", why)
        fake = FakeOllama(lambda b: "{}", model="something-else")
        try:
            ok, why = ollama_env.availability(fake.url, "qwen3.5:9b")
        finally:
            fake.close()
        self.assertFalse(ok)
        self.assertIn("not installed", why)

    def test_runner_skips_cleanly_without_ollama(self):
        env = dict(os.environ, RPG_OLLAMA_URL="http://127.0.0.1:9")
        r = subprocess.run([sys.executable, "-m", "tests_llm"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("LLM UNAVAILABLE", r.stdout)
        r = subprocess.run([sys.executable, "-m", "tests_llm", "--require"], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 3)

    def test_llm_module_skips_without_ollama(self):
        env = dict(os.environ, RPG_OLLAMA_URL="http://127.0.0.1:9")
        r = subprocess.run([sys.executable, "-m", "unittest", "-v", "tests_llm.llm_narrator_e2e"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skipped", r.stderr.lower())
        self.assertIn("LLM UNAVAILABLE", r.stderr)


if __name__ == "__main__":
    unittest.main()
