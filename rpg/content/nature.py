"""世界的物質真實與「怎麼理解它」的資料表（靜態定義）。

這裡分成三種東西，刻意分開：
- KINDS：世界裡真正存在的東西是什麼（上帝視角）。只有世界模擬器讀 kind；角色永遠只拿得到 traits 的一部分。
- TRAITS：東西客觀的性質，以及「要用哪種感官、多敏銳才察覺得到」。
- CONCEPTS：角色腦中的概念。概念用「性質的樣子」來辨認東西，不看 kind——所以同一個東西，
  懂醫的人看成結石、練內功的看成內丹、修道的看成金丹、什麼都不懂的人只覺得「肚子裡有個硬塊」。

規則（act.py）只看 traits 算結果，不看 kind 名字：沒有任何「如果是金丹就……」的寫法。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 感官
# 每個角色有一組感官深度（0＝沒有）。一般人：看 1、摸 1、聽 1。
SENSES = {
    "sight": "看",
    "touch": "觸診",       # 2 以上摸得出皮下、體內的團塊；3 摸得出硬度大小
    "listen": "聽",        # 2 以上聽得出敲擊時的共鳴
    "qi": "氣感",          # 感覺得到體內流動的氣、東西蘊藏的能量
    "spirit": "靈視",      # 看得見一般人看不見的東西
    "smell": "嗅",
    "structure": "看結構",  # 看得出受力、材料、會從哪裡塌
    "appraise": "估量",     # 看得出一個人大概多有錢
}
DEFAULT_SENSES = {"sight": 1, "touch": 1, "listen": 1}

# 性質要用什麼感官、多深才察覺得到。internal＝東西在身體裡面時，用 sight 看不到。
# experiment＝只有在受到某種作用時才顯露（例如共鳴只在被震動、被敲時聽得出來）。
TRAITS = {
    "form": {"sense": [("sight", 1), ("touch", 2)], "internal_senses": [("touch", 2), ("qi", 2), ("spirit", 1)]},
    "region": {"sense": [("sight", 1), ("touch", 2)], "internal_senses": [("touch", 2), ("qi", 1), ("spirit", 1)]},
    "size": {"sense": [("sight", 1), ("touch", 2)], "internal_senses": [("touch", 3), ("qi", 2), ("spirit", 1)]},
    "hardness": {"sense": [("touch", 1)], "internal_senses": [("touch", 3)]},
    "warmth": {"sense": [("touch", 1)], "internal_senses": [("touch", 2), ("qi", 1)]},
    "energy": {"sense": [("qi", 1), ("spirit", 1)], "internal_senses": [("qi", 1), ("spirit", 1)]},
    "resonant": {"sense": [("listen", 2)], "internal_senses": [("listen", 2)], "experiment": True},
    "material": {"sense": [("sight", 1), ("touch", 1)], "internal_senses": [("spirit", 2)]},
    "edge": {"sense": [("sight", 1)], "internal_senses": []},
    "smell": {"sense": [("smell", 1)], "internal_senses": [("smell", 2)]},
}

# 不認得時，用性質描述（任何人都說得出口的話）
DESCRIBE = {
    "form": {"mass": "團塊", "core": "圓滾滾的硬核", "lesion": "病灶", "growth": "增生的軟塊", "object": "東西",
             "trace": "說不清的痕跡", "shard": "碎片"},
    "size": {"tiny": "極小的", "small": "小小的", "large": "很大的", "huge": "大得出奇的"},
    "hardness": [(7, "非常堅硬"), (4, "硬"), (0, "軟")],
    "warmth": {"hot": "發燙", "warm": "溫熱", "cold": "冰涼"},
    "energy": [(7, "蘊藏著驚人的氣"), (3, "隱隱有氣在流動"), (1, "帶著一絲說不出的勁")],
    "resonant": {True: "一受震就嗡嗡共鳴"},
    "material": {"stone": "像石頭", "metal": "是金屬做的", "flesh": "像是肉長出來的"},
}

REGIONS = {
    "lower_abdomen": {"default": "下腹", "medicine_modern": "下腹部（膀胱附近）", "medicine_trad": "小腹",
                      "neigong": "丹田", "cultivation": "丹田"},
    "flank": {"default": "腰側", "medicine_modern": "腰側（腎臟附近）", "medicine_trad": "腰間"},
    "chest": {"default": "胸口", "medicine_modern": "胸腔", "medicine_trad": "肺經一帶"},
    "throat": {"default": "喉嚨"},
    "limb": {"default": "四肢"},
    "whole": {"default": "全身", "neigong": "經脈之中", "cultivation": "經脈之中"},
}

# ---------------------------------------------------------------- 世界裡真正存在的東西（上帝視角）
# traits：客觀性質。internal：在身體裡。vital：跟宿主的什麼連在一起（power＝功力、life＝性命）。
# cause：它會造成什麼症狀（毀掉它，症狀就失去來源）。tool：當工具用時提供哪種作用、多強。
KINDS = {
    "core_dense": {"traits": {"form": "core", "region": "lower_abdomen", "size": "large", "hardness": 8, "warmth": "warm",
                              "energy": 9, "resonant": True, "material": "unknown"},
                   "internal": True, "vital": "power", "volatile": 6, "brittle": False},
    "core_faint": {"traits": {"form": "core", "region": "lower_abdomen", "size": "small", "hardness": 2, "warmth": "warm",
                              "energy": 4, "resonant": False},
                   "internal": True, "vital": "power", "volatile": 2, "brittle": False},
    "calculus": {"traits": {"form": "mass", "region": "flank", "size": "small", "hardness": 6, "resonant": True,
                            "material": "stone"},
                 "internal": True, "cause": "colic", "volatile": 0, "brittle": True},
    "inflamed": {"traits": {"form": "lesion", "region": "chest", "hardness": 1, "warmth": "hot", "smell": "腐氣"},
                 "internal": True, "cause": "fever", "volatile": 0, "brittle": False, "transient": True},
    "consumptive": {"traits": {"form": "lesion", "region": "chest", "hardness": 2, "warmth": "warm"},
                    "internal": True, "cause": "consumption", "volatile": 0, "brittle": False},
    "growth": {"traits": {"form": "growth", "region": "lower_abdomen", "size": "small", "hardness": 4, "material": "flesh"},
               "internal": True, "cause": "wasting", "vital": "life", "volatile": 0, "brittle": False},
    "lineage": {"traits": {"form": "trace", "region": "whole", "warmth": "hot", "energy": 5},
                "internal": True, "volatile": 1, "brittle": False, "durable": True},
    "seedling": {"traits": {"form": "core", "region": "lower_abdomen", "size": "tiny", "hardness": 5, "energy": 3},
                 "internal": True, "volatile": 3, "brittle": False},
    "foreign_needle": {"traits": {"form": "object", "region": "limb", "size": "tiny", "hardness": 7, "material": "metal"},
                       "internal": True, "volatile": 0, "brittle": False},
    "blade": {"traits": {"form": "object", "size": "small", "hardness": 7, "material": "metal", "edge": True},
              "internal": False, "tool": {"cut": 4}, "volatile": 0, "brittle": False},
    "blade_odd": {"traits": {"form": "object", "size": "small", "hardness": 9, "material": "metal", "edge": True,
                             "energy": 4},
                  "internal": False, "tool": {"cut": 5}, "volatile": 1, "brittle": False},
    "trinket": {"traits": {"form": "object", "size": "small", "hardness": 5}, "internal": False, "volatile": 0,
                "brittle": False},
}

# 症狀：體內的東西造成什麼病（症狀是看得到的；成因要診察才知道）
CAUSES = {
    "colic": {"label": "陣陣絞痛", "flare_pct": 8, "hurt": 12},
    "fever": {"label": "高燒不退", "flare_pct": 0, "hurt": 0},
    "consumption": {"label": "咳嗽不止", "flare_pct": 0, "hurt": 0},
    "wasting": {"label": "日漸消瘦", "flare_pct": 3, "hurt": 6},
}

# ---------------------------------------------------------------- 角色腦中的概念
# pattern：辨認條件。needs：這些性質一定要「察覺到」才可能下這個判斷（例如沒有氣感的人，永遠不會判斷出蘊藏真氣的東西）。
# 判斷只看察覺到的性質，所以同一個東西會被不同的人看成不同的東西。
CONCEPTS = {
    # 一般人
    "lump": {"label": "體內的硬塊", "domain": "common", "pattern": {"form": ["mass", "core", "growth"], "internal": True},
             "weight": 0.5},
    # 傳統醫術
    "stone_trad": {"label": "石淋（體內的結石）", "domain": "medicine_trad",
                   "pattern": {"form": ["mass", "core"], "hardness": (">=", 5), "internal": True,
                               "region": ["flank", "lower_abdomen"], "energy": ("<=", 1)}, "needs": ["hardness"]},
    "lump_trad": {"label": "癥瘕（腹中的積塊）", "domain": "medicine_trad",
                  "pattern": {"form": ["mass", "growth", "core"], "hardness": ("<=", 5), "internal": True},
                  "needs": ["hardness"]},
    "lung_heat": {"label": "肺熱之症", "domain": "medicine_trad",
                  "pattern": {"form": ["lesion"], "region": ["chest"], "warmth": ["hot"]}, "needs": ["warmth"]},
    "consumption_trad": {"label": "癆病", "domain": "medicine_trad",
                         "pattern": {"form": ["lesion"], "region": ["chest"], "warmth": ["warm"]}, "needs": ["warmth"]},
    # 現代醫學（只會從天賦來）
    "calculus_modern": {"label": "結石", "domain": "medicine_modern",
                        "pattern": {"form": ["mass", "core"], "hardness": (">=", 5), "internal": True, "energy": ("<=", 1)},
                        "needs": ["hardness"]},
    "tumor_modern": {"label": "腫瘤", "domain": "medicine_modern",
                     "pattern": {"form": ["growth", "mass"], "hardness": ("<=", 5), "internal": True}, "needs": ["hardness"]},
    "infection_modern": {"label": "發炎的感染灶", "domain": "medicine_modern",
                         "pattern": {"form": ["lesion"], "warmth": ["hot", "warm"]}, "needs": ["warmth"]},
    "foreign_body": {"label": "體內異物", "domain": "medicine_modern",
                     "pattern": {"form": ["object"], "material": ["metal"], "internal": True}, "needs": ["material"]},
    # 聲學／物理
    "resonator": {"label": "會共振的硬物", "domain": "acoustics",
                  "pattern": {"hardness": (">=", 5), "resonant": [True]}, "needs": ["resonant"]},
    "energy_core": {"label": "某種高能量的核心", "domain": "physics",
                    "pattern": {"form": ["core"], "energy": (">=", 6)}, "needs": ["energy"]},
    "machine_part": {"label": "某種機件", "domain": "engineering", "pattern": {"form": ["object"], "material": ["metal"]},
                     "needs": ["material"]},
    # 內功
    "qi_knot": {"label": "內丹（練出來的氣團）", "domain": "neigong",
                "pattern": {"form": ["core"], "region": ["lower_abdomen"], "energy": (">=", 2)}, "needs": ["energy"]},
    # 修道
    "golden_core": {"label": "金丹", "domain": "cultivation",
                    "pattern": {"form": ["core"], "region": ["lower_abdomen"], "energy": (">=", 7)}, "needs": ["energy"]},
    "spirit_seed": {"label": "未成形的道種", "domain": "cultivation",
                    "pattern": {"form": ["core"], "energy": ("<=", 4)}, "needs": ["energy"]},
    "bloodline_trace": {"label": "異族血脈的氣息", "domain": "cultivation",
                        "pattern": {"form": ["trace"], "energy": (">=", 3)}, "needs": ["energy"]},
    # 江湖術士的說法
    "evil_object": {"label": "邪術留下的異物", "domain": "mystic",
                    "pattern": {"form": ["core", "mass", "trace", "object"], "warmth": ["hot", "warm", "cold"]},
                    "weight": 0.8},
    # 讀書人從書上看來的
    "legend_core": {"label": "書上說的「金丹」", "domain": "lore",
                    "pattern": {"form": ["core"], "region": ["lower_abdomen"], "energy": (">=", 6)}, "needs": ["energy"],
                    "weight": 0.7},
    # 器物
    "blade_concept": {"label": "刀刃", "domain": "common", "pattern": {"form": ["object"], "edge": [True]}, "needs": ["edge"]},
    "trinket_concept": {"label": "小物件", "domain": "common", "pattern": {"form": ["object"], "internal": False},
                        "weight": 0.4},
}

# 同一個「真實概念」在不同知識體系裡的名字（被人告知名字時，用來接上自己的理解）
SAME_THING = [
    {"golden_core", "legend_core", "energy_core"},
    {"stone_trad", "calculus_modern"},
    {"lump_trad", "tumor_modern"},
    {"lung_heat", "infection_modern"},
]

# ---------------------------------------------------------------- 作用方式（modality）
MODALITIES = {
    "vibration": {"default": "一陣奇怪的震動", "acoustics": "聚焦的聲波", "medicine_modern": "震波",
                  "cultivation": "某種特殊的術法", "neigong": "一種古怪的內勁", "mystic": "邪術"},
    "blunt": {"default": "拳腳"},
    "cut": {"default": "利刃"},
    "heat": {"default": "灼熱", "cultivation": "火屬的術法", "mystic": "邪火"},
    "cold": {"default": "寒氣"},
    "chemical": {"default": "藥物", "medicine_modern": "藥劑", "mystic": "下咒"},
    "qi": {"default": "一股說不出的勁道", "neigong": "內力", "cultivation": "真氣"},
    "care": {"default": "推拿診治", "medicine_trad": "施治", "medicine_modern": "治療"},
    "craft": {"default": "手藝"},
}

# ---------------------------------------------------------------- 固定技能池（保留給玩家穩定、好懂的角色基礎）
# 技能的主要內容是「知識（domains）、會注意什麼（senses）、會怎麼做（practices）」，等級只是附帶。
SKILLS = {
    "medicine": {"name": "醫術", "desc": "望聞問切，懂人體與常見病症，摸得出病人身上不對勁的地方。",
                 "domains": ["medicine_trad"], "senses": {"touch": 3, "smell": 1},
                 "practices": [{"modality": "care", "magnitude": 4, "precision": 6, "reach": "touch", "label": "診治"}]},
    "herbal": {"name": "草藥學", "desc": "認得百草，知道什麼能救命、什麼會要命。",
               "domains": ["herbal", "medicine_trad"], "senses": {"smell": 2},
               "practices": [{"modality": "chemical", "magnitude": 4, "precision": 5, "reach": "touch", "label": "用藥"}]},
    "sword": {"name": "劍術", "desc": "練過劍，知道刃該往哪裡走。手上有兵器才使得出來。",
              "domains": ["martial"], "senses": {"sight": 2}, "prowess": 0.8,
              "practices": [{"modality": "cut", "magnitude": 5, "precision": 6, "reach": "near", "label": "劍招",
                             "needs_tool": "cut"}]},
    "fist": {"name": "拳腳", "desc": "拳腳功夫，打架不吃虧。", "domains": ["martial"], "prowess": 1.5,
             "practices": [{"modality": "blunt", "magnitude": 5, "precision": 4, "reach": "touch", "label": "拳腳"}]},
    "engineering": {"name": "工程", "desc": "看得懂結構與機件，知道東西怎麼受力、會從哪裡壞。",
                    "domains": ["engineering", "physics"], "senses": {"structure": 2, "listen": 2},
                    "practices": [{"modality": "craft", "magnitude": 4, "precision": 6, "reach": "touch", "label": "修造"}]},
    "trade": {"name": "商業", "desc": "會算帳、會看貨，一眼看得出誰手頭寬裕。", "domains": ["trade"], "senses": {"appraise": 2},
              "practices": []},
    "letters": {"name": "讀書識字", "desc": "讀過不少書，雜學旁收，連志怪傳奇也看過一些。", "domains": ["lore"],
                "senses": {}, "practices": []},
    "neigong": {"name": "內功", "desc": "練過吐納，體內有一點氣，也感覺得到別人身上的氣。", "domains": ["neigong"],
                "senses": {"qi": 1}, "prowess": 0.5,
                "practices": [{"modality": "qi", "magnitude": 3, "precision": 4, "reach": "touch", "label": "運勁"}]},
}
MAX_SKILLS = 2

# 出身本身也帶著見識（原本的出身系統保留）
BACKGROUND_DOMAINS = {"herbalist": ["herbal", "medicine_trad"], "scholar": ["lore"], "peddler": ["trade"],
                      "escort": ["martial"], "heir": ["trade"], "drifter": []}
BACKGROUND_SENSES = {"herbalist": {"touch": 2, "smell": 1}, "peddler": {"appraise": 1}}

# 鎮民的見識（依 voice_key；外來者依身分）
NPC_DOMAINS = {
    "bai": (["medicine_trad", "herbal"], {"touch": 3, "smell": 2}),
    "tie": (["neigong", "martial"], {"qi": 2}),
    "shitou": (["martial"], {}),
    "banxian": (["mystic", "lore"], {}),
    "zhou": (["lore"], {}),
    "chenbo": (["trade"], {"appraise": 2}),
    "sun": (["trade"], {"appraise": 2}),
    "qian": (["trade"], {"appraise": 3}),
    "feng": (["trade"], {"appraise": 2}),
    "hu": (["trade", "herbal"], {"appraise": 2, "smell": 1}),
    "liu6": ([], {"appraise": 1}),
    "zhang": ([], {"listen": 2}),
}

# 一開始就帶在身上的東西（世界真實）。依 voice_key。
NPC_THINGS = {"tie": ["core_faint"], "linshen": ["consumptive"]}
# 有些鎮民身上可能帶著舊疾（每個世界抽一次，見 world.new_world）
CHRONIC_POOL = [("calculus", ["chenbo", "wang", "sun", "laohe", "feng"])]
# 外來者的見識與身上的東西（依身分）
DRIFTER_NATURE = {
    "雲遊的修道人": (["cultivation", "neigong", "lore"], {"qi": 3, "spirit": 1}, ["core_dense"]),
    "跑江湖的賣藝人": (["neigong", "martial"], {"qi": 1}, []),
    "找活幹的木匠": (["engineering"], {"structure": 2}, []),
    "逃荒的農人": ([], {}, []),
    "來投親的姑娘": ([], {}, []),
    "來路不明的漢子": (["martial"], {}, []),
}

# ---------------------------------------------------------------- 自訂天賦：把自由文字拆成「主張」的詞表
# 這不是在限制玩家能寫什麼：認不出的部分一樣保留成主張，只是世界要到它真的被用上時才決定它代表什麼。
FACET_CUES = [
    ("item", ["帶著", "帶了", "一把", "一柄", "一塊", "一枚", "一本", "隨身", "陪伴我"]),
    ("perception", ["看得見", "看見", "看到", "聽得見", "聞得到", "感覺得到", "感應"]),
    ("bloodline", ["血統", "血脈", "後裔", "族人"]),
    ("disposition", ["不信任", "多疑", "膽小", "膽大", "性格", "脾氣", "冷靜"]),
    ("state", ["體內", "吃了", "中了", "被詛咒", "變化", "不知道是什麼"]),
    ("rule", ["永遠不會", "從來不會", "絕對不會", "一定會", "總是"]),
    ("body", ["體質", "身體", "天生", "力大", "皮膚", "骨骼"]),
    ("identity", ["王族", "皇族", "貴族", "王子", "公主", "身份", "轉生前是"]),
    ("memory", ["記憶", "記得", "保留"]),
    ("ability", ["能夠", "可以", "會", "擅長", "能"]),
    ("profession", ["醫生", "醫師", "大夫", "工程師", "學家", "教授", "研究", "專門", "職業", "是一名", "是個", "前世是"]),
    ("experience", ["曾經", "做過", "工作", "年", "經歷", "待過"]),
]
DOMAIN_CUES = [
    ("medicine_modern", ["醫生", "醫師", "外科", "內科", "泌尿", "手術", "醫院", "護理", "急診", "現代醫"]),
    ("acoustics", ["超聲波", "超音波", "聲波", "震波", "碎石", "共振", "頻率"]),
    ("physics", ["物理", "核融合", "核子", "能量", "電", "磁"]),
    ("engineering", ["工程", "機械", "結構", "建築", "設計"]),
    ("cultivation", ["修仙", "修真", "修士", "金丹", "靈根", "仙"]),
    ("neigong", ["內功", "內力", "武功", "練武", "武林", "吐納"]),
    ("mystic", ["咒", "符", "邪", "鬼", "妖"]),
    ("herbal", ["草藥", "藥草", "毒"]),
    ("trade", ["商", "生意", "帳"]),
    ("lore", ["讀書", "書", "學者", "歷史"]),
    ("martial", ["戰場", "士兵", "軍", "格鬥", "拳"]),
]
MODALITY_CUES = [
    ("vibration", ["震", "超聲", "超音", "聲波", "共振"]),
    ("heat", ["火", "燒", "熱", "焰"]),
    ("cold", ["冰", "寒", "凍"]),
    ("cut", ["刀", "劍", "割", "切", "斬"]),
    ("chemical", ["毒", "藥"]),
    ("qi", ["氣", "內力", "真氣"]),
    ("blunt", ["拳", "打", "揍", "踢", "力"]),
]
MAGNITUDE_CUES = [(10, ["任何", "一切", "所有", "無限", "無敵", "最強", "毀天滅地"]), (7, ["非常", "極", "超強", "強大", "驚人"])]
