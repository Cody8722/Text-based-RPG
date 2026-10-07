"""世界基因池：開局時隨機抽幾個「隱藏設定」，改寫 NPC 的狀態、債務、人際與秘密。

依《終極願景》第 3 節：候選詞要「意外、具體、有延伸性」——每個基因都會落到機制上
（債務、旗標、人際數值、事實），不是只寫在描述裡的空話。
每個世界抽到的組合不同，所以同一個小鎮每次開局都是不同的人際網絡。

基因的內容是開發者資料，絕不送到前端；玩家只能透過遊戲裡的見聞慢慢拼出來。
"""

from __future__ import annotations


def _pick(w, ids):
    ids = [i for i in ids if i in w.npcs and w.npcs[i]["status"] == "normal"]
    return w.rng.choice(ids) if ids else None


def g_secret_patron(w):
    cands = [("wang", 5), ("bai", 3), ("su", 2), ("sun", 2), ("chenbo", 1)]
    patron = w.pick_weighted(cands)
    w.npcs[patron]["patron_of"] = "linshen"
    known = [patron] + (["bai"] if patron != "bai" else [])
    w.add_fact("secret_support", {"patron": patron, "beneficiary": "linshen"}, place="pharmacy",
               secrecy="secret", importance=4, known_by=known, log=False)
    return {"patron": patron}


def g_gambling_debt(w):
    b = _pick(w, ["zhou", "liu6", "shitou", "xiaoli", "chenbo", "aniu"])
    if not b or w.open_loans(borrower=b, lender="qian"):
        return None
    amt = w.rng.randint(6, 16) * 10
    w.npcs[b]["traits"]["vice"] = min(10, w.npcs[b]["traits"]["vice"] + 2)
    fid = w.add_fact("loan", {"lender": "qian", "borrower": b}, place="den",
                     data={"amount": amt, "due": w.day + w.rng.randint(2, 6)}, secrecy="private",
                     importance=3, known_by=[b, "qian", "liu6"], log=False)
    w.add_loan("qian", b, amt, w.facts[fid]["data"]["due"] - w.day, 0, fact_id=fid)
    return {"borrower": b, "amount": amt}


GRUDGES = [
    ("tie", "qian", "錢三爺當年設局，讓鐵師傅的師弟在賭桌上輸掉了一條胳膊"),
    ("wang", "feng", "馮員外三年前想低價收走老王的酒館，被老王當眾潑了一盆洗碗水"),
    ("zhou", "zhao", "趙捕頭曾經當著半條街的面把周秀才當賊搜身，最後什麼也沒搜到"),
    ("su", "feng", "蘇娘子的丈夫是替馮家修屋頂時摔死的，馮家只賠了三兩銀子"),
    ("aniu", "liu6", "劉六去年為了一筆帳把小虎推進河裡，是阿牛跳下去撈上來的"),
    ("shitou", "xiaoli", "小李收了好處，把一場賭坊門口的鬥毆全推到石頭頭上，害他在拘房蹲了三天"),
    ("chenbo", "sun", "陳伯的女兒當年跟一個住在孫記客棧的外地人私奔，陳伯一直認定是孫掌櫃牽的線"),
    ("laohe", "wu", "吳伯曾經在鎮口扣下老何的一船貨，老何賠掉了半年的收入"),
    ("banxian", "bai", "劉半仙替人算命說「此病無藥可醫」，害白大夫的一個病人放棄吃藥，兩人從此結仇"),
]


def g_old_grudge(w):
    used = {tuple(sorted((g["a"], g["b"]))) for g in w.genes if g.get("gene") == "old_grudge" and g.get("a")}
    opts = [g for g in GRUDGES if tuple(sorted(g[:2])) not in used]
    a, b, reason = w.rng.choice(opts)
    for x, y in ((a, b), (b, a)):
        w.npcs[x]["opinions"][y] = -w.rng.randint(55, 75)
    gossip = _pick(w, ["chenbo", "zhang", "banxian", "su"])
    w.add_fact("grudge", {"a": a, "b": b}, data={"reason": reason}, secrecy="private", importance=2,
               known_by=[a, b] + ([gossip] if gossip else []), log=False)
    return {"a": a, "b": b}


def g_sticky_fingers(w):
    t = _pick(w, ["xiaohu", "zhou", "xiaoli", "liu6", "laohe", "banxian"])
    tr = w.npcs[t]["traits"]
    tr["honesty"] = 1
    tr["greed"] = min(10, tr["greed"] + 2)
    w.add_fact("petty_theft_past", {"who": t}, secrecy="secret", importance=2, known_by=["zhang"], log=False)
    return {"who": t}


def g_hidden_savings(w):
    h = _pick(w, ["zhang", "banxian", "linshen", "wu"])
    w.npcs[h]["money"] += w.rng.randint(12, 22) * 10
    w.npcs[h]["hoarder"] = True
    w.add_fact("hidden_savings", {"who": h}, secrecy="secret", importance=2, known_by=[h], log=False)
    return {"who": h}


def g_guarantor(w):
    b = _pick(w, ["zhou", "liu6", "aniu", "shitou"])
    if not b or w.open_loans(borrower=b, lender="qian"):
        return None
    amt = w.rng.randint(8, 15) * 10
    due = w.day + w.rng.randint(4, 8)
    fid = w.add_fact("loan", {"lender": "qian", "borrower": b, "guarantor": "wang"}, place="den",
                     data={"amount": amt, "due": due}, secrecy="private", importance=3,
                     known_by=[b, "qian", "liu6", "wang"], log=False)
    w.add_loan("qian", b, amt, due - w.day, 0, guarantor="wang", fact_id=fid)
    return {"borrower": b, "amount": amt}


LOVES = [("sun", "su"), ("zhou", "su"), ("aniu", "ayue"), ("xiaoli", "ayue"), ("laohe", "su"), ("hu", "su")]


def g_secret_love(w):
    lover, beloved = w.rng.choice(LOVES)
    w.npcs[lover]["opinions"][beloved] = max(w.npcs[lover]["opinions"].get(beloved, 0), 75)
    w.npcs[lover]["admires"] = beloved
    known = [lover] + (["sun"] if lover != "sun" else [])
    w.add_fact("secret_love", {"lover": lover, "beloved": beloved}, secrecy="secret", importance=2,
               known_by=known, log=False)
    if beloved == "ayue" and lover != "shitou":
        w.npcs["shitou"]["rival"] = lover
    return {"lover": lover, "beloved": beloved}


def g_smuggling(w):
    w.npcs["laohe"]["smuggler"] = True
    w.npcs["laohe"]["money"] += 60
    w.add_fact("smuggling", {"boatman": "laohe", "boss": "qian"}, place="dock", secrecy="secret",
               importance=4, known_by=["laohe", "qian", "zhang"], log=False)
    return {}


def g_medicine_shortage(w):
    w.medicine_stock = w.rng.choice([0, 1])
    w.trader_next_day = w.rng.randint(5, 7)
    return {"stock": w.medicine_stock}


def g_tavern_mortgage(w):
    if w.open_loans(borrower="wang", lender="qian"):
        return None
    amt = w.rng.randint(24, 34) * 10
    due = w.day + w.rng.randint(4, 7)
    fid = w.add_fact("loan", {"lender": "qian", "borrower": "wang"}, place="den",
                     data={"amount": amt, "due": due, "secured": "老王酒館"}, secrecy="private",
                     importance=4, known_by=["wang", "qian", "liu6"], log=False)
    w.add_loan("qian", "wang", amt, due - w.day, 0, secured="tavern", fact_id=fid)
    return {"amount": amt}


def g_ayue_debt(w):
    amt = w.rng.randint(4, 7) * 10
    due = w.day + w.rng.randint(3, 6)
    fid = w.add_fact("loan", {"lender": "qian", "borrower": "ayue"}, place="den",
                     data={"amount": amt, "due": due}, secrecy="secret", importance=3,
                     known_by=["ayue", "qian", "liu6"], log=False)
    w.add_loan("qian", "ayue", amt, due - w.day, 0, fact_id=fid)
    return {"amount": amt}


def g_rent_hike(w):
    for t in ("chenbo", "su", "tie", "bai"):
        w.npcs[t]["rent"] += 10
    w.add_fact("news", {}, data={"text": "馮員外貼出告示，下個月起市集和長街的鋪租一律加十文"},
               secrecy="public", importance=2, known_by=["feng", "chenbo", "su", "tie", "bai", "wu"], log=False)
    return {}


def g_lazy_guard(w):
    w.npcs["zhao"]["traits"]["vice"] = 7
    w.npcs["zhao"]["schedule"][4] = "den"
    w.npcs["zhao"]["lazy"] = True
    w.add_fact("guard_gambles", {"who": "zhao"}, place="den", secrecy="private", importance=2,
               known_by=["xiaoli", "qian"], log=False)
    return {}


GENE_POOL = [
    ("secret_patron", g_secret_patron, 6),
    ("gambling_debt", g_gambling_debt, 6),
    ("old_grudge", g_old_grudge, 7),
    ("old_grudge", g_old_grudge, 4),
    ("sticky_fingers", g_sticky_fingers, 5),
    ("hidden_savings", g_hidden_savings, 3),
    ("guarantor", g_guarantor, 4),
    ("secret_love", g_secret_love, 4),
    ("smuggling", g_smuggling, 3),
    ("medicine_shortage", g_medicine_shortage, 3),
    ("tavern_mortgage", g_tavern_mortgage, 5),
    ("ayue_debt", g_ayue_debt, 4),
    ("rent_hike", g_rent_hike, 2),
    ("lazy_guard", g_lazy_guard, 2),
]


def apply_genes(w, count: int | None = None):
    pool = list(GENE_POOL)
    n = count if count is not None else w.rng.randint(5, 8)
    while pool and len(w.genes) < n:
        idx = w.pick_weighted([(i, wt) for i, (_, _, wt) in enumerate(pool)])
        name, fn, _ = pool.pop(idx)
        info = fn(w)
        if info is not None:
            w.genes.append({"gene": name, **info})
