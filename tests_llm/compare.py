"""Compare installed Ollama models on the RPG narrator contract without changing .env.

Run with: python -m tests_llm --compare
Without model arguments, discover every model installed in the local Ollama instance.
With explicit model arguments, test only those models and report any that are missing.
Before running, show the selected models and a rough time estimate.
"""
from __future__ import annotations

import json
import os
import re
import time

from rpg.narrator import Narrator

from . import harness, ollama_env, scenarios

def _installed_models(url: str) -> tuple[list[str], str | None]:
    """Read model names from the local Ollama tags API."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = sorted({
            item.get("name", "")
            for item in payload.get("models", [])
            if item.get("name")
        })
        return names, None
    except Exception as error:
        return [], f"{type(error).__name__}: {error}"


def _is_embedding_model(name: str) -> bool:
    """Embedding-only models cannot generate narrator prose."""
    short_name = name.rsplit("/", 1)[-1].split(":", 1)[0].casefold()
    return "embed" in short_name or short_name.startswith(("bge-", "bge_"))


QUICK_SCENARIOS = {"arrive_then_stay", "absent_mentioned", "private_persona", "time_0"}


def _save(rows: list[dict]) -> str:
    os.makedirs(harness.REPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(harness.REPORT_DIR, f"llm-compare-{stamp}.json")
    data = {"models": rows}
    for name in (f"llm-compare-{stamp}.json", "latest-compare.json"):
        with open(os.path.join(harness.REPORT_DIR, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def _duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"


def _previous_latencies() -> dict[str, float]:
    path = os.path.join(harness.REPORT_DIR, "latest-compare.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for row in data.get("models", []):
            summary = row.get("summary", {})
            mean = summary.get("latency", {}).get("mean")
            if mean and summary.get("model"):
                result[summary["model"]] = float(mean)
        return result
    except (OSError, ValueError, TypeError):
        return {}


def _first_run_seconds(model: str) -> float:
    """Rough fallback until this machine has a measured latency for this model."""
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[bB]", model)
    params = float(match.group(1)) if match else 8.0
    if params <= 2:
        return 3.0
    if params <= 4.5:
        return 5.0
    return 10.0


def _scenario_call_count(selected: list) -> int:
    # Replay the deterministic game without an LLM; this is cheap and counts
    # exactly how many narrator calls the selected scenarios will make.
    return sum(
        sum(1 for turn in harness.run_scenario(scenario, None)["turns"] if turn["kind"] == "llm")
        for scenario in selected
    )


def run(
    models: list[str] | None = None,
    only: list[str] | None = None,
    quick: bool = False,
) -> int:
    settings = ollama_env.settings()
    selected = [
        s for s in scenarios.SCENARIOS
        if (not quick or s.name in QUICK_SCENARIOS)
        and (not only or any(k in s.name for k in only))
    ]
    if not selected:
        print("沒有符合 --only 的情境。")
        return 2

    discovered, discovery_error = _installed_models(settings["url"])
    if discovery_error:
        print(f"無法探測本機 Ollama（{settings['url']}）：{discovery_error}")
        return 3

    if models:
        candidates = list(dict.fromkeys(models))
        installed, missing = [], []
        for model in candidates:
            ok, why = ollama_env.availability(settings["url"], model)
            (installed if ok else missing).append((model, why))
        mode = "指定模型"
    else:
        embedding_models = [model for model in discovered if _is_embedding_model(model)]
        candidates = [model for model in discovered if model not in embedding_models]
        installed = [(model, "已安裝") for model in candidates]
        missing = []
        mode = "自動探測"

    print(f"模型測試預覽（{mode}{'／快速情境' if quick else ''}）")
    print(
        f"Ollama 探測到 {len(discovered)} 個已安裝模型；"
        f"排除 {len(embedding_models) if not models else 0} 個嵌入模型；"
        f"本次將測 {len(installed)} 個。"
    )
    if not models and embedding_models:
        print("以下是嵌入模型，不適合生成旁白，已排除：")
        for model in embedding_models:
            print(f"  - {model}")
    if installed:
        print("本次會測：")
        for model, _ in installed:
            print(f"  ✓ {model}")
    if missing:
        print("指定模型中以下尚未下載：")
        for model, why in missing:
            print(f"  - {model}（ollama pull {model}）")

    if installed:
        calls_per_model = _scenario_call_count(selected)
        history = _previous_latencies()
        low = high = 0.0
        print(f"情境：{len(selected)} 個；每個模型約呼叫說書人 {calls_per_model} 次")
        print("各模型時間粗估：")
        for model, _ in installed:
            measured = history.get(model)
            per_call = measured if measured else _first_run_seconds(model)
            # Include model load/warm-up; show a range because machine load and
            # prompt prefill vary. The previous benchmark mean is more useful
            # than the parameter-size fallback when available.
            estimate = 10 + calls_per_model * per_call
            model_low = 10 + calls_per_model * per_call * 0.6
            model_high = 10 + calls_per_model * per_call * 1.8
            low += model_low
            high += model_high
            basis = "上次實測均值" if measured else "依模型大小粗估"
            print(f"  {model}: 約 {_duration(model_low)}–{_duration(model_high)}（{basis}）")
        print(f"合計約 {_duration(low)}–{_duration(high)}；不含下載時間。")
        try:
            answer = input("要開始比較嗎？[y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("已取消比較。")
            return 0
    else:
        print("Ollama 本機沒有可測的模型，無法開始比較。")
        for model, _ in missing:
            print(f"  下載：ollama pull {model}")
        return 3

    rows = []
    for model, _ in installed:
        print(f"\n開始測試 {model}（{len(selected)} 個情境）")
        narrator = Narrator(mode="ollama", url=settings["url"], model=model, timeout=settings["timeout"])
        results = []
        for scenario in selected:
            print(f"  {scenario.name} …", flush=True)
            results.append(harness.run_scenario(scenario, narrator))
        summary = harness.summarize(results, model=model)
        rows.append({"summary": summary, "results": results})
        print(harness.format_report(summary))

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
    return 0
