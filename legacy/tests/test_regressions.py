"""Regression tests for MVP_AUDIT.md items 1 and 2.

Run from the repo root:  python3 -m unittest discover -s tests -v

All external services (Ollama, Qdrant, cloud option API) are mocked; no network is needed.
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import game_mvp as g  # noqa: E402

_INITIAL_STATE = copy.deepcopy(g.state)


def _fake_response(payload: dict):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def _ollama_post(narrative="敘事內容", fail_call2=False):
    """requests.post replacement: Call1 returns a valid narrative, Call2 optionally fails."""

    def post(url, json=None, **kwargs):  # noqa: A002 (mirror requests' kwarg name)
        fmt = (json or {}).get("format")
        if fmt is g.AFFINITY_SCHEMA:
            if fail_call2:
                raise requests.exceptions.Timeout("call2 timeout")
            content = '{"affinity_delta": 1}'
        else:
            content = '{"narrative": "%s", "memory_note": "一句摘要", "flags_set": []}' % narrative
        return _fake_response({"message": {"content": content}})

    return post


class GameTestCase(unittest.TestCase):
    def setUp(self):
        g.state = copy.deepcopy(_INITIAL_STATE)
        g.conversation_history = {npc_id: [] for npc_id in g.NPCS}
        patches = [
            mock.patch.object(g, "MEMORY_ENABLED", False),  # no Qdrant / embedding calls
            mock.patch.object(g, "ensure_memory_collection"),
            mock.patch.object(g, "call_cloud_option_llm", return_value=None),  # no cloud call
            mock.patch.object(g, "print_typewriter"),
            mock.patch("builtins.print"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_main_choosing(self, option_id: str, times: int):
        """Drive main() choosing `option_id` whenever it is on the menu, at most `times` times, then quit.
        Returns how many times the option was actually offered-and-chosen."""
        chosen = []

        def fake_input(_prompt=""):
            visible = g.get_visible_options(g.SCENES[g.state["location"]]["options"])
            ids = [o["id"] for o in visible]
            if option_id in ids and len(chosen) < times:
                chosen.append(option_id)
                return str(ids.index(option_id) + 1)
            return "0"

        with mock.patch("builtins.input", fake_input):
            g.main()
        return len(chosen)


class ScriptedOneShotTests(GameTestCase):
    def test_wang_debtor_trouble_cannot_succeed_twice(self):
        g.state["player"]["flags"]["mentioned_wang_debt"] = True
        with mock.patch.object(g.random, "randint", return_value=1), mock.patch.object(
            g.requests, "post", side_effect=_ollama_post()
        ) as post:
            self.run_main_choosing("wang_debtor_trouble", times=2)
        self.assertTrue(g.state["player"]["flags"].get("helped_wang_debt"))
        # one success = +3; a second success would push this to 5 (clamped)
        self.assertEqual(g.state["npcs"]["npc_wang"]["affinity"], 3)
        self.assertEqual(g.state["npcs"]["npc_wang"]["option_counts"]["wang_debtor_trouble"], 1)

    def test_ayue_secret_money_cannot_grow_prowess_twice(self):
        with mock.patch.object(g.random, "randint", return_value=1), mock.patch.object(
            g.requests, "post", side_effect=_ollama_post()
        ):
            self.run_main_choosing("ayue_secret_money", times=2)
        self.assertTrue(g.state["player"]["flags"].get("offered_help_ayue"))
        self.assertEqual(g.state["player"]["prowess_growth_count"], 1)
        self.assertEqual(g.state["npcs"]["npc_ayue"]["affinity"], 1)

    def test_failed_attempt_can_be_retried(self):
        """Failure sets no flag, so the option must stay on the menu (existing design)."""
        g.state["player"]["flags"]["mentioned_wang_debt"] = True
        # randint=100 -> always above the 30/70 success rate -> failure
        with mock.patch.object(g.random, "randint", return_value=100), mock.patch.object(
            g.requests, "post", side_effect=_ollama_post()
        ):
            attempts = self.run_main_choosing("wang_debtor_trouble", times=2)
        self.assertEqual(attempts, 2)
        self.assertFalse(g.state["player"]["flags"].get("helped_wang_debt"))

    def test_completed_scripted_option_hidden_but_unlock_option_stays(self):
        g.state["player"]["flags"].update({"mentioned_wang_debt": True})
        ids = [o["id"] for o in g.get_visible_options(g.SCENES["tavern"]["options"])]
        self.assertIn("wang_debtor_trouble", ids)
        self.assertIn("ayue_secret_money", ids)
        g.state["player"]["flags"].update({"helped_wang_debt": True, "offered_help_ayue": True})
        ids = [o["id"] for o in g.get_visible_options(g.SCENES["tavern"]["options"])]
        self.assertNotIn("wang_debtor_trouble", ids)
        self.assertNotIn("ayue_secret_money", ids)
        self.assertIn("goto_ayue_home", ids)  # unlocked by offered_help_ayue, must not be affected


class HistoryOnFailureTests(GameTestCase):
    def test_call2_failure_leaves_history_untouched(self):
        with mock.patch.object(g.requests, "post", side_effect=_ollama_post(fail_call2=True)):
            with self.assertRaises(requests.exceptions.Timeout):
                g.call_llm("跟老王攀談", "npc_wang", 1)
        self.assertEqual(g.conversation_history["npc_wang"], [])

    def test_main_call2_failure_does_not_pollute_context(self):
        with mock.patch.object(g.requests, "post", side_effect=_ollama_post(fail_call2=True)):
            self.run_main_choosing("wang_business", times=1)
        self.assertEqual(g.conversation_history["npc_wang"], [])
        self.assertEqual(g.state["npcs"]["npc_wang"]["option_counts"], {})
        self.assertEqual(g.state["npcs"]["npc_wang"]["affinity"], 0)

    def test_successful_turn_is_recorded_once_as_user_and_assistant(self):
        with mock.patch.object(g.requests, "post", side_effect=_ollama_post(narrative="老王哼了一聲")):
            self.run_main_choosing("wang_business", times=1)
        history = g.conversation_history["npc_wang"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(json.loads(history[1]["content"])["narrative"], "老王哼了一聲")
        self.assertEqual(g.get_recent_narratives("npc_wang"), ["老王哼了一聲"])

    def test_failed_turn_then_retry_records_only_the_successful_one(self):
        posts = [_ollama_post(fail_call2=True), _ollama_post(narrative="第二次成功")]
        calls = {"n": 0}

        def post(url, json=None, **kwargs):
            # first full turn (2 posts) fails at Call2; afterwards everything succeeds
            calls["n"] += 1
            return posts[0 if calls["n"] <= 2 else 1](url, json=json, **kwargs)

        with mock.patch.object(g.requests, "post", side_effect=post):
            self.run_main_choosing("wang_business", times=2)
        history = g.conversation_history["npc_wang"]
        self.assertEqual(len(history), 2)
        self.assertEqual(json.loads(history[1]["content"])["narrative"], "第二次成功")

    def test_scripted_call1_failure_still_commits_the_fallback_narration_the_player_saw(self):
        """Round-3 semantics: the rolled outcome is authoritative, so a Call1 failure no longer aborts the turn;
        the player sees (and history records) the Python fallback narration instead."""
        g.state["player"]["flags"]["mentioned_wang_debt"] = True

        def boom(*a, **k):
            raise requests.exceptions.Timeout("call1 timeout")

        with mock.patch.object(g.random, "randint", return_value=1), mock.patch.object(
            g.requests, "post", side_effect=boom
        ):
            self.run_main_choosing("wang_debtor_trouble", times=1)
        hint = g.SCENES["tavern"]["options"][6]["outcome_above"]["hint"]
        history = g.conversation_history["npc_wang"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(json.loads(history[1]["content"])["narrative"], hint)
        self.assertTrue(g.state["player"]["flags"].get("helped_wang_debt"))


if __name__ == "__main__":
    unittest.main()
