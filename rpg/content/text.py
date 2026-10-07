"""所有由 Python 產生的文字模板。

沒有 LLM 時，遊戲完全靠這些模板也要讀起來像樣；有 LLM 時，這些模板是「已確定的事實」，
說書人只能潤飾、不能改寫結果。
"""

from __future__ import annotations

from .locations import LOCATIONS


def _n(w, ref):
    return w.name(ref) if ref else "某人"


def _loc(place):
    return LOCATIONS[place]["name"] if place in LOCATIONS else (place or "某處")


# ---------------- 事實 → 一句話（見聞錄、傳話、算命都用它） ----------------
def fact_text(w, f: dict, speaker: str | None = None, listener: str = "player") -> str:
    """speaker：說這句話的人（提到自己時用「我」）；listener：聽的人（是玩家時，提到玩家用「你」）。"""
    r, d, t = f["roles"], f["data"], f["type"]

    def g(k):
        ref = r.get(k)
        if speaker and ref == speaker:
            return "我"
        if ref == "player" and listener != "player":
            return "那個外地人"
        return _n(w, ref)

    amt = d.get("amount")
    if t == "grudge":
        return f"{g('a')}和{g('b')}之間有過節：{d.get('reason', '')}。"
    if t == "loan":
        extra = f"，還拿{d['secured']}作抵押" if d.get("secured") else ""
        guar = f"，{g('guarantor')}是保人" if r.get("guarantor") else ""
        span = d.get("due", f["day"]) - f["day"]
        when = f"說好{span}天內還清" if span > 0 else "說好立刻就還"
        return f"{g('borrower')}欠{g('lender')}{amt}文，{when}{extra}{guar}。"
    if t == "loan_repaid":
        return f"{g('borrower')}把欠{g('lender')}的錢還清了。"
    if t == "debt_paid_by":
        return f"{g('payer')}替{g('debtor')}還清了欠{g('lender')}的{amt}文。"
    if t == "debt_warning":
        return f"{g('collector')}找上{g('debtor')}，說欠{g('lender')}的錢已經過期了。"
    if t == "debt_threat":
        return f"{g('collector')}揪住{g('debtor')}的衣領當眾逼債，要人把欠{g('lender')}的錢吐出來。"
    if t == "debt_beating":
        return f"{g('attacker')}為了討{g('lender')}的債，把{g('victim')}打傷了。"
    if t == "property_seized":
        return f"{g('lender')}收走了{g('debtor')}的{d.get('property', '產業')}抵債。"
    if t == "debt_transferred":
        return f"{g('debtor')}還不出錢，{g('lender')}的債落到了保人{g('guarantor')}頭上。"
    if t == "debt_forgiven":
        return f"{g('lender')}免了{g('borrower')}的債。"
    if t == "theft":
        return f"{g('thief')}從{_loc(f['place'])}偷走了{g('victim')}{amt}文錢。"
    if t == "theft_report":
        return f"{g('victim')}在{_loc(f['place'])}丟了{amt}文錢，還不知道是誰偷的。"
    if t == "caught_stealing":
        return f"{g('thief')}想偷{g('victim')}的錢，被當場撞破。"
    if t == "fight":
        why = f"（{d['reason']}）" if d.get("reason") else ""
        return f"{g('attacker')}在{_loc(f['place'])}對{g('victim')}動了手，把人打傷了{why}。"
    if t == "gamble_loss":
        return f"{g('who')}在賭坊輸了{amt}文。"
    if t == "gamble_win":
        return f"{g('who')}在賭坊贏了{amt}文。"
    if t == "help_money":
        return f"{g('giver')}拿了{amt}文給{g('receiver')}應急。"
    if t == "secret_support":
        return f"{g('patron')}一直暗中替{g('beneficiary')}付藥錢，從沒讓人知道。"
    if t == "medicine":
        return f"{g('giver')}給{g('receiver')}送了一帖藥。"
    if t == "ill":
        return f"{g('who')}病倒了。"
    if t == "worse":
        return f"{g('who')}的病一天比一天重。"
    if t == "recovered":
        return f"{g('who')}的身子好些了。"
    if t == "death":
        cause = d.get("cause_text", "")
        return f"{g('who')}過世了{('，' + cause) if cause else ''}。"
    if t == "arrest":
        return f"{g('guard')}以「{d.get('charge', '犯事')}」把{g('suspect')}抓進了巡檢所。"
    if t == "release":
        return f"{g('who')}從巡檢所的拘房放出來了。"
    if t == "bribe":
        return f"{g('briber')}塞錢給{g('guard')}，把{g('prisoner')}從拘房弄了出來。"
    if t == "fled":
        how = "搭船" if d.get("via") == "boat" else "趁天沒亮出了鎮口"
        return f"{g('who')}{how}離開了青石鎮，沒說要去哪。"
    if t == "arrival":
        return f"鎮上來了個生面孔：{g('who')}，看起來是{d.get('role', '外地人')}。"
    if t == "rent_unpaid":
        return f"{g('tenant')}付不出這七天給{g('landlord')}的租錢。"
    if t == "evicted":
        return f"{g('landlord')}收回了{g('tenant')}的鋪位。"
    if t == "trader":
        return f"行商{g('trader')}進鎮了，帶來一批藥材和南貨。"
    if t == "news":
        return f"{d.get('text', '')}。"
    if t == "need":
        return f"{g('who')}{d.get('text', '有難處')}。"
    if t == "smuggling":
        return f"{g('boatman')}三更半夜替{g('boss')}運一些見不得光的貨。"
    if t == "hidden_savings":
        return f"{g('who')}在某個地方藏了一筆不小的錢。"
    if t == "petty_theft_past":
        return f"{g('who')}手腳不乾淨，以前偷過東西。"
    if t == "secret_love":
        return f"{g('lover')}心裡喜歡{g('beloved')}，只是一直沒說出口。"
    if t == "guard_gambles":
        return f"{g('who')}下了差常常窩在賭坊，帳上還欠著不少。"
    if t == "accusation":
        return f"{g('accuser')}說，偷{g('victim')}錢的人就是{g('accused')}。"
    if t == "clue":
        return f"在{_loc(f['place'])}找到{d.get('what', '一點痕跡')}，看起來跟{g('suspect')}有關。"
    if t == "quit_job":
        return f"{g('who')}不在{_loc(d.get('place'))}幹活了。"
    if t == "fired":
        return f"{g('owner')}把{g('who')}辭退了。"
    if t == "wages_unpaid":
        return f"{g('employer')}已經好幾天沒付{g('who')}工錢了。"
    if t == "found_purse":
        return f"{g('who')}在路邊撿到一個錢袋，裡頭有{amt}文。"
    if t == "fire":
        return f"{g('owner')}的{d.get('property', '鋪子')}半夜起了一場小火，燒掉不少東西。"
    if t == "dog_bite":
        return f"{g('who')}被一條野狗咬傷了腿。"
    if t == "letter":
        return f"{g('who')}收到一封外地寄來的信。"
    if t == "rescue":
        return f"{g('helper')}替{g('target')}擋下了{g('attacker')}。"
    if t == "persuade":
        return f"{g('helper')}好說歹說，勸住了{g('attacker')}。"
    if t == "trained":
        return f"{g('who')}在鐵家武館跟鐵師傅學了一陣拳。"
    if t == "grieving":
        return f"{g('who')}失去了{g('lost')}，整個人都變了。"
    if t == "revenge_vow":
        return f"{g('who')}認定是{g('target')}害的，放話絕不放過{g('target')}。"
    if t == "hired":
        return f"{g('owner')}雇了{g('who')}到{_loc(d.get('place'))}幹活。"
    if t == "player_work":
        return f"{g('who')}在{_loc(f['place'])}幹了一陣活。"
    return f"（{t}）"


# ---------------- 玩家目擊事件時的敘述（比見聞錄生動） ----------------
WITNESS = {
    "theft": [
        "你眼角瞥見{thief}的手飛快地伸進{victim}的錢匣，抓了一把，塞進袖子裡。沒有人注意到。",
        "{thief}趁{victim}轉身的工夫，把一串銅錢撈進懷裡，動作熟練得不像第一次。",
    ],
    "caught_stealing": [
        "「抓賊啊！」{victim}一把扣住了{thief}的手腕，銅錢叮叮噹噹撒了一地。",
        "{thief}的手才剛碰到錢袋，就被{victim}當場逮住，四周的人全圍了過來。",
    ],
    "debt_warning": [
        "{collector}慢吞吞地走到{debtor}身邊，壓低聲音說了幾句。{debtor}的臉色一下子白了。",
    ],
    "debt_threat": [
        "{collector}一把揪住{debtor}的衣領，聲音大到半條街都聽得見：「錢三爺的錢，你打算拖到什麼時候？」",
    ],
    "debt_beating": [
        "{attacker}一拳砸在{victim}的臉上，又補了兩腳。「這是利息。本金，下次再來拿。」",
    ],
    "fight": [
        "{attacker}和{victim}不知道為了什麼吵起來，三兩句話就動了手，桌椅翻了一地。",
        "{attacker}突然掄起拳頭朝{victim}揮過去，旁邊的人尖叫著閃開。",
    ],
    "arrest": [
        "{guard}帶著鐵尺走過來，二話不說把{suspect}的胳膊反扭到背後：「跟我回巡檢所一趟。」",
    ],
    "help_money": [
        "{giver}把一個小布包塞進{receiver}手裡，低聲說了句什麼。{receiver}愣了一下，眼眶紅了。",
    ],
    "medicine": ["{giver}把一包藥小心地放在{receiver}床頭。"],
    "gamble_loss": ["{who}盯著碗裡的骰子，臉色一點一點灰下去。又輸了。"],
    "gamble_win": ["{who}一拍桌子跳起來：「開！開！老子贏了！」"],
    "fled": ["{who}揹著一個小包袱，頭也不回地走了。"],
    "arrival": ["一個你沒見過的人走進來，四處打量——{who}，看樣子是{role}。"],
    "death": ["{who}的屋子裡傳出壓抑的哭聲。人，走了。"],
    "property_seized": ["{lender}的人搬來一塊新招牌，把{property}原來的掛了下來。{debtor}站在一旁，一句話也沒說。"],
    "release": ["{who}從巡檢所的門裡走出來，瞇著眼睛看了看太陽。"],
    "trader": ["一陣騾鈴聲由遠而近——行商{trader}的貨隊進鎮了。"],
    "fire": ["濃煙從{owner}的鋪子竄出來，街坊們提著水桶跑來跑去。"],
    "rescue": ["{helper}一步跨上前，硬生生架住了{attacker}的手。"],
    "persuade": ["{helper}擋在中間說了好一陣，{attacker}終於啐了一口，悻悻地走了。"],
    "quit_job": ["{who}把圍裙往桌上一丟，頭也不回地走了出去。"],
    "fired": ["{owner}冷著臉對{who}說：「明天起不用來了。」"],
    "revenge_vow": ["{who}紅著眼睛，咬牙切齒地說：「{target}……這筆帳，我一定要算。」"],
    "evicted": ["{landlord}的管家帶著兩個家丁，把{tenant}攤子上的東西一件件搬了出來。"],
    "found_purse": ["{who}彎腰從地上撿起一個錢袋，左右看了看，飛快地塞進懷裡。"],
    "dog_bite": ["一條野狗突然竄出來，在{who}腿上狠狠咬了一口。"],
    "rent_unpaid": ["{landlord}的管家翻著帳本，對{tenant}搖了搖頭：「下次再拖，鋪子就收回來。」"],
    "hired": ["{owner}拍了拍{who}的肩膀：「明天開始來幹活吧。」"],
    "debt_paid_by": ["{payer}把一疊銅錢推到{lender}面前：「{debtor}的帳，我來結。」"],
    "loan_repaid": ["{borrower}把錢一枚枚數清楚，推到{lender}面前，總算鬆了口氣。"],
}

# 遠處聽到的動靜（玩家不在場，但在相鄰地點或事件很大）
DISTANT = {
    "fight": "不遠處傳來一陣叫罵和桌椅翻倒的聲音。",
    "debt_beating": "巷子那頭傳來幾聲悶響和壓抑的哀叫。",
    "debt_threat": "街上有人在大聲嚷嚷，好像是在討債。",
    "arrest": "遠處有人喊：「捕頭抓人了！」",
    "fire": "空氣裡飄來一股焦味，有人喊著「走水了」。",
    "caught_stealing": "遠遠聽見一聲「抓賊啊」，接著一陣騷動。",
    "death": "窄巷那邊隱約傳來哭聲。",
}

# ---------------- 外表看得出來的狀態（不洩漏內部數值） ----------------
def demeanor(w, n: dict) -> str:
    cues = []
    if n["status"] == "jailed":
        return "關在拘房的木柵後面"
    if n.get("bedridden") or n["condition"] == "ill":
        cues.append("臉色蠟黃，像是病著")
    elif n["health"] < 45:
        cues.append("身上帶著傷")
    elif n["health"] < 75:
        cues.append("臉上有些淤青")
    if n.get("grief_until", 0) >= w.day:
        cues.append("一身素服，眼睛紅腫")
    if n.get("drunk_until", -1) >= w.clock:
        cues.append("滿身酒氣")
    if n["stress"] >= 80:
        cues.append("神色焦躁，坐立不安")
    elif n["stress"] >= 60:
        cues.append("看起來心事重重")
    elif n["stress"] <= 15 and not cues:
        cues.append("神情輕鬆")
    if not n.get("employed", True):
        cues.append("看起來無所事事")
    return "，".join(cues[:2]) if cues else "看不出什麼異樣"


def attitude_word(op: int) -> str:
    if op >= 70:
        return "把你當自己人"
    if op >= 40:
        return "對你頗有好感"
    if op >= 15:
        return "對你還算客氣"
    if op > -15:
        return "跟你不太熟"
    if op > -40:
        return "對你有些戒心"
    if op > -70:
        return "對你頗為不滿"
    return "對你恨之入骨"


def health_word(h: int) -> str:
    if h >= 90:
        return "精神飽滿"
    if h >= 70:
        return "還算硬朗"
    if h >= 45:
        return "有些虛弱"
    if h >= 20:
        return "傷痕累累"
    return "搖搖欲墜"


# ---------------- 算命：用真的秘密，說得似是而非 ----------------
FORTUNE = {
    "loan": "你身邊有個人，肩上背著一筆不該背的債，日子一天比一天近。",
    "secret_support": "有人在暗處替別人撐著一把傘，被撐傘的人卻不知道。",
    "smuggling": "水上有船，夜裡比白天忙。",
    "secret_love": "有一顆心偷偷繫在別人身上，繫了很久了。",
    "petty_theft_past": "這鎮上有一雙手，不太老實。",
    "hidden_savings": "最窮的地方，未必最窮。",
    "grudge": "兩個人之間有一筆舊帳，總有一天要算。",
    "guard_gambles": "掌管公道的人，夜裡也有自己的賭局。",
    "theft": "丟了的東西，未必在你以為的人手上。",
    "default": "你的命裡有貴人，也有小人，只是你現在還分不清誰是誰。",
}

MISCHIEF_NOTICE = [
    "風向忽然變了一下，像是有誰在暗處撥動了一根看不見的線。",
    "土地廟的長明燈無緣無故跳了一下。",
    "你心裡沒來由地一動，好像有什麼事情，悄悄偏了方向。",
    "天邊的雲走得特別快。",
]

OUTSIDE_NEWS = [
    "外頭傳說北邊的官道上鬧了山賊，好幾支商隊都繞路走了",
    "聽說府城的米價又漲了，一斗米要多出十幾文",
    "上游的堤壩前些日子差點決口，好多人家連夜往高處搬",
    "府城有個大戶人家在招護院，說是給的工錢很高",
    "聽說隔壁縣的捕頭因為收黑錢被摘了帽子",
    "南邊的藥材今年收成不好，價錢翻了一倍",
    "有人在河下游撈起一隻刻著字的木箱，誰也看不懂上面寫的什麼",
]

NEED_TEXT = {
    "medicine": "急需一筆錢給家裡的病人買藥",
    "rent": "這七天的租錢還沒著落",
    "debt": "欠錢三爺的債快到期了，還不出來",
    "food": "已經好幾天沒吃上一頓飽飯",
    "tuition": "武館的學費交不出來",
    "stake": "在賭坊輸光了，正想找門路翻本",
}

PERIOD_OPENERS = [
    "時辰往前挪了一格。",
]

DAY_OPENERS = [
    "天亮了。雞叫了三遍，青石鎮慢慢醒過來。",
    "新的一天。晨霧還沒散，街上已經有人在走動。",
    "天剛濛濛亮，遠處傳來第一聲叫賣。",
]

GUARDED = ["「我？老樣子。」", "「還過得去。」", "「問這做什麼？」", "「好得很，多謝。」", "「……沒什麼好說的。」"]

SMALL_NEWS = [
    "「聽說最近米價又要漲了。」",
    "「這兩天夜裡風大，你注意門窗。」",
    "「前幾天有隻野狗在市集咬傷了人，到現在還沒抓到。」",
    "「河水漲了一點，船家都在說今年雨水多。」",
    "「府城那邊好像有什麼大官要下來巡視，也不知真假。」",
]

IMPRESSION = {
    "warm": ["「{t}啊，是個好人，鎮上誰不知道。」", "「{t}？我們熟得很，人不錯。」", "「{t}這個人，靠得住。」"],
    "neutral": ["「{t}？就是那個{role}嘛，沒什麼交情。」", "「{t}啊……點頭之交，不太清楚。」", "「{t}？見過幾面，人怎麼樣就不知道了。」"],
    "cold": ["「{t}？哼，少跟那種人來往。」", "「別跟我提{t}。」", "「{t}那傢伙，我看不順眼很久了。」"],
}

# ---------------- 寒暄的場景與反應（跨角色共用：不寫代名詞） ----------------
PLACE_FRAME = {
    "tavern": (["隔著吧台", "在酒桌邊坐下來"], ["在划拳聲裡湊近了", "就著昏黃的油燈"]),
    "market": (["在攤子前", "站在人來人往的攤位邊"], ["在收了攤的空木架旁"]),
    "street": (["在街邊的屋簷下", "沿著青石板並肩走了一段"], ["在一盞燈籠底下"]),
    "inn": (["在大堂的方桌邊", "倚著櫃檯"], ["在只點了一盞燈的大堂裡"]),
    "gate": (["在城門洞的陰涼裡", "在告示牌下"], ["在城門洞的風燈下"]),
    "dojo": (["在院子的木樁旁", "在兵器架邊"], ["在廂房透出的燈光裡"]),
    "pharmacy": (["在一整面藥櫃前", "在滿屋子的藥味裡"], ["在上了門板的藥鋪裡"]),
    "yamen": (["在巡檢所門口", "在那面蒙灰的大鼓旁"], ["在巡檢所昏暗的燈籠下"]),
    "alley": (["在窄巷的屋簷下", "在矮房門口"], ["在窄巷的黑暗裡"]),
    "temple": (["在廟簷下", "在供桌旁"], ["就著長明燈的微光"]),
    "den": (["在煙霧繚繞的賭桌邊"], ["在嘩啦作響的骰子聲裡", "在煙霧繚繞的賭桌邊"]),
    "dock": (["在河邊的石階上", "在堆著麻包的碼頭邊"], ["在拍岸的水聲裡"]),
    "mansion": (["在朱漆大門前", "在門房的注視下"], ["在大宅高牆的陰影裡"]),
}

CHAT_REACTION = {
    "warm": ["{n}說得興起，話匣子一開就關不上。", "{n}笑了起來，說話也隨意多了。", "聊著聊著，{n}的話越來越多。"],
    "neutral": ["{n}應了幾句，神情鬆了些。", "{n}聽著，偶爾接一兩句。", "{n}話不多，倒也沒有要走的意思。"],
    "cold": ["{n}愛理不理，敷衍了兩句。", "{n}的回應冷冷淡淡的。"],
    "stressed": ["{n}心不在焉，眼神不時飄向別處。", "{n}說著說著就停下來，像是想起了別的事。"],
    "bedridden": ["{n}靠在床頭，聽得很專心。", "{n}說幾句就要喘一下，臉上倒是有了點笑意。", "{n}握著被角，慢慢地說，慢慢地笑。"],
    "jailed": ["{n}隔著木柵，聲音壓得很低。", "{n}靠在牆角，有一句沒一句地答著。"],
}

LOCAL_NEWS = {
    "market": ["「今天的菜價又漲了，這日子怎麼過。」", "「東頭賣豆腐的說，他家老母豬下了十二隻小豬。」", "「聽說有人在市集撿到一隻金耳環，到現在沒人認領。」"],
    "dock": ["「河水這兩天漲了，上游怕是下了大雨。」", "「下游來的船說，碼頭那邊在招人扛貨。」", "「前天有條船擱淺了，搬了一整夜才弄下來。」"],
    "tavern": ["「昨晚有個客人喝醉了，抱著柱子喊娘。」", "「新來的那批酒，聽說是從南邊運來的。」", "「角落那桌天天來，天天賒帳。」"],
    "temple": ["「這陣子來上香的人少了，菩薩也寂寞。」", "「前幾天有人在廟裡求了支下下籤，臉都白了。」"],
    "gate": ["「這兩天進城的騾隊少了，聽說北邊的路不好走。」", "「昨天有個挑擔子的，說是從府城一路走來的。」"],
    "inn": ["「樓上住了個怪人，三天沒下樓了。」", "「這陣子投宿的客人不多，淡季。」"],
    "den": ["「昨晚有人一把押上全副身家，結果你猜怎麼著？」", "「莊家換了新骰子，有人說手氣變了。」"],
    "dock_night": [],
}
