"""設定：讀專案根目錄的 .env（選填）。已經存在的環境變數優先，不會被 .env 蓋掉。不依賴 python-dotenv。"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv(path: str | None = None) -> None:
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def save_dir() -> str:
    return os.environ.get("RPG_SAVE_DIR") or os.path.join(ROOT, "saves")
