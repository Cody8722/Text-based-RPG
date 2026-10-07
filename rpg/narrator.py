"""說書人：把已經確定的結果講得更生動。可選，沒有 LLM 時遊戲照常可玩。

邊界（吸收 docs/reviews/ 的教訓）：
- LLM 只拿到「這一回合已經發生、玩家看得到」的片段（beats），沒有任何隱藏狀態。
- LLM 的輸出只用來顯示，永遠不會寫回 world、不會變成事實、不會進記憶。
- 輸出先過白盒驗證：數字不能憑空出現、片段裡的人名一個都不能少、不能冒出片段裡沒有的鎮民、
  長度要合理、控制字元一律清掉。任何一項不過就用模板原文。
- 失敗（連不上、逾時、亂碼）只會讓這一段改用模板，不影響任何遊戲結果。
- 台詞（「」裡的話）是規則選出來的，說書人一字不改照抄；只有台詞、沒有動作或場景的回合不送給說書人。
- 不給 NPC 的人物設定：那是給設計者看的內心描寫，說書人會把它講出來（等於劇透），也會讓每回合都重新介紹一次人物。
- 場景只給地名與時辰天氣；完整的地點描寫只在「剛走進來」那一回合的片段裡出現一次。
- 依 CLAUDE.md 的實測結論：qwen3.5 一律 think:false + num_ctx:8192；提示用描述句，不用「不要…」這種否定命令。
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from .content.locations import LOCATIONS, PERIODS
from .content.npcs import NPCS

REWRITE_KINDS = {"action", "speech", "witness", "arrive", "overheard", "approach", "player_say"}
DIALOGUE_KINDS = {"speech", "player_say"}
_QUOTE = re.compile(r"「([^「」]+)」")
_PUNCT = re.compile(r"[\s，。！？、；：…—「」『』,.!?;:]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏ -‮]")
_DIGITS = re.compile(r"\d+")


def parse_json_object(content: str) -> dict:
    start = content.index("{")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(content[start:i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("not an object")
                return obj
    raise ValueError("no complete JSON object")


def all_names() -> dict[str, str]:
    """所有核心鎮民的稱呼／別名 → id（用來偵測 LLM 憑空拉人進場）。"""
    out = {}
    for nid, spec in NPCS.items():
        for a in [spec["call"], spec["name"], *spec.get("aliases", [])]:
            if len(a) >= 2:
                out[a] = nid
    return out


NAME_INDEX = all_names()


def validate(output: str, template: str, required_names: list[str]) -> str | None:
    """通過回傳清理後文字，不通過回傳 None。"""
    if not isinstance(output, str):
        return None
    text = _CTRL.sub("", output.replace("\r", "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text or "{" in text or "}" in text or "【" in text:
        return None
    tlen = len(template)
    if len(text) < max(15, int(tlen * 0.5)) or len(text) > tlen * 2 + 80:
        return None
    # 台詞一字不改（標點、空白不計）
    flat = _PUNCT.sub("", text)
    for q in _QUOTE.findall(template):
        if _PUNCT.sub("", q) not in flat:
            return None
    allowed_digits = set(_DIGITS.findall(template))
    if any(d not in allowed_digits for d in _DIGITS.findall(text)):
        return None
    for name in required_names:
        if name not in text:
            return None
    present_ids = {NAME_INDEX[n] for n in required_names if n in NAME_INDEX}
    for alias, nid in NAME_INDEX.items():
        if alias in text and nid not in present_ids and alias not in template:
            return None
    return text


class Narrator:
    def __init__(self, mode: str | None = None, url: str | None = None, model: str | None = None, timeout: float = 60):
        self.mode = (mode or os.environ.get("RPG_LLM", "auto")).lower()
        self.url = (url or os.environ.get("RPG_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("RPG_MODEL", "qwen3.5:9b")
        self.timeout = timeout
        self.enabled = False
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.stats = {"ok": 0, "fallback": 0, "error": 0}
        if self.mode in ("auto", "ollama"):
            self.enabled = self.probe()

    # ---------- 連線 ----------
    def probe(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=1.5) as r:
                tags = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in tags.get("models", [])]
            return any(n == self.model or n.startswith(self.model.split(":")[0]) for n in names)
        except Exception:
            return False

    def call(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "think": False,
            "format": {"type": "object", "properties": {"narrative": {"type": "string"}}, "required": ["narrative"]},
            "options": {"num_ctx": 8192, "temperature": 0.8},
            "stream": False,
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return parse_json_object(data["message"]["content"]).get("narrative")

    # ---------- 組 prompt ----------
    @staticmethod
    def build_context(w, beats: list[dict]) -> dict | None:
        rew = [b for b in beats if b["kind"] in REWRITE_KINDS]
        if not rew or all(b["kind"] in DIALOGUE_KINDS for b in rew):
            return None   # 純對話：台詞已經是定稿，照原樣顯示
        template = "\n".join(b["text"] for b in rew)
        names = [n["call"] for n in w.npcs.values() if n["call"] in template]
        loc = w.player["location"]
        here = {w.npcs[i]["call"] for i in w.present_npcs(loc)} | {b.get("speaker") and w.npcs[b["speaker"]]["call"]
                                                                 for b in rew if b.get("speaker") in w.npcs}
        on_stage = [x for x in names if x in here]
        mentioned = [x for x in names if x not in here]
        return {
            "template": template,
            "names": names,
            "scene": f"{LOCATIONS[loc]['name']}，{PERIODS[w.period]}，{w.weather}",
            "cast": "你" + ("、" + "、".join(on_stage) if on_stage else ""),
            "mentioned": "、".join(mentioned),
            "length": int(len(template) * 1.3) + 20,
        }

    @staticmethod
    def prompts(ctx: dict) -> tuple[str, str]:
        system = (
            "你是一位說書人，替一款發生在江南小鎮「青石鎮」的文字冒險遊戲，把剛剛發生的事講給玩家聽。"
            "玩家在故事裡以「你」稱呼。下面的「本段已發生的事」全都已經確定，你的工作是把它們串成一段流暢、有畫面的敘事："
            "引號「」裡的台詞逐字照抄，事件的結果、出場的人、提到的數目都照原樣保留，"
            "你補上的只有動作、神情和此刻的氣氛。"
            "這一段緊接在上一段之後，玩家已經熟悉這裡的場景和人物，敘事就從剛發生的事寫起。"
            "篇幅貼近指定的字數。全文使用繁體中文，只包含文字與標點符號。輸出一個 JSON 物件，欄位 narrative 放這段敘事。"
        )
        user = f"【場景】{ctx['scene']}\n【這一段在場的人】{ctx['cast']}\n"
        if ctx.get("mentioned"):
            user += f"【只在話裡提到、此刻不在場的人】{ctx['mentioned']}\n"
        user += f"【篇幅】約{ctx['length']}字\n【本段已發生的事】\n{ctx['template']}"
        return system, user

    # ---------- 非同步工作 ----------
    def submit(self, w, beats: list[dict]) -> str | None:
        if not self.enabled:
            return None
        ctx = self.build_context(w, beats)
        if not ctx:
            return None
        jid = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[jid] = {"status": "pending", "text": ctx["template"]}
            if len(self.jobs) > 200:
                for k in list(self.jobs)[:100]:
                    self.jobs.pop(k, None)
        self.pool.submit(self._run, jid, ctx)
        return jid

    def _run(self, jid: str, ctx: dict):
        text = ctx["template"]
        source = "template"
        try:
            system, user = self.prompts(ctx)
            out = self.call(system, user)
            ok = validate(out, ctx["template"], ctx["names"])
            if ok:
                text, source = ok, "llm"
                self.stats["ok"] += 1
            else:
                self.stats["fallback"] += 1
        except Exception:
            self.stats["error"] += 1
        with self.lock:
            self.jobs[jid] = {"status": "done", "text": text, "source": source}

    def get(self, jid: str) -> dict:
        with self.lock:
            return dict(self.jobs.get(jid) or {"status": "unknown"})
