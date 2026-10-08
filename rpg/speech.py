"""說話層：把「事實」變成「人說出口的話」，並記得誰已經聽過、說過什麼。

為什麼需要這一層：事實（world.facts）是給規則用的紀錄體，一條一件事。直接把它塞進引號當台詞，
會變成每個人都用同一句紀錄腔講同一件事，同一個人被抓到三次就要被播報三次。這裡做三件事：

1. 故事（story）：同一個人的同一類事歸成一個故事——某人這幾天手腳不乾淨被抓到好幾回、
   之後被抓進巡檢所；同一個人的債被一路催討；同一個人的病。傳話、清晨的街談、告示、見聞錄、
   NPC 提起你做過的事，都以「故事」為單位，不再一條事實播一次。
2. 口語：同一件事，講的人是當事人、旁觀者還是聽說的，對當事人有好感還是看不順眼，
   性子是心軟、火爆還是嘴碎，講法都不同；還會帶上「什麼時候」「從哪聽來」。
3. 記性：每個 NPC 對玩家說過的句子會記住，短期內不重複；可有可無的句子用完了就不說。

這裡只做「文字選擇」，不改任何數值、不決定任何結果——好感、金錢、誰知道什麼，仍由呼叫端的白盒規則處理。
跨 NPC 共用的句子不寫死代名詞（CLAUDE.md 的規則），一律用名字或省略主詞。
"""

from __future__ import annotations

import random
from string import Formatter

from .content import text as T

# ---------------------------------------------------------------- 記性
LINE_MEMORY = 14


def text_rng(w, owner: str) -> random.Random:
    """文字專用的亂數：由世界種子、時間、說話的人、第幾句話決定。
    挑哪個句子不消耗 world.rng——措辭怎麼變，世界的走向都完全一樣；同一個存檔讀回來，挑到的句子也一樣。"""
    n = w.player.get("said_n", 0) + 1
    w.player["said_n"] = n
    return random.Random(f"{w.seed}:{w.clock}:{owner}:{n}")


def chance(w, owner: str, pct: float) -> bool:
    return text_rng(w, owner).random() * 100 < pct


# 只是「顯示」用的措辭（選項標籤、見聞錄）：不能改變任何狀態——看一眼畫面不該讓世界不一樣
PURE_OWNERS = {"_label", "_journal"}


def pick(w, owner: str, pool: list[str], optional: bool = False, keep: int = LINE_MEMORY) -> str | None:
    """從 pool 挑一句 owner 最近沒說過的。optional=True 時全都說過就回傳 None（寧可不說，也不重複）。"""
    if not pool:
        return None
    if owner in PURE_OWNERS:
        return pool[0]
    mem = w.player.setdefault("said", {}).setdefault(owner, [])
    fresh = [x for x in pool if x not in mem]
    if not fresh:
        if optional:
            return None
        fresh = [x for x in pool if not mem or x != mem[-1]] or list(pool)
        # 全說過了：挑最久以前說的那幾句
        order = {x: i for i, x in enumerate(mem)}
        fresh.sort(key=lambda x: order.get(x, -1))
        fresh = fresh[:max(1, len(fresh) // 2)]
    line = text_rng(w, owner).choice(fresh)
    if line in mem:
        mem.remove(line)
    mem.append(line)
    del mem[:-keep]
    return line


def cn(k: int) -> str:
    return "一兩三四五六七八九十"[k - 1] if 1 <= k <= 10 else "好多"


def when(w, day: int) -> str:
    d = w.day - day
    if d <= 0:
        return "今天"
    if d == 1:
        return "昨天"
    if d == 2:
        return "前天"
    if d <= 6:
        return "前幾天"
    return "前陣子"


def namer(w, speaker: str | None, listener: str = "player"):
    def n(ref):
        if not ref:
            return "某人"
        if speaker and ref == speaker:
            return "我"
        if ref == "player":
            return "你" if listener == "player" else "那個外地人"
        return w.name(ref)

    return n


# ---------------------------------------------------------------- 故事
def story_key(f: dict) -> str:
    """把一條事實歸到它所屬的故事。只看事實自己的角色——走樣的傳聞換了主角，就是另一個故事（聽的人也這麼以為）。"""
    t, r = f["type"], f["roles"]
    if t in ("theft", "caught_stealing"):
        return f"crime:{r.get('thief')}"
    if t == "accusation":
        return f"crime:{r.get('accused')}"
    if t == "arrest":
        return f"crime:{r.get('suspect')}"
    if t == "release":
        return f"crime:{r.get('who')}"
    if t == "bribe":
        return f"crime:{r.get('prisoner')}"
    if t == "theft_report":
        return f"loss:{r.get('victim')}:{f['data'].get('crime')}"
    if t in ("debt_warning", "debt_threat", "property_seized", "debt_transferred"):
        return f"debt:{r.get('debtor')}"
    if t == "debt_beating":
        return f"debt:{r.get('victim')}"
    if t in ("loan", "loan_repaid", "debt_forgiven"):
        return f"debt:{r.get('borrower')}"
    if t == "debt_paid_by":
        return f"debt:{r.get('debtor')}"
    if t == "fight":
        return "fight:" + ":".join(sorted([str(r.get("attacker")), str(r.get("victim"))]))
    if t == "revenge_vow":
        return "fight:" + ":".join(sorted([str(r.get("who")), str(r.get("target"))]))
    if t in ("ill", "worse", "recovered", "death", "grieving"):
        return f"health:{r.get('who')}"
    if t == "act":
        return f"act:{r.get('target') or f['data'].get('thing') or f['id']}"
    if t in ("gamble_loss", "gamble_win"):
        return f"gamble:{r.get('who')}"
    if t in ("rent_unpaid", "evicted"):
        return f"rent:{r.get('tenant')}"
    if t in ("quit_job", "fired", "hired", "wages_unpaid"):
        return f"job:{r.get('who')}"
    return f"fact:{f['id']}"


def story_subject(key: str) -> str | None:
    fam, _, rest = key.partition(":")
    if fam in ("crime", "debt", "health", "gamble", "rent", "job"):
        return rest
    if fam == "loss":
        return rest.split(":")[0]
    return None


def story_facts(w, who: str, key: str) -> list[dict]:
    """who（玩家或某個 NPC）知道的、屬於這個故事的事實，依時間排序。"""
    e = w.ent(who)
    out = [w.facts[f] for f in e["knows"] if f in w.facts and story_key(w.facts[f]) == key]
    out.sort(key=lambda f: (f["day"], f["id"]))
    return out


def stories_of(w, who: str, skip_types=("player_work",)) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for fid in w.ent(who)["knows"]:
        f = w.facts.get(fid)
        if not f or f["type"] in skip_types:
            continue
        out.setdefault(story_key(f), []).append(f)
    for v in out.values():
        v.sort(key=lambda f: (f["day"], f["id"]))
    return out


# ---------------------------------------------------------------- 單一件事的口語說法
# 佔位：角色名（依 roles）、{when}、{place}、{amt}、{charge}、{cause}、{property}、{reason}、{role}、{text}
SPOKEN = {
    "theft": ["{when}{thief}在{place}順走了{victim}{amt}文錢", "{thief}{when}把手伸進了{victim}的錢匣，摸走{amt}文",
              "{victim}{when}在{place}丟的那{amt}文，是{thief}拿的"],
    "caught_stealing": ["{when}{thief}想摸{victim}的錢，手還沒縮回去就被逮個正著", "{thief}{when}在{place}伸手被{victim}當場抓住",
                        "{when}{place}有人喊抓賊，抓到的是{thief}，想偷的是{victim}的錢"],
    "theft_report": ["{victim}{when}在{place}丟了{amt}文，到現在還不知道是誰幹的", "{when}{victim}的錢少了{amt}文，翻遍了{place}也沒找著",
                     "{victim}{when}被人摸走{amt}文，賊還沒抓到"],
    "accusation": ["{accuser}一口咬定，偷{victim}錢的就是{accused}", "{accuser}說，{victim}丟的錢八成是{accused}拿的",
                   "照{accuser}的說法，{victim}那筆錢跟{accused}脫不了關係"],
    "arrest": ["{when}{guard}以{charge}的罪名把{suspect}押進了巡檢所", "{suspect}{when}被{guard}帶走了，說是{charge}",
               "{guard}{when}把{suspect}抓進了拘房"],
    "release": ["{who}{when}從拘房放出來了", "{who}{when}出了巡檢所"],
    "bribe": ["{briber}塞了錢給{guard}，{prisoner}才從拘房出來的"],
    "fight": ["{when}{attacker}在{place}跟{victim}動了手，把人打傷了", "{attacker}跟{victim}{when}在{place}打了一架，{victim}吃了虧",
              "{when}{place}那邊鬧哄哄的，是{attacker}揍了{victim}"],
    "debt_warning": ["{collector}{when}找上{debtor}，說欠{lender}的錢過期了", "{when}{collector}去跟{debtor}打了招呼——{lender}那筆錢，該還了"],
    "debt_threat": ["{when}{collector}在{place}揪著{debtor}的衣領逼債", "{collector}{when}當街堵住{debtor}，要人把欠{lender}的錢吐出來"],
    "debt_beating": ["{when}{attacker}替{lender}討債，把{victim}揍了一頓", "{victim}{when}還不出{lender}的錢，挨了{attacker}一頓打"],
    "property_seized": ["{lender}{when}收走了{debtor}的{property}抵債", "{debtor}的{property}{when}被{lender}拿去抵債了"],
    "debt_transferred": ["{debtor}還不出錢，{lender}的債落到了保人{guarantor}頭上"],
    "loan": ["{borrower}欠{lender}{amt}文", "{borrower}跟{lender}借了{amt}文"],
    "loan_repaid": ["{borrower}{when}把欠{lender}的錢還清了"],
    "debt_paid_by": ["{payer}{when}替{debtor}還清了欠{lender}的{amt}文", "{debtor}欠{lender}的錢，{when}是{payer}出面結的"],
    "debt_forgiven": ["{lender}{when}免了{borrower}的債"],
    "gamble_loss": ["{who}{when}在賭坊輸了{amt}文", "{when}{who}在賭桌上一口氣輸掉{amt}文"],
    "gamble_win": ["{who}{when}在賭坊贏了{amt}文", "{when}{who}手氣旺，在賭坊贏了{amt}文"],
    "help_money": ["{giver}{when}拿了{amt}文給{receiver}應急", "{receiver}手頭緊的時候，是{giver}塞了{amt}文過去"],
    "medicine": ["{giver}{when}給{receiver}送了一帖藥"],
    "ill": ["{who}{when}病倒了", "{who}{when}起就躺在床上起不來"],
    "worse": ["{who}的病一天比一天重", "{who}的病越拖越重了"],
    "recovered": ["{who}的身子{when}好些了", "{who}{when}能下床走動了"],
    "death": ["{who}{when}走了{cause}", "{who}{when}過世了{cause}"],
    "grieving": ["{who}沒了{lost}，整個人都變了"],
    "fled": ["{who}{when}離開了青石鎮，沒說要去哪", "{when}起就再沒見過{who}，說是走了"],
    "arrival": ["{when}鎮上來了個生面孔，叫{who}，看樣子是{role}", "{who}是{when}才進鎮的，像是{role}"],
    "rent_unpaid": ["{tenant}付不出給{landlord}的租錢", "{tenant}欠了{landlord}的租"],
    "evicted": ["{landlord}{when}收回了{tenant}的鋪位", "{tenant}的鋪位{when}被{landlord}收回去了"],
    "trader": ["行商{trader}{when}進鎮了，帶了一批藥材和南貨"],
    "fire": ["{property}{when}半夜走了水，燒掉不少東西", "{when}夜裡{property}起了火，{owner}心疼得不得了"],
    "quit_job": ["{who}{when}不幹了，把活兒撂下就走"],
    "fired": ["{owner}{when}把{who}辭了"],
    "hired": ["{owner}{when}雇了{who}去幹活"],
    "wages_unpaid": ["{employer}好幾天沒給{who}工錢了"],
    "revenge_vow": ["{who}放話了，說這筆帳一定要找{target}算", "{who}認定是{target}害的，咬著牙說絕不放過"],
    "rescue": ["{when}{helper}替{target}擋下了{attacker}", "{attacker}{when}要對{target}動手，是{helper}攔住的"],
    "persuade": ["{when}{helper}好說歹說，把{attacker}勸住了"],
    "need": ["{who}{text}"],
    "found_purse": ["{who}{when}在路邊撿到一個錢袋"],
    "dog_bite": ["{who}{when}被野狗咬傷了腿"],
    "letter": ["{who}{when}收到一封外地寄來的信"],
    "clue": ["在{place}找到{what}，看起來跟{suspect}有關"],
}


class _Safe(Formatter):
    def get_value(self, key, args, kwargs):
        if key not in kwargs:
            raise KeyError(key)
        return kwargs[key]


def spoken(w, f: dict, speaker: str | None = None, listener: str = "player", timed: bool = True,
           owner: str | None = None) -> str:
    """一件事的口語說法（不含句號）。owner：用誰的記性挑句子（同一個人不連著用同一個句型）。"""
    n = namer(w, speaker, listener)
    pool = SPOKEN.get(f["type"])
    if not pool:
        return T.fact_text(w, f, speaker=speaker, listener=listener).rstrip("。")
    d = f["data"]
    vals = {k: n(v) for k, v in f["roles"].items()}
    vals.update({
        "when": when(w, f["day"]) if timed else "",
        "place": T._loc(f["place"]),
        "amt": d.get("amount", "幾"),
        "charge": f"「{d.get('charge', '犯事')}」",
        "cause": ("，" + d["cause_text"]) if d.get("cause_text") else "",
        "property": d.get("property", "產業"),
        "reason": d.get("reason", ""),
        "role": d.get("role", "外地人"),
        "text": d.get("text", "有難處"),
        "what": d.get("what", "一點痕跡"),
    })
    tpl = pick(w, owner or "_spoken", pool) if len(pool) > 1 else pool[0]
    try:
        return _Safe().format(tpl, **vals)
    except (KeyError, IndexError, ValueError):
        return T.fact_text(w, f, speaker=speaker, listener=listener).rstrip("。")


# ---------------------------------------------------------------- 一整個故事的說法
def _names(n, refs: list[str]) -> str:
    seen = []
    for r in refs:
        if r and n(r) not in seen:
            seen.append(n(r))
    if len(seen) > 3:
        return "、".join(seen[:3]) + "好幾家"
    return "、".join(seen)


def _crime_text(w, facts, speaker, listener, subject, timed, owner) -> str:
    n = namer(w, speaker, listener)
    s = n(subject)
    steals = [f for f in facts if f["type"] in ("theft", "caught_stealing")]
    caught = [f for f in steals if f["type"] == "caught_stealing"]
    accs = [f for f in facts if f["type"] == "accusation"]
    arrests = [f for f in facts if f["type"] == "arrest"]
    outs = [f for f in facts if f["type"] in ("release", "bribe")]
    parts = []
    if len(steals) == 1:
        parts.append(spoken(w, steals[0], timed=timed, owner=owner, speaker=speaker, listener=listener))
    elif steals:
        refs = [f["roles"].get("victim") for f in steals]
        victims = _names(n, refs)
        span = "幾天" if steals[-1]["day"] - steals[0]["day"] <= 4 else "陣子"
        if len(set(refs)) == 1:
            tpl = pick(w, owner, [f"{s}這{span}老是打{victims}那份錢的主意", f"{s}這{span}一再把手伸向{victims}的錢"])
        else:
            tpl = pick(w, owner, [f"{s}這{span}手腳不乾淨，{victims}那兒都伸過手",
                                  f"{victims}的錢，{s}這{span}都動過念頭",
                                  f"{s}這{span}到處伸手，{victims}都差點遭殃"])
        if len(caught) >= 2:
            tpl += f"，光是當場被逮住就有{cn(len(caught))}回"
        elif len(caught) == 1:
            tpl += "，有一回還被當場逮住"
        parts.append(tpl)
    if accs:
        if len(accs) == 1:
            a = accs[0]
            if steals and a["roles"].get("accuser") == speaker:
                parts.append(f"我看，偷{n(a['roles'].get('victim'))}錢的八成也是{s}")
            elif steals:
                parts.append(f"{n(a['roles'].get('accuser'))}還說，偷{n(a['roles'].get('victim'))}錢的也是{s}")
            else:
                parts.append(spoken(w, a, timed=timed, owner=owner, speaker=speaker, listener=listener))
        else:
            victims = _names(n, [a["roles"].get("victim") for a in accs])
            parts.append(f"好幾個人都說，{victims}丟的錢跟{s}脫不了關係")
    if arrests:
        a = arrests[-1]
        out_after = [o for o in outs if o["day"] >= a["day"]]
        guard = n(a["roles"].get("guard"))
        if out_after:
            o = out_after[-1]
            how = "是有人塞了錢才放的" if o["type"] == "bribe" else "已經放出來了"
            parts.append(f"{'後來' if parts else ''}被{guard}抓進巡檢所關了幾天，{how}")
        elif parts:
            parts.append(f"{when(w, a['day']) if timed else '後來'}被{guard}抓進巡檢所了")
        else:
            parts.append(spoken(w, a, timed=timed, owner=owner, speaker=speaker, listener=listener))
    elif outs:
        parts.append(spoken(w, outs[-1], timed=timed, owner=owner, speaker=speaker, listener=listener))
    return "；".join(p for p in parts if p)


FAMILY_AGAIN = {
    "debt": ["這已經不是頭一回被找上門了", "前前後後被催了好幾回"],
    "fight": ["兩邊這不是頭一回動手了"],
    "gamble": ["這陣子天天往賭坊跑"],
    "health": [],
    "rent": [],
    "job": [],
}


def story_text(w, facts: list[dict], speaker: str | None = None, listener: str = "player", timed: bool = True,
               owner: str | None = None) -> str:
    """一整個故事的說法（不含結尾句號）。facts 必須屬於同一個故事，依時間排序。"""
    if not facts:
        return ""
    owner = owner or speaker or "_story"
    key = story_key(facts[-1])
    fam = key.split(":")[0]
    n = namer(w, speaker, listener)
    if fam == "crime":
        return _crime_text(w, facts, speaker, listener, story_subject(key), timed, owner)
    latest = facts[-1]
    body = spoken(w, latest, speaker=speaker, listener=listener, timed=timed, owner=owner)
    if fam == "health" and latest["type"] == "death" and any(f["type"] in ("ill", "worse") for f in facts[:-1]):
        body = f"{n(latest['roles'].get('who'))}病了好一陣子，{when(w, latest['day']) if timed else '最後'}還是走了"
    elif len(facts) > 1 and FAMILY_AGAIN.get(fam):
        body += "，" + pick(w, owner, FAMILY_AGAIN[fam])
    return body


# ---------------------------------------------------------------- NPC 講一個故事給玩家聽
LEADS = {
    "gossip": ["湊過來，眼睛發亮", "左右看了看，壓低聲音", "神秘兮兮地朝你招招手", "一副憋了很久的樣子"],
    "kind": ["嘆了口氣", "搖了搖頭", "聲音放輕了些"],
    "temper": ["哼了一聲", "撇了撇嘴", "把手上的東西往旁邊一擱"],
    "plain": ["想了想", "像是想起什麼似的", "頓了一下", "隨口提了一句"],
}

SOURCE = {
    "witness": ["我親眼看見的。", "當時我就在旁邊。", "我就在那兒，看得清清楚楚。"],
    "town": ["現在街上都在講。", "滿鎮子都傳遍了。", "這事誰不知道。"],
    "notice": ["告示上都貼出來了。"],
    "npc": ["是{x}跟我說的。", "我也是聽{x}講的。", "{x}說的，真假我可不敢保證。"],
}

STANCE = {
    "crime_contempt": ["這種人，早該關起來。", "活該。", "我早看出來那雙手不老實。", "鎮上就是有這種人，才搞得人心惶惶。"],
    "crime_pity": ["說到底，也是窮怕了。", "唉，好好一個人，怎麼走到這一步。", "可憐歸可憐，偷就是不對。"],
    "crime_doubt": ["我是不太信，可大家都這麼說。", "這事……我總覺得哪裡不對。", "人言可畏啊。"],
    "crime_wary": ["你自己也留點神，錢袋看緊。", "這陣子出門，錢別露白。"],
    "crime_victim": ["我那些錢，是一文一文攢的。", "下回再讓我撞見，就不是罵兩句的事了。"],
    "debt": ["錢三爺的錢，碰不得啊。", "欠了那種錢，日子就難過了。", "借的時候痛快，還的時候要命。"],
    "debt_hard": ["欠債還錢，天經地義。", "借錢的時候怎麼不想想。"],
    "health": ["人啊，說倒就倒。", "但願能熬過去。", "這種事，誰也說不準。"],
    "death": ["人說走就走，唉。", "活著的人還得過日子。"],
    "fight": ["火氣都太大了。", "打架能打出什麼名堂。", "我看這事還沒完。"],
    "gamble": ["那地方，進去容易出來難。", "十賭九輸，偏偏就是有人不信。"],
    "secret": ["這話出了我的嘴，可就別再傳了。", "你可別說是我說的。"],
}


def lead_for(w, nid) -> str:
    tr = w.npcs[nid]["traits"]
    if tr["gossip"] >= 7:
        pool = LEADS["gossip"]
    elif tr["temper"] >= 7:
        pool = LEADS["temper"] + LEADS["plain"]
    elif tr["kind"] >= 7:
        pool = LEADS["kind"] + LEADS["plain"]
    else:
        pool = LEADS["plain"]
    return pick(w, nid, pool)


def source_phrase(w, nid, f) -> str:
    info = w.npcs[nid]["knows"].get(f["id"])
    if not info:
        return ""
    src = info["src"]
    if src in ("witness", "town", "notice"):
        return pick(w, nid, SOURCE[src], optional=True) or ""
    if src in w.npcs and src != nid and chance(w, nid, 50):
        line = pick(w, nid, SOURCE["npc"], optional=True)
        return line.format(x=w.name(src)) if line else ""
    return ""


def stance(w, nid, facts: list[dict]) -> str:
    """說的人怎麼看這件事——由他對當事人的看法與性子決定。只是語氣，不影響任何數值。"""
    n = w.npcs[nid]
    tr = n["traits"]
    latest = facts[-1]
    key = story_key(latest)
    fam = key.split(":")[0]
    subj = story_subject(key)
    op = w.opinion(nid, subj) if subj and subj != nid and (subj in w.npcs or subj == "player") else 0
    if fam == "crime":
        if any(f["roles"].get("victim") == nid for f in facts):
            pool = STANCE["crime_victim"]
        elif op >= 30:
            pool = STANCE["crime_doubt"]
        elif op <= -20 or tr["temper"] >= 7:
            pool = STANCE["crime_contempt"]
        elif tr["kind"] >= 7:
            pool = STANCE["crime_pity"]
        else:
            pool = STANCE["crime_wary"]
    elif fam == "debt":
        pool = STANCE["debt"] if tr["kind"] >= 5 else STANCE["debt_hard"]
    elif fam == "health":
        pool = STANCE["death"] if latest["type"] == "death" else STANCE["health"]
    elif fam in ("fight", "gamble"):
        pool = STANCE[fam]
    elif latest["secrecy"] in ("secret", "private"):
        pool = STANCE["secret"]
    else:
        return ""
    if tr["gossip"] >= 7 and latest["secrecy"] != "public" and chance(w, nid, 40):
        pool = STANCE["secret"]
    return pick(w, nid, pool, optional=True) or ""


UPDATE_INTRO = ["那件事又有後續了——", "你應該也聽說了一些吧？", "還記得那件事嗎？", "那件事啊，後來又鬧大了——"]
FIRST_INTRO = ["跟你說件事，", "你聽說了沒？", "說到這個——"]


def retell(w, nid, facts: list[dict], known_before: int = 0, intro: bool = False) -> str:
    """nid 把一個故事講給玩家聽。known_before：玩家原本已經知道這個故事的幾件事。"""
    key = story_key(facts[-1])
    subj = story_subject(key)
    body = story_text(w, facts, speaker=nid, owner=nid)
    head = ""
    if known_before and subj and subj not in (nid,):
        head = pick(w, nid, UPDATE_INTRO)
    elif intro:
        head = pick(w, nid, FIRST_INTRO, optional=True) or ""
    tail = ""
    src = source_phrase(w, nid, facts[-1])
    st = stance(w, nid, facts) if chance(w, nid, 70) else ""
    tail = "".join(x for x in (src, st) if x)
    return f"{w.name(nid)}{lead_for(w, nid)}：「{head}{body}。{tail}」"


# ---------------------------------------------------------------- 清晨的街談、告示
DAWN_INTRO = ["一早，井邊打水的人都在議論：", "天還沒大亮，早點攤前就有人在說：", "街坊們三三兩兩湊在一起，說的都是同一件事：",
              "你聽見路過的人在嚼舌根：", "賣早點的一邊揉麵一邊跟客人說："]
DAWN_MORE = ["另外還有些零零碎碎的閒話，你順耳聽了幾句。", "其餘的閒話，你聽了個大概。"]


def dawn_digest(w, stories: list[tuple[str, list[dict], int]], limit: int = 2) -> list[str]:
    """stories：[(key, 這個故事玩家現在知道的事實, 之前已知幾件)]。最多講 limit 個，其他的一句帶過。"""
    stories = sorted(stories, key=lambda s: (-max(f["importance"] for f in s[1]), -s[1][-1]["day"]))
    out = []
    for key, facts, before in stories[:limit]:
        intro = pick(w, "_dawn", DAWN_INTRO)
        body = story_text(w, facts, owner="_dawn")
        if before:
            body = "又有新消息——" + body
        out.append(f"{intro}{body}。")
    if len(stories) > limit:
        out.append(pick(w, "_dawn", DAWN_MORE))
    return out


# ---------------------------------------------------------------- NPC 提起你做過的事
GOOD_TYPES = {"rescue", "persuade", "debt_paid_by", "help_money", "medicine"}
MINOR_TYPES = {"player_work", "loan", "trained", "loan_repaid", "debt_warning", "need", "accusation", "clue"}

DEED_LOOK = {
    "bad": ["打量你的眼神多了幾分提防", "的語氣冷了幾分", "往後退了半步", "上下打量了你一眼"],
    "good": ["看你的眼神不太一樣了", "朝你點了點頭", "臉上多了點笑意"],
    "sorry": ["看了看你", "壓低了聲音"],
}
DEED_HEARD = {
    "witness": ["那天我可就在旁邊——", "我親眼看見的，", ""],
    "town": ["滿街都在說，", "我聽說了，", ""],
    "npc": ["聽{x}說，", "{x}都跟我講了，"],
}
DEED_TAIL = {
    "bad": ["這種事在青石鎮傳得快。", "我勸你收斂點。", "別在我這兒動歪腦筋。", "哼。"],
    "bad_soft": ["日子再難，也別走那條路。", "我就當沒聽過，你好自為之。"],
    "good": ["這年頭，肯伸手的人不多了。", "看不出來，你還挺講義氣。", "這份情，鎮上的人會記得的。"],
    "sorry": ["你自己小心點。", "那些人惹不起，能躲就躲。", "沒傷著哪吧？"],
}
VICTIM_OF_PLAYER = ["「你還敢站到我面前？」", "「手放在我看得見的地方。」", "「上回的帳，我可沒忘。」", "「離我的錢遠一點。」"]
GUARD_AFTER = ["「出來了？這回的教訓，記住了。」", "「再讓我逮到一次，就不是關幾天的事了。」", "「我盯著你呢。」"]
JAILER_AFTER = ["「喲，出來啦。裡頭的飯不好吃吧？」", "「別再進來了，我可懶得給你送飯。」"]
KINDRED = ["「嘿，原來你也是同道中人。」", "「手藝不行啊，這麼容易就被逮。」", "「下回挑人少的時候。……我什麼都沒說。」"]
THANKED = ["「那天的事……謝謝你。」", "「你幫過我，我記著。」", "「上回多虧了你。」"]


def involves_player(n: dict, f: dict) -> bool:
    """這個人「認為」這件事跟玩家有關嗎？有自己的版本就看自己的版本（不知道是誰做的，就不會來找玩家說）。"""
    v = (n["knows"].get(f["id"]) or {}).get("view")
    if v is not None:
        return "player" in (v.get("actor"), v.get("host"))
    return "player" in f["roles"].values()


def deed_remark(w, nid) -> str | None:
    """nid 聽說過玩家做的事時，見面會提起。每個故事只提一次（故事有新進展才會再提），
    不是每個人都會提——當事人、在場的人、捕快一定會，其他人看性子。回傳整句台詞或 None。"""
    p = w.player
    n = w.npcs[nid]
    remarked = p.setdefault("remarked", {}).setdefault(nid, {})
    best = None
    for key, facts in stories_of(w, nid).items():
        # 玩家自己告訴他的事，他不會再拿來對玩家說一遍
        mine = [f for f in facts if involves_player(n, f) and f["type"] not in MINOR_TYPES
                and n["knows"].get(f["id"], {}).get("src") != "player"]
        if not mine or mine[-1]["day"] < w.day - 8 or remarked.get(key, 0) >= len(mine):
            continue
        score = (max(f["importance"] for f in mine), mine[-1]["day"])
        if best is None or score > best[0]:
            best = (score, key, mine, facts)
    if not best:
        return None
    _, key, mine, facts = best
    remarked[key] = len(mine)
    latest = mine[-1]
    involved = nid in latest["roles"].values() or any(n["knows"].get(f["id"], {}).get("src") == "witness" for f in mine)
    role_guard = nid in ("zhao", "xiaoli") and key == "crime:player"
    if not (involved or role_guard or chance(w, nid, 30 + n["traits"]["gossip"] * 5 + abs(w.opinion(nid, "player")) / 3)):
        return None
    name = w.name(nid)
    culprit = w.culprit_of(latest)
    if key == "crime:player":
        arrested = any(f["type"] == "arrest" for f in mine)
        if any(f["roles"].get("victim") == nid for f in mine):
            return f"{name}一見是你，臉就沉了下來：{pick(w, nid, VICTIM_OF_PLAYER)}"
        if arrested and nid == "zhao":
            return f"{name}斜眼看你：{pick(w, nid, GUARD_AFTER)}"
        if arrested and nid == "xiaoli":
            return f"{name}咧嘴一笑：{pick(w, nid, JAILER_AFTER)}"
    if latest["type"] in GOOD_TYPES and culprit != "player" and nid in latest["roles"].values() and \
            latest["roles"].get("attacker") != nid:
        return f"{name}：{pick(w, nid, THANKED)}"
    if key == "crime:player" and any(f["type"] in ("caught_stealing", "theft") and f["roles"].get("thief") == nid
                                     for f in w.facts_known(nid)):
        return f"{name}瞇著眼睛打量你：{pick(w, nid, KINDRED)}"
    if culprit == "player" or key == "crime:player":
        mood = "bad" if w.opinion(nid, "player") < 30 and n["traits"]["kind"] < 7 else "bad_soft"
        look = "bad"
    elif latest["type"] in GOOD_TYPES:
        mood = look = "good"
    else:
        mood = look = "sorry"
    src = n["knows"].get(latest["id"], {}).get("src", "town")
    heard_pool = DEED_HEARD["npc"] if src in w.npcs else DEED_HEARD.get(src, DEED_HEARD["town"])
    heard = pick(w, nid, heard_pool).format(x=w.name(src) if src in w.npcs else "")
    body = story_text(w, mine, speaker=nid, owner=nid)
    tail = pick(w, nid, DEED_TAIL[mood], optional=True) or ""
    return f"{name}{pick(w, nid, DEED_LOOK[look])}：「{heard}{body}？{tail}」" if mood != "sorry" else \
        f"{name}{pick(w, nid, DEED_LOOK[look])}：「{heard}{body}。{tail}」"
