"""Compare installed Ollama models on the RPG narrator contract without changing .env.

Run with: python -m tests_llm --compare
Only installed models are tested; missing models are listed with pull commands.
This evaluates narration only, using the same deterministic scenarios and validator
as the regular model integration tests.
"""
from __future__ import annotations

import json
import os
import time

from rpg.narrator import Narrator

from . import harness, ollama_env, scenarios

DEFAULT_MODELS = (
    "qwen3.5:9b",
    "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q4_K_M",
    "maternion/mimo-v2.6:9b-instruct",
    "wangshenzhi/gemma2-9b-chinese-chat",
    "fauxpaslife/Astrea-R8-Chat-9B",
)


def _save(rows: list[dict]) -> str:
    os.makedirs(harness.REPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(harness.REPORT_DIR, f"llm-compare-{stamp}.json")
    data = {"models": rows}
    for name in (f"llm-compare-{stamp}.json", "latest-compare.json"):
        with open(os.path.join(harness.REPORT_DIR, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def run(models: list[str] | None = None, only: list[str] | None = None) -> int:
    settings = ollama_env.settings()
    candidates = list(dict.fromkeys(models or DEFAULT_MODELS))
    selected = [s for s in scenarios.SCENARIOS if not only or any(k in s.name for k in only)]
    if not selected:
        print("沒有符合 --only 的情境。")
        return 2

    rows = []
    for model in candidates:
        ok, why = ollama_env.availability(settings["url"], model)
        if not ok:
            print(f"略過 {model}：尚未下載。請執行：ollama pull {model}")
            continue
        print(f"\n開始測試 {model}（{len(selected)} 個情境）")
        narrator = Narrator(mode="ollama", url=settings["url"], model=model, timeout=settings["timeout"])
        results = []
        for scenario in selected:
            print(f"  {scenario.name} …", flush=True)
            results.append(harness.run_scenario(scenario, narrator))
        summary = harness.summarize(results, model=model)
        rows.append({"summary": summary, "results": results})
        print(harness.format_report(summary))

    if not rows:
        print("\n沒有已安裝的候選模型可測。先下載至少一個模型，再重跑。")
        return 3

    ordered = sorted(rows, key=lambda row: (
        row["summary"]["accepted"] / max(1, row["summary"]["llm_calls"]),
        -row["summary"]["latency"].get("mean", float("inf")),
    ), reverse=True)
    print("\n比較摘要（接受率越高，代表越常通過遊戲的說書契約）：")
    print(f"{'模型':<58} {'接受率':>9} {'錯誤':>8} {'平均秒數':>10}")
    for row in ordered:
        s = row["summary"]
        rate = 100 * s["accepted"] / max(1, s["llm_calls"])
        print(f"{s['model']:<58} {rate:>7.1f}% {s['errors']:>8} {s['latency'].get('mean', 0):>10.1f}")
    path = _save(rows)
    print(f"\n完整比較報告已存到：{path}")
    if len(rows) < len(candidates):
        print("只測了已安裝的模型；上面的略過項目下載後可直接重跑比較。")
    return 0
