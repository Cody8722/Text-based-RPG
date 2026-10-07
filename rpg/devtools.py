"""開發者工具：世界編年史、因果鏈、統計。會劇透，玩家介面絕不呼叫這些。"""

from __future__ import annotations

from .content import text as T
from .content.locations import PERIODS


def chronicle(w, since_day: int = 1, types: set | None = None) -> list[str]:
    out = []
    for fid in w.event_log:
        f = w.facts[fid]
        if f["day"] < since_day or (types and f["type"] not in types):
            continue
        cause = f" ⟵ {','.join(f['causes'])}" if f["causes"] else ""
        out.append(f"D{f['day']:>3} {PERIODS[f['period']]} [{fid}] {T.fact_text(w, f)}{cause}")
    return out


def chain_depth(w, fid: str, memo: dict | None = None, stack: frozenset = frozenset()) -> int:
    memo = {} if memo is None else memo
    if fid in memo:
        return memo[fid]
    f = w.facts.get(fid)
    if not f or fid in stack:
        return 0
    d = 1 + max((chain_depth(w, c, memo, stack | {fid}) for c in f["causes"]), default=0)
    memo[fid] = d
    return d


def longest_chains(w, k: int = 5) -> list[list[str]]:
    memo: dict = {}
    ranked = sorted(w.event_log, key=lambda f: chain_depth(w, f, memo), reverse=True)
    chains, used = [], set()
    for fid in ranked:
        if fid in used:
            continue
        chain = [fid]
        cur = fid
        while w.facts[cur]["causes"]:
            cur = max(w.facts[cur]["causes"], key=lambda c: chain_depth(w, c, memo))
            chain.append(cur)
        chain.reverse()
        used.update(chain)
        chains.append(chain)
        if len(chains) >= k:
            break
    return chains


def summarize(w) -> dict:
    alive = [n for n in w.npcs.values() if n["status"] in ("normal", "jailed")]
    return {
        "day": w.day,
        "genes": [g["gene"] for g in w.genes],
        "alive": len(alive),
        "dead": [n["call"] for n in w.npcs.values() if n["status"] == "dead"],
        "fled": [n["call"] for n in w.npcs.values() if n["status"] == "fled"],
        "jailed": [n["call"] for n in w.npcs.values() if n["status"] == "jailed"],
        "owners": {p["name"]: w.name(p["owner"]) for p in w.properties.values() if p.get("orig_owner")},
        "max_chain": max((chain_depth(w, f) for f in w.event_log), default=0),
        "mischief": len(w.mischief_log),
    }
