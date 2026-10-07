"""把情境逐回合跑過說書人，記下每一次呼叫，最後彙總成統計報告。

每個回合：
1. 用真正的遊戲動作推進世界，得到這回合的 beats。
2. 記下世界的 state hash → 呼叫說書人（同步，跟遊戲背景執行緒走同一條 `Narrator.narrate_ctx`）→ 再記一次 hash，必須相同。
3. 同一個情境另外跑一份「沒有說書人」的影子世界，每回合 hash 都要跟主世界一樣（說書人不可能影響世界走向）。
4. 用獨立的契約檢查器檢查「模型原始輸出」（統計模型多常越界）與「最後顯示給玩家的文字」（必須零越界）。
"""

from __future__ import annotations

import json
import os
import statistics
import time

from rpg.narrator import Narrator, REWRITE_KINDS

from . import contract, scenarios

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def run_scenario(sc: scenarios.Scenario, narrator: Narrator | None, narrated_turns: int | None = None) -> dict:
    """narrator=None 時只跑世界（用來驗證情境本身、或在沒有模型時檢查測試架構）。"""
    main = scenarios.iterate(sc)
    shadow = scenarios.iterate(sc)
    target = narrated_turns if narrated_turns is not None else (scenarios.long_turns() if sc.policy else None)
    turns, hash_mismatch, shadow_mismatch = [], 0, 0
    started = time.monotonic()
    for step, ((w, aid, beats), (sw, said, _)) in enumerate(zip(main, shadow)):
        if aid != said:
            shadow_mismatch += 1
        ctx = Narrator.build_context(w, beats)
        rew = [b for b in beats if b["kind"] in REWRITE_KINDS]
        t = {"step": step, "action": aid, "kind": "llm" if ctx else ("dialogue_only" if rew else "nothing"),
             "period": w.period, "weather": w.weather, "place": w.player["location"]}
        if ctx:
            t.update(template=ctx["template"], arrived=ctx["arrived"], on_stage=ctx["on_stage"], absent=ctx["absent"],
                     prompt="\n".join(Narrator.prompts(ctx)))
        if ctx and narrator:
            before = w.state_hash()
            fixed_before = narrator.stats.get("schema_key_fixed", 0)
            rec = narrator.narrate_ctx(ctx)
            if w.state_hash() != before:
                hash_mismatch += 1
            t.update(source=rec["source"], reason=rec["reason"], error=rec["error"], latency=rec["latency"],
                     raw=rec["raw"], shown=rec["text"],
                     schema_key_fixed=narrator.stats.get("schema_key_fixed", 0) > fixed_before,
                     raw_violations=contract.audit(rec["raw"], ctx, w) if rec["reason"] != "error" else ["error"],
                     shown_violations=contract.audit(rec["text"], ctx, w))
        elif rew:
            t["shown"] = "\n".join(b["text"] for b in rew)   # 不經模型，照原樣顯示
        if w.state_hash() != sw.state_hash():
            shadow_mismatch += 1
        turns.append(t)
        if target is not None and sum(1 for x in turns if x["kind"] == "llm") >= target:
            break
    return {"scenario": sc.name, "about": sc.about, "turns": turns, "hash_mismatch": hash_mismatch,
            "shadow_mismatch": shadow_mismatch, "seconds": round(time.monotonic() - started, 1)}


# ---------------------------------------------------------------- 統計
def _pct(a, b):
    return f"{a}/{b} ({(100 * a / b if b else 0):.0f}%)"


def summarize(results: list[dict], model: str = "") -> dict:
    calls = [t for r in results for t in r["turns"] if "source" in t]
    s = {
        "model": model,
        "scenarios": [r["scenario"] for r in results],
        "turns": sum(len(r["turns"]) for r in results),
        "dialogue_only_turns": sum(1 for r in results for t in r["turns"] if t["kind"] == "dialogue_only"),
        "llm_calls": len(calls),
        "accepted": sum(1 for t in calls if t["source"] == "llm"),
        "fallback": sum(1 for t in calls if t["source"] == "template" and t["reason"] != "error"),
        "errors": sum(1 for t in calls if t["reason"] == "error"),
        "schema_key_fixed": sum(1 for t in calls if t.get("schema_key_fixed")),
        "fallback_reasons": {},
        "raw_violations": {},
        "shown_violations": {},
        "rejected_but_clean": {},
        "hash_mismatch": sum(r["hash_mismatch"] for r in results),
        "shadow_mismatch": sum(r["shadow_mismatch"] for r in results),
    }
    for t in calls:
        if t["reason"]:
            s["fallback_reasons"][t["reason"]] = s["fallback_reasons"].get(t["reason"], 0) + 1
        for v in t["raw_violations"]:
            s["raw_violations"][v] = s["raw_violations"].get(v, 0) + 1
        for v in t["shown_violations"]:
            s["shown_violations"][v] = s["shown_violations"].get(v, 0) + 1
        if t["source"] == "template" and t["reason"] not in (None, "error") and not t["raw_violations"]:
            # 驗證器擋了，但獨立檢查器沒看到越界：可能是驗證器太嚴（調退回率時先看這裡）
            s["rejected_but_clean"][t["reason"]] = s["rejected_but_clean"].get(t["reason"], 0) + 1
    non_arrival = [t for t in calls if not t["arrived"]]
    s["scene_reintro_raw"] = [sum(1 for t in non_arrival if "scene_reintro" in t["raw_violations"]), len(non_arrival)]
    lat = [t["latency"] for t in calls if t.get("latency") is not None]
    s["latency"] = {"mean": round(statistics.mean(lat), 1), "p50": round(statistics.median(lat), 1),
                    "p95": round(sorted(lat)[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0], 1),
                    "max": round(max(lat), 1)} if lat else {}
    long_run = next((r for r in results if r["scenario"] == "long_play"), None)
    if long_run:
        lc = [t for t in long_run["turns"] if "source" in t]
        half = len(lc) // 2
        fb = lambda xs: sum(1 for t in xs if t["source"] != "llm") / len(xs) if xs else 0  # noqa: E731
        s["long_play_fallback_halves"] = [round(fb(lc[:half]), 2), round(fb(lc[half:]), 2)]
        s["long_play_calls"] = len(lc)
    return s


def format_report(s: dict) -> str:
    calls = s["llm_calls"]
    lines = [
        "=" * 64,
        "說書人真模型整合測試報告",
        "=" * 64,
        f"Model:               {s['model']}",
        f"Scenarios:           {len(s['scenarios'])}  ({', '.join(s['scenarios'])})",
        f"Turns (game actions):{s['turns']:>5}",
        f"  dialogue-only:     {s['dialogue_only_turns']:>5}   (shown as written, model not called)",
        f"LLM calls:           {calls:>5}",
        f"  accepted:          {_pct(s['accepted'], calls)}",
        f"  fallback:          {_pct(s['fallback'], calls)}",
        f"  errors/timeouts:   {_pct(s['errors'], calls)}",
        f"  misnamed JSON key: {s['schema_key_fixed']} (accepted as the single text field)",
        "Fallback reasons (validator):",
    ]
    for k, v in sorted(s["fallback_reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:<20}{v}")
    lines.append("Model raw output broke the contract (independent checker; validator should catch these):")
    for k in contract.CATEGORIES:
        if s["raw_violations"].get(k):
            lines.append(f"  {k:<20}{_pct(s['raw_violations'][k], calls)}")
    lines.append(f"Reached the player (must be 0): {sum(s['shown_violations'].values())} {s['shown_violations'] or ''}")
    lines.append(f"Rejected though the checker saw nothing (validator possibly too strict): {s['rejected_but_clean'] or 0}")
    a, b = s["scene_reintro_raw"]
    lines.append(f"Scene re-introduced on non-arrival turns (raw): {_pct(a, b)}")
    if "long_play_fallback_halves" in s:
        h1, h2 = s["long_play_fallback_halves"]
        lines.append(f"Long play: {s['long_play_calls']} calls, fallback first half {h1:.0%} → second half {h2:.0%}")
    if s["latency"]:
        lt = s["latency"]
        lines.append(f"Latency (s): mean {lt['mean']}  p50 {lt['p50']}  p95 {lt['p95']}  max {lt['max']}")
    lines.append(f"World state changed by narration: {s['hash_mismatch']}   diverged from no-narrator shadow world: {s['shadow_mismatch']}")
    lines.append("=" * 64)
    return "\n".join(lines)


def save(results: list[dict], summary: dict) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    data = {"summary": summary, "results": results}
    for name in (f"llm-{stamp}.json", "latest.json"):
        with open(os.path.join(REPORT_DIR, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    with open(os.path.join(REPORT_DIR, "latest.txt"), "w", encoding="utf-8") as f:
        f.write(format_report(summary) + "\n")
    return os.path.join(REPORT_DIR, f"llm-{stamp}.json")
