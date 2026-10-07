"""真模型測試的環境：連哪個 Ollama、哪個模型；連不上或沒有模型時，給一個清楚的「不可用」原因（測試會 SKIP，不算失敗）。"""

from __future__ import annotations

import json
import os
import urllib.request


def settings() -> dict:
    from rpg.config import load_dotenv

    load_dotenv()
    return {
        "url": os.environ.get("RPG_OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        "model": os.environ.get("RPG_MODEL", "qwen3.5:9b"),
        "timeout": float(os.environ.get("RPG_LLM_TIMEOUT", "180")),
    }


def availability(url: str | None = None, model: str | None = None) -> tuple[bool, str]:
    s = settings()
    url = (url or s["url"]).rstrip("/")
    model = model or s["model"]
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, f"Ollama is not reachable at {url} ({type(e).__name__}: {e})"
    names = [m.get("name", "") for m in tags.get("models", [])]
    if model not in names and f"{model}:latest" not in names:
        return False, f"model '{model}' is not installed at {url} (installed: {', '.join(names) or 'none'}); run: ollama pull {model}"
    try:
        with urllib.request.urlopen(f"{url}/api/version", timeout=3) as r:
            version = json.loads(r.read().decode("utf-8")).get("version", "?")
    except Exception:
        version = "?"
    return True, f"{model} @ {url} (Ollama {version})"
