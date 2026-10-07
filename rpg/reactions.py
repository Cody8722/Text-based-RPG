"""得知一條事實之後的白盒反應。

這是「傳聞會改變世界」的關鍵：NPC 不管聽到的是真相還是走樣的傳聞，都會依自己相信的版本調整好感、
記恨、決定要不要報官。捕頭辦案也只能依據他聽到的東西——所以假消息真的能讓無辜的人被抓。
"""

from __future__ import annotations

HARM_TYPES = {"theft", "caught_stealing", "debt_beating", "fight", "accusation", "death"}


def _victim_of(f):
    r = f["roles"]
    for k in ("victim", "debtor"):
        if k in r:
            return r[k]
    return None


def _cares(w, who, target):
    if who == target:
        return 100
    if who == "player" or target is None:
        return 0
    if target in w.family_of(who):
        return 90
    return max(0, w.opinion(who, target))


def on_learn(w, who: str, fid: str, src: str):
    f = w.facts[fid]
    t, r = f["type"], f["roles"]
    if who == "player":
        return
    n = w.npcs[who]

    culprit = w.culprit_of(f)
    victim = _victim_of(f)
    if t == "accusation":
        culprit, victim = r.get("accused"), r.get("victim")

    if culprit and t in HARM_TYPES and culprit != who:
        care = _cares(w, who, victim)
        hit = 6 + care // 4
        if t == "accusation":
            # 指控的可信度取決於聽的人信不信得過指控的人
            trust = w.opinion(who, r.get("accuser")) if r.get("accuser") not in (None, "player") else 10
            hit = hit // 2 if trust < 20 else hit
        w.adjust_opinion(who, culprit, -hit)
        if care >= 60:
            add = 70 if t == "death" else 45 if victim == who else 30
            n["blame"][culprit] = min(200, n["blame"].get(culprit, 0) + add)
            n.setdefault("blame_src", {})[culprit] = fid
            if victim == who:
                w.stress(who, 12)

    if t == "debt_paid_by":
        if r.get("debtor") == who:
            w.adjust_opinion(who, r.get("payer"), 45)
            w.stress(who, -35)
        else:
            w.adjust_opinion(who, r.get("payer"), 6)
    elif t in ("help_money", "medicine"):
        if r.get("receiver") == who or r.get("receiver") in w.family_of(who):
            w.adjust_opinion(who, r.get("giver"), 25)
        else:
            w.adjust_opinion(who, r.get("giver"), 4)
    elif t == "secret_support":
        ben = r.get("beneficiary")
        if who == ben or ben in w.family_of(who):
            w.adjust_opinion(who, r.get("patron"), 40)
    elif t in ("rescue", "persuade"):
        if r.get("target") == who:
            w.adjust_opinion(who, r.get("helper"), 35)
        else:
            w.adjust_opinion(who, r.get("helper"), 5)
            w.adjust_opinion(who, r.get("attacker"), -3)
    elif t == "arrest":
        s = r.get("suspect")
        if s in w.family_of(who) or w.opinion(who, s) >= 50:
            w.adjust_opinion(who, r.get("guard"), -20)
            w.stress(who, 15)
        elif s != who:
            w.adjust_opinion(who, s, -6)
    elif t == "death":
        dead = r.get("who")
        if dead in w.family_of(who):
            w.stress(who, 60)
            n["grief_until"] = w.day + 7
        elif w.opinion(who, dead) >= 40:
            w.stress(who, 20)
    elif t == "smuggling" and who == "zhao":
        _open_case(w, "smuggling", fid, victim=None, place=f["place"], suspect_hint=r.get("boatman"))
    elif t == "guard_gambles":
        w.adjust_opinion(who, r.get("who"), -8)
    elif t == "secret_love" and r.get("beloved") == "ayue" and who == "shitou" and r.get("lover") != "shitou":
        w.adjust_opinion(who, r.get("lover"), -30)
    elif t == "fled":
        for ln in w.loans.values():
            if ln["borrower"] == r.get("who") and ln["lender"] == who:
                w.adjust_opinion(who, r.get("who"), -40)

    # 聽信了指控、又本來就看被指控的人不順眼：會想去跟捕頭說
    if t == "accusation" and r.get("accused") not in (None, who) and who != "zhao":
        if w.opinion(who, r["accused"]) <= -30 or r.get("victim") == who:
            n.setdefault("to_report", [])
            if fid not in n["to_report"]:
                n["to_report"].append(fid)

    # 自己是被害人或旁觀者：要不要去報官，交給 behaviors 的 report 行為（依老實/恩怨/膽量擲骰）
    if t in ("theft", "caught_stealing", "debt_beating", "fight") and culprit and culprit != who and \
            (src == "witness" or who == victim or _cares(w, who, victim) >= 80):
        n.setdefault("to_report", [])
        if fid not in n["to_report"]:
            n["to_report"].append(fid)

    # 捕頭聽到跟犯罪有關的事，掛到案件上（案件只看他「知道」什麼）
    if who == "zhao" and t in ("theft", "theft_report", "caught_stealing", "debt_beating", "fight", "accusation", "clue"):
        root = w.root_fact(fid)
        crime_id = f["data"].get("crime") or root["id"]
        if crime_id in w.facts:
            ctype = w.facts[crime_id]["type"]
            if ctype in ("theft", "theft_report", "caught_stealing", "debt_beating", "fight"):
                _open_case(w, ctype, crime_id, victim=victim, place=f["place"])


def _open_case(w, ctype, crime_id, victim=None, place=None, suspect_hint=None):
    for c in w.cases.values():
        if c["crime"] == crime_id:
            return c["id"]
    w.case_seq += 1
    cid = f"C{w.case_seq}"
    crime = w.facts[crime_id]
    true_culprit = w.culprit_of(crime) if crime["truth"] else None
    if crime["type"] == "theft_report":
        true_culprit = crime["data"].get("thief")
    w.cases[cid] = {
        "id": cid,
        "type": ctype,
        "crime": crime_id,
        "victim": victim or crime["roles"].get("victim"),
        "place": place or crime["place"],
        "opened_day": w.day,
        "status": "open",
        "true_culprit": true_culprit or suspect_hint,
        "arrested": None,
    }
    return cid


def suspicion(w, case: dict) -> dict[str, int]:
    """捕頭對一個案件的懷疑分數：只根據他知道的事實（包括走樣的傳聞與不實指控）。"""
    scores: dict[str, int] = {}
    zhao = w.npcs.get("zhao")
    if not zhao:
        return scores
    crime_id = case["crime"]
    for fid, info in zhao["knows"].items():
        f = w.facts.get(fid)
        if not f:
            continue
        related = w.root_fact(fid)["id"] == crime_id or f["data"].get("crime") == crime_id
        if case["type"] == "smuggling" and f["type"] == "smuggling":
            related = True
        if not related:
            continue
        culprit = w.culprit_of(f)
        if f["type"] == "smuggling":
            culprit = f["roles"].get("boatman")
        if not culprit or culprit == case.get("victim"):
            continue
        src = info["src"]
        if src == "witness":
            pts = 70
        elif f["type"] == "accusation":
            accuser = f["roles"].get("accuser")
            trust = w.opinion("zhao", accuser) if accuser != "player" else w.opinion("zhao", "player")
            if f["data"].get("speculation"):
                pts = 19 + max(-10, min(15, trust // 3))   # 街坊閒話，捕頭只信三分
            else:
                pts = 30 + max(-20, min(30, trust // 2))
        elif f["type"] == "clue":
            pts = 35
        else:
            # 轉述：講的人自己有沒有親眼看到，可信度不同
            teller = w.npcs.get(src)
            saw = teller and fid in teller["knows"] and teller["knows"][fid]["src"] in ("witness", "self")
            pts = 55 if saw else 30
            pts += w.opinion("zhao", src) // 5 if src in w.npcs else 0
        scores[culprit] = scores.get(culprit, 0) + pts
    for s in list(scores):
        scores[s] += max(0, -w.opinion("zhao", s)) // 4
    return scores
