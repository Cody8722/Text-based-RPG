"""python -m tests_llm [--long-turns N] [--only 名稱 …] [--require]

真模型整合測試的入口（跟 `python -m unittest discover -s tests` 的快速測試分開）。
- 連不上 Ollama／沒有模型：印出 LLM UNAVAILABLE 與原因，結束碼 0（環境問題不算失敗）；加 --require 則結束碼 3。
- 跑完會印統計報告，完整逐回合紀錄寫到 tests_llm/reports/。
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests_llm")
    ap.add_argument("--long-turns", type=int, help="長時間遊玩要跑幾個說書回合（預設 60，環境變數 RPG_LLM_LONG_TURNS）")
    ap.add_argument("--only", nargs="*", help="只跑名稱含這些字的測試，例如 --only time absent")
    ap.add_argument("--require", action="store_true", help="Ollama 不可用時當成失敗（結束碼 3）")
    ap.add_argument("--rescore", metavar="REPORT.json", help="不呼叫模型：用現在的驗證器重新判定一份已記錄的執行結果")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if a.long_turns is not None:
        os.environ["RPG_LLM_LONG_TURNS"] = str(a.long_turns)

    if a.rescore:
        import json

        from . import harness

        with open(a.rescore, encoding="utf-8") as f:
            old = json.load(f)
        results = harness.rescore(old["results"])
        print(harness.format_report(harness.summarize(results, model=old["summary"].get("model", "") + "（rescored）")))
        return 0

    from . import ollama_env

    ok, why = ollama_env.availability()
    if not ok:
        print(f"LLM UNAVAILABLE — {why}\nAll real-model tests skipped (this is an environment condition, not a game failure).")
        return 3 if a.require else 0

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_llm.llm_narrator_e2e")
    if a.only:
        def keep(t):
            return any(k in t.id() for k in a.only)

        def flatten(s):
            for x in s:
                if isinstance(x, unittest.TestSuite):
                    yield from flatten(x)
                else:
                    yield x
        suite = unittest.TestSuite([t for t in flatten(suite) if keep(t)])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
