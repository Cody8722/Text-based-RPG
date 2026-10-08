"""對話：玩家跟 NPC 說話時，NPC 願意講什麼、怎麼回應。

規則決定「說不說、說哪一條、好感怎麼變、錢怎麼動」；文字用 NPC 自己的口吻模板組出來。
有 LLM 時，說書人只把這些已確定的台詞潤飾得更像那個人在說話。
自由輸入的一句話，只會被對應到既有的幾種意圖（白名單），不會產生新的效果。
"""

from __future__ import annotations

from . import behaviors, sim, speech
from .content import text as T
from .content.npcs import CHATTER, NPCS, TALK

TALK_KINDS = {"chat", "ask_news", "ask_about", "ask_self", "tell", "give", "lend", "collect", "give_med",
              "work", "buy_med", "treat", "train", "borrow", "repay_own", "pay_for", "bribe_release", "bail",
              "accuse", "fortune", "alms", "end_talk", "doctor_self"}

GENERIC_VOICE = {
    "warm": ["「是你啊，坐。」", "「你來得正好。」"],
    "neutral": ["「有事嗎？」", "「嗯？」"],
    "cold": ["「……我跟你沒什麼好說的。」"],
    "deflect": ["「這我可不清楚。」", "「別問我。」"],
    "trouble": ["「……既然你問了。」"],
    "thanks": ["「多謝你。」"],
}


EXTRA_COLD = ["「我跟你沒什麼好說的。」", "「你走吧。」", "「……」連看都沒看你一眼。", "「別在這兒礙眼。」"]
EXTRA_DEFLECT = ["「這人我不熟。」", "「不清楚，你問別人吧。」", "「你問錯人了。」", "「沒聽說什麼。」", "「這種事，少打聽為妙。」"]


def voice(w, nid, key):
    vk = w.npcs[nid].get("voice_key", nid)
    lines = list(NPCS.get(vk, {}).get("voice", GENERIC_VOICE).get(key) or GENERIC_VOICE[key])
    if key == "deflect":
        lines += EXTRA_DEFLECT
    elif key == "cold":
        lines += EXTRA_COLD
    return speech.pick(w, nid, lines)


def rebuff(w, nid):
    """對你沒好感的人，問什麼都碰釘子；碰到第三次，對方就不理你了。"""
    c = w.player.get("convo") or {}
    c["rebuffs"] = c.get("rebuffs", 0) + 1
    if c["rebuffs"] >= 3:
        wear_out(w, nid)
    else:
        say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'cold')}")


# 同一天第二次以後碰面：不再用初見的招呼
AGAIN = {
    "warm": ["「又來啦？」", "「還有事？說吧。」", "「怎麼，又想起什麼了？」"],
    "neutral": ["「又是你。」", "「還有什麼事？」", "「嗯？剛才不是才見過。」"],
    "cold": ["「怎麼又是你。」", "「沒完沒了是吧？」"],
}
# 同一場談話裡問了又問
REPEAT_ASK = ["「剛不是說過了？」", "「同樣的話，你要我說幾遍？」", "「你今天怎麼老問這個。」", "「就那樣，沒別的了。」"]
WEARY = ["{n}擺擺手，不想再說了。", "{n}打了個哈欠：「改天再聊吧。」說完就忙自己的去了。",
         "{n}看了看天色：「好了，我還有事。」", "{n}的眼神已經飄到別處去了，顯然不想再聊。"]


def tier(w, nid):
    op = w.opinion(nid, "player")
    return "warm" if op >= 40 else "cold" if op <= -25 else "neutral"


def say(w, nid, text):
    sim.beat(w, "speech", text, None)
    w.feed[-1]["speaker"] = nid


def act(aid, label, group, hint=None):
    from .player import act_ as _act

    return _act(aid, label, group, hint)


# ---------------- 對話中可選的事 ----------------
def known_jailed(w) -> list[str]:
    """玩家知道被關著的人：在巡檢所親眼看到，或聽說過他被抓（且還沒聽說被放）。"""
    out = []
    for jid, j in w.npcs.items():
        if j["status"] != "jailed":
            continue
        if w.player["location"] == "yamen":
            out.append(jid)
            continue
        arrests = [w.facts[f]["day"] for f in w.player["knows"] if f in w.facts and w.facts[f]["type"] == "arrest"
                   and w.facts[f]["roles"].get("suspect") == jid]
        if arrests:
            out.append(jid)
    return out


def people_of_interest(w, exclude: str) -> list[str]:
    seen = []
    for fid in reversed(list(w.player["knows"])):
        f = w.facts.get(fid)
        if not f:
            continue
        for ref in f["roles"].values():
            if ref in w.npcs and ref != exclude and ref not in seen:
                seen.append(ref)
    for m in w.player["met"]:
        if m != exclude and m not in seen and m in w.npcs:
            seen.append(m)
    return seen[:10]


def talk_actions(w, nid) -> list[dict]:
    n = w.npcs[nid]
    p = w.player
    out = [act("chat", talk_spec(w, nid)["label"], "talk"), act("ask_news", "問問最近鎮上有什麼事", "talk"),
           act("ask_self", f"問問{w.name(nid)}最近過得怎麼樣", "talk")]
    asked = (p.get("convo") or {}).get("asked", {}) if (p.get("convo") or {}).get("nid") == nid else {}
    for ref in people_of_interest(w, nid):
        if not asked.get(f"ask_about:{ref}"):   # 這場談話裡問過的人就不再列出
            out.append(act(f"ask_about:{ref}", f"打聽{w.name(ref)}", "ask"))
    # 能說出去的是「一件事」（一個故事），不是見聞錄的每一行
    stories = sorted(speech.stories_of(w, "player").values(), key=lambda fs: (fs[-1]["day"], fs[-1]["id"]), reverse=True)
    tried = p.get("told_to", {}).get(nid, {})
    # 跟這個人說過（或被回「早知道了」）的事，除非後來又有新進展，否則不再列出
    stories = [fs for fs in stories if tried.get(speech.story_key(fs[-1]), 0) < len(fs)]
    for fs in stories[:12]:
        label = speech.story_text(w, fs, timed=False, owner="_label")
        out.append(act(f"tell:{fs[-1]['id']}", (label[:38] + "……") if len(label) > 40 else label + "。", "tell"))
    if n["status"] == "normal":
        for amt in (10, 30, 50):
            if p["money"] >= amt:
                out.append(act(f"give:{amt}", f"給{w.name(nid)}{amt}文", "money"))
        for amt in (30, 60):
            if p["money"] >= amt:
                out.append(act(f"lend:{amt}", f"借{w.name(nid)}{amt}文（約定七天後還）", "money"))
        for ln in w.open_loans(borrower=nid, lender="player"):
            out.append(act(f"collect:{ln['id']}", f"提醒{w.name(nid)}欠你的{ln['due_amount']}文", "money"))
        if p["inventory"].get("medicine", 0) > 0 and (n.get("bedridden") or n["condition"] != "healthy" or
                                                     any(w.npcs[f].get("bedridden") for f in w.family_of(nid))):
            out.append(act("give_med", f"把身上的藥給{w.name(nid)}", "money"))
    # 角色專屬
    if nid == w.properties["tavern"]["owner"] or nid in ("chenbo", "sun"):
        if w.opinion(nid, "player") >= 10 and w.period in (1, 2, 3):
            out.append(act("work", "問問有沒有活可以幫忙", "role"))
    if nid == "bai" and n["status"] == "normal":
        price = 22 if p["background"] == "herbalist" else sim.MEDICINE_PRICE
        if p["money"] >= price:
            out.append(act("buy_med", f"買一帖藥（{price}文）" + ("" if w.medicine_stock > 0 else "——好像斷貨了"), "role"))
        if p["health"] < 80 and p["money"] >= sim.DOCTOR_FEE:
            out.append(act("doctor_self", f"請白大夫看看你的傷（{sim.DOCTOR_FEE}文）", "role"))
    if nid == "tie" and n["status"] == "normal" and p["money"] >= 10 and w.period in (0, 1, 2, 3):
        out.append(act("train", "跟鐵師傅學一陣拳（10文）", "role"))
    if nid == "qian" and n["status"] == "normal":
        mine = w.open_loans(borrower="player", lender="qian")
        if not mine and w.opinion("qian", "player") > -40:
            out.append(act("borrow:50", "跟錢三爺借五十文", "role", hint="risky"))
            out.append(act("borrow:100", "跟錢三爺借一百文", "role", hint="risky"))
        for ln in mine:
            if p["money"] >= ln["due_amount"]:
                out.append(act(f"repay_own:{ln['id']}", f"把欠的{ln['due_amount']}文還清", "role"))
        for ln in w.open_loans(lender="qian"):
            if ln["borrower"] != "player" and ln.get("fact") in p["knows"] and p["money"] >= ln["due_amount"]:
                out.append(act(f"pay_for:{ln['id']}", f"替{w.name(ln['borrower'])}還清欠款（{ln['due_amount']}文）", "role"))
    if nid == "xiaoli" and n["status"] == "normal":
        for jid in known_jailed(w):
            if p["money"] >= 30:
                out.append(act(f"bribe_release:{jid}", f"塞錢讓他放了{w.name(jid)}（30文）", "role", hint="risky"))
    if nid == "zhao" and n["status"] == "normal":
        for jid in known_jailed(w):
            if p["money"] >= 50:
                out.append(act(f"bail:{jid}", f"替{w.name(jid)}繳保釋金（50文）", "role"))
        for fid in p["knows"]:
            f = w.facts.get(fid)
            if f and f["type"] == "theft_report":
                case = next((c for c in w.cases.values() if c["crime"] in (fid, f["data"].get("crime")) and c["status"] == "open"), None)
                if case is None and f["roles"]["victim"] != "player":
                    continue
                for ref in people_of_interest(w, "zhao")[:6]:
                    if ref != f["roles"]["victim"]:
                        out.append(act(f"accuse:{fid}:{ref}", f"跟捕頭說：偷{w.name(f['roles']['victim'])}錢的，八成是{w.name(ref)}", "accuse"))
    if nid == "banxian" and n["status"] == "normal" and p["money"] >= 5:
        out.append(act("fortune", "請半仙算一卦（5文）", "role"))
    if nid == "zhang" and n["status"] == "normal" and p["money"] >= 5:
        out.append(act("alms", "給他五文錢買點吃的", "role"))
    out.append(act("end_talk", "結束談話", "talk"))
    return out


# ---------------- 開始／進行 ----------------
def start_talk(w, nid):
    p = w.player
    p["talking_to"] = nid
    p["convo"] = {"nid": nid, "asked": {}, "turns": 0}
    n = w.npcs[nid]
    first = nid not in p["met"]
    if first:
        p["met"].append(nid)
        n["met_player"] = True
        sim.beat(w, "action", f"{n['appearance']}這人是{n['call']}，{n['role']}。", None)
    t = tier(w, nid)
    greeted = p.setdefault("greeted", {})
    if not first and greeted.get(nid) == w.day:
        say(w, nid, f"{w.name(nid)}：{speech.pick(w, nid, AGAIN[t])}")
    else:
        say(w, nid, f"{w.name(nid)}：{voice(w, nid, t)}")
    greeted[nid] = w.day
    comment_on_deeds(w, nid)


def comment_on_deeds(w, nid):
    """NPC 聽說過你做的事，會提起——世界記得你。每個故事只提一次，不是每個人都會提（見 speech.deed_remark）。"""
    line = speech.deed_remark(w, nid)
    if line:
        say(w, nid, line)


def asked_again(w, nid, kind: str, arg: str = "") -> int:
    """這場談話裡，這個問題已經問過幾次（不含這次）。"""
    c = w.player.get("convo") or {}
    if c.get("nid") != nid:
        c = w.player["convo"] = {"nid": nid, "asked": {}, "turns": 0}
    k = f"{kind}:{arg}"
    n = c["asked"].get(k, 0)
    c["asked"][k] = n + 1
    return n


def wear_out(w, nid, opinion_cost: int = 0):
    """問煩了：對方結束談話。"""
    sim.beat(w, "action", speech.pick(w, nid, WEARY).format(n=w.name(nid)))
    if opinion_cost:
        w.adjust_opinion(nid, "player", -opinion_cost)
    w.player["talking_to"] = None


def do_talk(w, action_id, text=None):
    nid = w.player["talking_to"]
    kind, _, arg = action_id.partition(":")
    if action_id == "say":
        kind, arg = route_free_text(w, nid, text or "")
        sim.beat(w, "player_say", f"你說：「{clean_text(text or '')}」")
    n = w.npcs[nid]
    p = w.player
    if kind == "end_talk":
        p["talking_to"] = None
        sim.beat(w, "action", f"你跟{w.name(nid)}道了別。")
        return
    handler = HANDLERS.get(kind)
    if handler:
        convo = p.get("convo") or {}
        convo["turns"] = convo.get("turns", 0) + 1
        handler(w, nid, arg)
    if p.get("talking_to"):
        sim.advance(w, 1)


def clean_text(s: str) -> str:
    s = "".join(ch for ch in s if ch.isprintable() and ch not in "\r\n\t")
    return s[:80]


def route_free_text(w, nid, text: str) -> tuple[str, str]:
    """自由輸入 → 既有意圖（白名單、精確比對別名，不做模糊比對）。"""
    t = clean_text(text)
    for ref, other in w.npcs.items():
        if ref == nid or other["status"] == "dead" and ref not in w.player["met"]:
            continue
        for alias in other["aliases"]:
            if alias and alias in t:
                return "ask_about", ref
    if any(k in t for k in ("最近", "消息", "新鮮事", "發生", "聽說", "八卦")):
        return "ask_news", ""
    if any(k in t for k in ("還好嗎", "怎麼了", "難處", "幫忙", "需要", "臉色", "煩", "你最近")):
        return "ask_self", ""
    return "chat", ""


# ---------------- 各種談話動作 ----------------
def talk_spec(w, nid) -> dict:
    return TALK.get(w.npcs[nid].get("voice_key", nid), TALK["generic"])


def chat_scene(w, nid) -> str:
    """場景（在哪、白天晚上）× 這個人會聊的話題 × 交情與心情，組出寒暄的敘述。"""
    n = w.npcs[nid]
    p = w.player
    loc = p["location"]
    day_frames, night_frames = T.PLACE_FRAME.get(loc, (["在一旁"], ["在夜色裡"]))
    frames = night_frames if w.period >= 4 else day_frames
    frame = "坐在床邊" if n.get("bedridden") else "隔著木柵" if n["status"] == "jailed" else speech.pick(w, f"_frame:{loc}", frames)
    topics = talk_spec(w, nid)["topics"]
    used = p.setdefault("topics_used", {}).setdefault(nid, [])
    fresh = [t for t in topics if t not in used[-(len(topics) - 1):]] or topics
    topic = w.rng.choice(fresh)
    used.append(topic)
    del used[:-6]
    if n.get("bedridden"):
        mood = "bedridden"
    elif n["status"] == "jailed":
        mood = "jailed"
    elif n["stress"] >= 70:
        mood = "stressed"
    else:
        mood = tier(w, nid)
    reaction = speech.pick(w, nid, T.CHAT_REACTION[mood]).format(n=w.name(nid))
    return f"{frame}，你和{w.name(nid)}聊起{topic}。{reaction}"


def h_chat(w, nid, _):
    p = w.player
    n = w.npcs[nid]
    again = asked_again(w, nid, "chat")
    if again >= 3:
        wear_out(w, nid)
        return
    first_today = p["chatted"].get(nid) != w.day
    p["chatted"][nid] = w.day
    gain = 4 if first_today else 1
    if p["background"] in ("peddler", "drifter") and first_today:
        gain += 1
    w.adjust_opinion(nid, "player", gain)
    line = state_line(w, nid)
    if line:
        say(w, nid, f"{w.name(nid)}：{line}")
    elif n.get("voice_key") in CHATTER and w.opinion(nid, "player") > -25:
        chatter = speech.pick(w, f"{nid}:chatter", CHATTER[n["voice_key"]], optional=True, keep=30)
        if chatter:   # 說過的家常話短期內不再說；說完了就只寫聊天的場景
            say(w, nid, f"{w.name(nid)}：{chatter}")
    sim.beat(w, "action", chat_scene(w, nid))
    if w.roll(n["traits"]["gossip"] * 6 + w.opinion(nid, "player") / 3):
        share_one(w, nid, None, lead=True)


def state_line(w, nid) -> str | None:
    """處境會改變說話內容：喪親、受傷、被關、丟了生計的人，聊天聊不出輕鬆話。"""
    n = w.npcs[nid]
    if n.get("grief_until", 0) >= w.day:
        return speech.pick(w, nid, ["「……」只是盯著桌面，什麼也沒說。", "「別跟我說話。現在不想。」", "「人啊，說沒就沒了。」"])
    if n["status"] == "jailed":
        return speech.pick(w, nid, ["「你來看我笑話的？」", "「我是冤枉的……你信不信？」", "「這裡的飯，狗都不吃。」"])
    if not n.get("employed", True):
        return speech.pick(w, nid, ["「活兒沒了，以後怎麼辦，誰知道呢。」", "「別問了，我現在是個閒人。」"])
    if n["health"] < 50 and not n.get("bedridden"):
        return speech.pick(w, nid, ["「沒事，摔了一跤。」說話時扯到傷口，眉頭一皺。", "「這點傷，死不了。」"])
    if n["stress"] >= 75:
        return speech.pick(w, nid, ["「最近煩心事多，你別見怪。」", "「唉……」一聲長嘆，好像有話卡在喉嚨裡。"])
    return None


def share_one(w, nid, topic, lead=False) -> bool:
    """nid 挑一件玩家還不知道的事告訴他——以「故事」為單位：
    玩家已經聽過的故事，權重大降（只有新進展才值得再提）；講的時候把同一個故事裡能說的一起說完。"""
    opts = behaviors.shareable(w, nid, "player", topic)
    if not opts:
        return False
    known = {speech.story_key(w.facts[f]) for f in w.player["knows"] if f in w.facts}
    told = w.player.setdefault("told_by", {}).setdefault(nid, [])
    weighted = []
    for fid, wt in opts:
        k = speech.story_key(w.facts[fid])
        weighted.append((fid, wt * (0.15 if k in told else 0.4 if k in known else 1.0)))
    fid = w.pick_weighted(weighted)
    if not fid:
        return False
    key = speech.story_key(w.facts[fid])
    before = len(speech.story_facts(w, "player", key))
    shared = behaviors.tell(w, nid, "player", fid)
    if shared == fid:
        for other, _ in opts:
            if other != fid and speech.story_key(w.facts[other]) == key:
                w.learn("player", other, nid)
    skey = speech.story_key(w.facts[shared])
    if skey != key:
        before = len([f for f in speech.story_facts(w, "player", skey) if f["id"] != shared])
    facts = [f for f in speech.story_facts(w, "player", skey) if f["id"] in w.npcs[nid]["knows"] or f["id"] == shared]
    if skey not in told:
        told.append(skey)
    say(w, nid, speech.retell(w, nid, facts, known_before=before, intro=lead))
    return True


NOTHING_NEW = ["「最近？沒什麼新鮮的。」", "「該說的都說了，鎮上這幾天就這樣。」", "「我知道的，你大概也都聽過了。」",
               "「沒了沒了，再問我也變不出來。」"]


def h_ask_news(w, nid, _):
    n = w.npcs[nid]
    bonus = 10 if w.player["background"] == "scholar" else 0
    again = asked_again(w, nid, "ask_news")
    if w.opinion(nid, "player") < -30:
        rebuff(w, nid)
        return
    if again >= 3:
        wear_out(w, nid)
        return
    if w.roll(40 + n["traits"]["gossip"] * 6 + bonus - again * 15) and share_one(w, nid, None):
        return
    # 鎮上的瑣事：玩家聽過的不再聽一遍（不管是誰說的）
    heard = w.player.setdefault("small_news", [])
    pool = T.LOCAL_NEWS.get(w.player["location"], []) + T.SMALL_NEWS
    fresh = [x for x in pool if x not in heard]
    if again or not fresh:
        say(w, nid, f"{w.name(nid)}：{speech.pick(w, nid, NOTHING_NEW)}")
        return
    line = speech.text_rng(w, "_small").choice(fresh)
    heard.append(line)
    del heard[:-20]
    say(w, nid, f"{w.name(nid)}想了想：{line}")


FEEL = {
    "respect": ["說起{t}，{s}的語氣裡帶著敬重", "{s}一聽是{t}，坐直了些"],
    "like": ["提到{t}，{s}笑了笑", "{s}一聽是問{t}，神情軟了下來"],
    "plain": ["{s}想了想{t}這個人", "{s}聽你問起{t}，抬了抬眉毛", "「{t}？」{s}重複了一遍", "{s}摸著下巴想了一會兒"],
    "dislike": ["聽到{t}的名字，{s}皺了皺眉", "{s}的臉色淡了下來"],
    "hate": ["說到{t}，{s}撇了撇嘴", "{s}一聽{t}的名字就哼了一聲"],
}
HEARD_IT = ["{n}聽完，若有所思地點了點頭。", "{n}「嗯」了一聲，沒多說什麼。", "{n}聽得很仔細，末了只說了句：「知道了。」",
            "{n}眉毛挑了挑：「還有這種事。」", "{n}沉默了一會兒，像是在掂量這話的分量。"]


def h_ask_about(w, nid, ref):
    n = w.npcs[nid]
    if ref not in w.npcs:
        return
    if asked_again(w, nid, "ask_about", ref):
        say(w, nid, f"{w.name(nid)}：「{w.name(ref)}的事，我知道的就這些了。」")
        return
    op = w.opinion(nid, ref)
    band = "respect" if op >= 50 else "like" if op >= 20 else "hate" if op <= -40 else "dislike" if op <= -15 else "plain"
    feel = speech.pick(w, nid, FEEL[band])
    sim.beat(w, "action", feel.format(t=w.name(ref), s=w.name(nid)) + "。")
    shared = 0
    if w.opinion(nid, "player") < -30:
        rebuff(w, nid)
        return
    bonus = 10 if w.player["background"] == "scholar" else 0
    for _ in range(2):
        if w.roll(55 + n["traits"]["gossip"] * 4 + bonus + w.opinion(nid, "player") / 4) and share_one(w, nid, ref):
            shared += 1
    if not shared:
        if ref in w.npcs and w.rng.random() < 0.7:
            key = "warm" if op >= 30 else "cold" if op <= -25 else "neutral"
            line = speech.pick(w, nid, T.IMPRESSION[key]).format(t=w.name(ref), role=w.npcs[ref]["role"])
            say(w, nid, f"{w.name(nid)}：{line}")
        else:
            say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'deflect')}")


def h_ask_self(w, nid, _):
    n = w.npcs[nid]
    p = w.player
    threshold = 30 + (n["traits"]["pride"] - 5) * 4
    op = w.opinion(nid, "player")
    again = asked_again(w, nid, "ask_self")
    if again:
        # 同一場談話裡追問：第二次被頂回來，第三次對方不想聊了（交情也薄了一點）
        if again >= 2:
            wear_out(w, nid, opinion_cost=2)
        else:
            say(w, nid, f"{w.name(nid)}：{speech.pick(w, nid, REPEAT_ASK)}")
        return
    if op < threshold:
        if tier(w, nid) == "cold":
            rebuff(w, nid)
            return
        else:
            say(w, nid, f"{w.name(nid)}：{speech.pick(w, nid, T.GUARDED + list(NPCS.get(n.get('voice_key'), {}).get('voice', {}).get('deflect', [])))}")
        if n["stress"] >= 60:
            sim.beat(w, "action", f"可是{w.name(nid)}眼神閃了一下，看得出心裡壓著事。")
        return
    told = False
    for key, fid in (n.get("need_fact") or {}).items():
        f = w.facts.get(fid)
        if f and f["day"] >= w.day - 6 and fid not in p["knows"]:
            say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'trouble')}「{speech.spoken(w, f, speaker=nid, owner=nid)}。」")
            w.learn("player", fid, nid)
            told = True
            break
    if not told and op >= threshold + 15:
        for fid in n["knows"]:
            f = w.facts.get(fid)
            if f and f["type"] == "loan" and f["roles"].get("borrower") == nid and fid not in p["knows"]:
                ln = next((l for l in w.loans.values() if l.get("fact") == fid and l["status"] == "open"), None)
                if ln:
                    say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'trouble')}「{speech.spoken(w, f, speaker=nid, owner=nid)}，日子到了還不知道拿什麼還。」")
                    w.learn("player", fid, nid)
                    told = True
                    break
    if not told:
        if n.get("grief_until", 0) >= w.day:
            say(w, nid, f"{w.name(nid)}沉默了很久，只說了一句：「……人沒了。」")
        else:
            line = state_line(w, nid)
            say(w, nid, f"{w.name(nid)}：{line or speech.pick(w, nid, FINE)}")
    w.adjust_opinion(nid, "player", 2)


FINE = ["「我？好得很，多謝關心。」", "「托你的福，還過得去。」", "「老樣子，餓不死也撐不著。」", "「沒什麼好抱怨的。」"]
ALREADY = ["「這事我早知道了。」", "「你也聽說了？我早就知道了。」", "「這還用你說。」", "「嗯，聽說了。」"]


def h_tell(w, nid, fid):
    f = w.facts.get(fid)
    if not f or fid not in w.player["knows"]:
        return
    story = speech.story_facts(w, "player", speech.story_key(f))
    w.player.setdefault("told_to", {}).setdefault(nid, {})[speech.story_key(f)] = len(story)
    new = [x for x in story if x["id"] not in w.npcs[nid]["knows"]]
    if not new:
        say(w, nid, f"{w.name(nid)}：{speech.pick(w, nid, ALREADY)}")
        return
    for x in new:
        w.learn(nid, x["id"], "player")
    f = new[-1]
    what = speech.story_text(w, story, timed=False, owner="_player")
    what = "自己" + what[1:] if what.startswith("你") else what
    sim.beat(w, "action", f"你把{what}的事告訴了{w.name(nid)}。")
    culprit = w.culprit_of(f)
    if nid == "zhao" and f["type"] in ("theft", "caught_stealing", "debt_beating", "fight", "clue", "theft_report", "smuggling"):
        say(w, nid, f"{w.name(nid)}眉頭一皺，掏出一本皺巴巴的冊子記了幾筆：「這消息有用。」")
        w.adjust_opinion("zhao", "player", 5)
    elif f["type"] == "secret_support" and f["roles"].get("beneficiary") in w.family_of(nid) + [nid]:
        say(w, nid, f"{w.name(nid)}愣住了，好一陣子說不出話。")
    elif culprit and w.opinion(nid, culprit) >= 50:
        say(w, nid, f"{w.name(nid)}的臉色沉了下來：「你別胡說。」")
        w.adjust_opinion(nid, "player", -5)
    else:
        say(w, nid, speech.pick(w, nid, HEARD_IT).format(n=w.name(nid)))
        w.adjust_opinion(nid, "player", 1)


def h_give(w, nid, amt):
    amt = int(amt)
    n = w.npcs[nid]
    op = w.opinion(nid, "player")
    if n["traits"]["pride"] >= 8 and op < 50 and not n.get("bedridden"):
        say(w, nid, f"{w.name(nid)}把你的手推了回去：「你這是什麼意思？我不需要人可憐。」")
        w.adjust_opinion(nid, "player", -3)
        return
    got = w.transfer("player", nid, amt)
    fid = w.add_fact("help_money", {"giver": "player", "receiver": nid}, place=w.player["location"],
                     data={"amount": got}, secrecy="private", importance=2, known_by=[nid],
                     witnesses=sim.witnesses_at(w, w.player["location"], exclude=(nid, "player"), notice_pct=40))
    from .player import deed

    deed(w, fid)
    w.stress(nid, -10)
    say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'thanks')}")


def h_lend(w, nid, amt):
    amt = int(amt)
    got = w.transfer("player", nid, amt)
    fid = w.add_fact("loan", {"lender": "player", "borrower": nid}, place=w.player["location"],
                     data={"amount": got, "due": w.day + 7}, secrecy="private", importance=2, known_by=[nid])
    from .player import deed

    deed(w, fid)
    w.add_loan("player", nid, got, 7, 0, fact_id=fid)
    w.adjust_opinion(nid, "player", 8)
    w.stress(nid, -8)
    say(w, nid, f"{w.name(nid)}接過錢：{voice(w, nid, 'thanks')}「七天，七天之內一定還你。」")


def h_collect(w, nid, lid):
    ln = w.loans.get(lid)
    if not ln or ln["status"] != "open":
        return
    n = w.npcs[nid]
    if w.money(nid) >= ln["due_amount"] and w.roll(30 + n["traits"]["honesty"] * 7):
        sim.repay(w, ln)
        say(w, nid, f"{w.name(nid)}把錢數給你：「拿去吧，一文不少。」")
    else:
        w.adjust_opinion(nid, "player", -5)
        say(w, nid, f"{w.name(nid)}面有難色：「再……再寬限幾天。」")


def h_give_med(w, nid, _):
    n = w.npcs[nid]
    patient = nid if (n.get("bedridden") or n["condition"] != "healthy") else next(
        (f for f in w.family_of(nid) if w.npcs[f].get("bedridden")), nid)
    w.player["inventory"]["medicine"] -= 1
    days = 4 if w.player["background"] == "herbalist" else 3
    w.npcs[patient]["medicine_days"] += days
    w.heal(patient, 5)
    fid = w.add_fact("medicine", {"giver": "player", "receiver": patient}, place=w.player["location"],
                     secrecy="private", importance=3, known_by=[nid, patient])
    from .player import deed

    deed(w, fid)
    say(w, nid, f"{w.name(nid)}捧著那包藥：{voice(w, nid, 'thanks')}")


def h_work(w, nid, _):
    pay = w.rng.randint(6, 10)
    w.add_money("player", pay)
    w.adjust_opinion(nid, "player", 4)
    chores = talk_spec(w, nid).get("work", "搬東西、打雜")
    sim.beat(w, "action", f"你在{w.name(nid)}那兒幫了兩個時辰的忙，{chores}，拿到{pay}文。")
    w.player["talking_to"] = None
    sim.advance(w, 2)


def h_buy_med(w, nid, _):
    if w.medicine_stock <= 0:
        say(w, nid, f"{w.name(nid)}搖搖頭：「藥材斷了，得等行商來。」")
        return
    price = 22 if w.player["background"] == "herbalist" else sim.MEDICINE_PRICE
    w.transfer("player", "bai", price)
    w.medicine_stock -= 1
    w.player["inventory"]["medicine"] = w.player["inventory"].get("medicine", 0) + 1
    say(w, nid, f"{w.name(nid)}把幾味藥包成一帖遞給你：「三碗水煎成一碗，一天一次。」")


def h_doctor_self(w, nid, _):
    w.transfer("player", "bai", sim.DOCTOR_FEE)
    w.heal("player", 25)
    say(w, nid, f"{w.name(nid)}替你敷了藥、正了骨：「年輕人，別逞強。」")


def h_train(w, nid, _):
    from .player import prowess

    before = round(prowess(w), 1)
    w.transfer("player", nid, 10)
    w.player["prowess_n"] += 1
    w.adjust_opinion(nid, "player", 3)
    after = round(prowess(w), 1)
    msg = "你覺得出拳比以前穩了。" if after - before >= 0.3 else "練到後來，你覺得自己好像卡在某個地方，怎麼都過不去。"
    sim.beat(w, "action", f"鐵師傅讓你扎馬步、打木樁，一個時辰下來，汗水濕透了衣裳。{msg}")
    w.player["talking_to"] = None
    sim.advance(w, 2)


def h_borrow(w, nid, amt):
    amt = int(amt)
    got = w.transfer("qian", "player", amt)
    fid = w.add_fact("loan", {"lender": "qian", "borrower": "player"}, place="den",
                     data={"amount": got, "due": w.day + 4}, secrecy="private", importance=3, known_by=["qian", "liu6"])
    from .player import deed

    deed(w, fid)
    w.add_loan("qian", "player", got, 4, 30, fact_id=fid)
    say(w, nid, f"{w.name(nid)}笑瞇瞇地把錢推給你：「四天後，連本帶利{w.loans[f'L{w.loan_seq}']['due_amount']}文。我的規矩，你懂的。」")


def h_repay_own(w, nid, lid):
    ln = w.loans.get(lid)
    if ln and ln["status"] == "open" and w.money("player") >= ln["due_amount"]:
        sim.repay(w, ln)
        say(w, nid, f"{w.name(nid)}：「好說，好說。下次再來。」")


def h_pay_for(w, nid, lid):
    ln = w.loans.get(lid)
    if not ln or ln["status"] != "open" or w.money("player") < ln["due_amount"]:
        return
    fid = sim.repay(w, ln, payer="player")
    from .player import deed

    deed(w, fid)
    say(w, nid, f"{w.name(nid)}挑了挑眉：「替{w.name(ln['borrower'])}還？有意思。」他把帳本上那一行劃掉了。")


def h_bribe_release(w, nid, jid):
    j = w.npcs.get(jid)
    if not j or j["status"] != "jailed":
        return
    if w.roll(w.npcs["xiaoli"]["traits"]["greed"] * 9):
        w.transfer("player", "xiaoli", 30)
        j["status"] = "normal"
        j["jail_until"] = 0
        fid = w.add_fact("bribe", {"briber": "player", "guard": "xiaoli", "prisoner": jid}, place="yamen",
                         secrecy="secret", importance=3, known_by=["xiaoli", jid])
        from .player import deed

        deed(w, fid)
        w.adjust_opinion(jid, "player", 30)
        say(w, nid, f"{w.name(nid)}把錢收進袖子：「趁捕頭不在……快點。」")
    else:
        say(w, nid, f"{w.name(nid)}縮了縮脖子：「你、你想害死我啊？捕頭盯著呢。」")
        w.adjust_opinion("zhao", "player", -5)


def h_bail(w, nid, jid):
    j = w.npcs.get(jid)
    if not j or j["status"] != "jailed":
        return
    w.transfer("player", "zhao", 50)
    j["status"] = "normal"
    j["jail_until"] = 0
    fid = w.add_fact("release", {"who": jid}, place="yamen", importance=2, known_by=[jid, "zhao"])
    w.adjust_opinion(jid, "player", 35)
    say(w, nid, f"{w.name(nid)}收了錢，開了木柵：「既然有人作保，就先放你出去。」")


def h_accuse(w, nid, arg):
    report_id, _, ref = arg.partition(":")
    rep = w.facts.get(report_id)
    if not rep or ref not in w.npcs:
        return
    victim = rep["roles"]["victim"]
    crime = rep["data"].get("crime", report_id)
    true_thief = w.facts[crime]["roles"].get("thief") if crime in w.facts else None
    fid = w.add_fact("accusation", {"accuser": "player", "accused": ref, "victim": victim}, place="yamen",
                     data={"crime": crime}, secrecy="private", importance=3, truth=(ref == true_thief), log=False)
    from .player import deed

    deed(w, fid)
    w.learn("zhao", fid, "player")
    say(w, nid, f"{w.name(nid)}瞇起眼睛看了你一會兒：「{w.name(ref)}？……我會查。可你要是冤枉好人，可別怪我不客氣。」")


def h_fortune(w, nid, _):
    w.transfer("player", nid, 5)
    pool = []
    for fid, info in w.npcs[nid]["knows"].items():
        f = w.facts.get(fid)
        if f and f["secrecy"] in ("secret", "private") and fid not in w.player["knows"] and f["type"] in T.FORTUNE:
            pool.append(f)
    # 半仙耳朵尖：鎮上的秘密他知道的比他承認的多
    for f in w.facts.values():
        if f["secrecy"] == "secret" and f["truth"] and f["type"] in T.FORTUNE and f["id"] not in w.player["knows"]:
            pool.append(f)
    line = T.FORTUNE[w.rng.choice(pool)["type"]] if pool else T.FORTUNE["default"]
    say(w, nid, f"{w.name(nid)}掐著指頭唸唸有詞，半晌才睜開眼：「{line}」")


def h_alms(w, nid, _):
    w.transfer("player", nid, 5)
    w.adjust_opinion(nid, "player", 15)
    say(w, nid, f"{w.name(nid)}：{voice(w, nid, 'thanks')}")
    # 瞎眼張的規矩：一口飯換一句話——他會挑一件你還不知道的事說（連平常不外傳的也可能）
    opts = behaviors.shareable(w, nid, "player")
    if not opts:
        n = w.npcs[nid]
        saved = n["opinions"].get("player", 0)
        n["opinions"]["player"] = max(saved, 60)
        opts = behaviors.shareable(w, nid, "player")
        n["opinions"]["player"] = saved
    fid = w.pick_weighted(opts)
    if fid:
        shared = behaviors.tell(w, nid, "player", fid)
        say(w, nid, f"{w.name(nid)}側著頭，壓低聲音：「{speech.spoken(w, w.facts[shared], speaker=nid, owner=nid)}。」")
    else:
        say(w, nid, f"{w.name(nid)}想了半天：「最近……倒是安靜得很。」")


HANDLERS = {
    "chat": h_chat, "ask_news": h_ask_news, "ask_about": h_ask_about, "ask_self": h_ask_self, "tell": h_tell,
    "give": h_give, "lend": h_lend, "collect": h_collect, "give_med": h_give_med, "work": h_work,
    "buy_med": h_buy_med, "doctor_self": h_doctor_self, "train": h_train, "borrow": h_borrow,
    "repay_own": h_repay_own, "pay_for": h_pay_for, "bribe_release": h_bribe_release, "bail": h_bail,
    "accuse": h_accuse, "fortune": h_fortune, "alms": h_alms,
}
