"""本機網頁伺服器（只用 Python 標準庫）。

- 預設只綁 127.0.0.1（CLAUDE.md：網路隔離靠明確綁定，不假設防火牆兜底）。
- 前端只能送「動作 id」，伺服器驗證它在當下的動作清單裡才執行。
- RPG_DEBUG=1 時才開 /api/debug/*（會劇透，給開發者用）。
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import devtools
from .game import Game
from .player import ActionError

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_BODY = 16 * 1024


def make_handler(game: Game, debug: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "QingshiTown/1.0"

        def log_message(self, fmt, *args):  # 安靜一點
            if os.environ.get("RPG_HTTP_LOG"):
                super().log_message(fmt, *args)

        def _send(self, code: int, payload, ctype="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ActionError("請求太大")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                d = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                raise ActionError("格式錯誤")
            if not isinstance(d, dict):
                raise ActionError("格式錯誤")
            return d

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    return self._static("index.html")
                if u.path.startswith("/static/"):
                    return self._static(u.path[len("/static/"):])
                if u.path == "/api/status":
                    return self._send(200, {"has_save": game.has_save(), "llm": game.narrator.enabled,
                                            "debug": debug, "in_game": game.world is not None})
                if u.path == "/api/backgrounds":
                    return self._send(200, {"choices": game.offer()})
                if u.path == "/api/view":
                    return self._send(200, game.current())
                if u.path == "/api/narration":
                    jid = (q.get("id") or [""])[0]
                    return self._send(200, game.narrator.get(jid))
                if debug and u.path.startswith("/api/debug/"):
                    return self._debug(u.path[len("/api/debug/"):], q)
                return self._send(404, {"error": "not found"})
            except ActionError as e:
                return self._send(400, {"error": str(e)})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                body = self._json_body()
                if u.path == "/api/new":
                    seed = body.get("seed") if debug else None
                    bg = body.get("background")
                    if game.offered and bg not in game.offered:
                        raise ActionError("請從提供的出身裡選一個")
                    return self._send(200, game.new(str(bg), seed if isinstance(seed, int) else None))
                if u.path == "/api/continue":
                    return self._send(200, game.resume())
                if u.path == "/api/act":
                    aid = body.get("id")
                    text = body.get("text")
                    if not isinstance(aid, str) or len(aid) > 80:
                        raise ActionError("動作格式錯誤")
                    if text is not None and (not isinstance(text, str) or len(text) > 200):
                        raise ActionError("說的話太長了")
                    return self._send(200, game.act(aid, text))
                return self._send(404, {"error": "not found"})
            except ActionError as e:
                return self._send(400, {"error": str(e)})

        def _static(self, rel: str):
            path = os.path.normpath(os.path.join(WEB_DIR, rel))
            if os.path.commonpath([path, WEB_DIR]) != WEB_DIR or not os.path.isfile(path):
                return self._send(404, {"error": "not found"})
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            with open(path, "rb") as f:
                return self._send(200, f.read(), ctype)

        def _debug(self, what: str, q):
            w = game.world
            if w is None:
                return self._send(400, {"error": "no world"})
            if what == "summary":
                return self._send(200, {**devtools.summarize(w), "genes": w.genes, "mischief": w.mischief_log,
                                        "stats": w.stats, "narrator": game.narrator.stats})
            if what == "chronicle":
                return self._send(200, {"lines": devtools.chronicle(w)})
            if what == "chains":
                return self._send(200, {"chains": [[devtools.T.fact_text(w, w.facts[f]) for f in ch]
                                                   for ch in devtools.longest_chains(w, 8)]})
            if what == "world":
                return self._send(200, w.to_dict())
            return self._send(404, {"error": "unknown debug view"})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, game: Game | None = None,
          debug: bool | None = None) -> ThreadingHTTPServer:
    debug = bool(int(os.environ.get("RPG_DEBUG", "0"))) if debug is None else debug
    game = game or Game()
    httpd = ThreadingHTTPServer((host, port), make_handler(game, debug))
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"青石鎮已開門：{url}")
    print(f"說書人（LLM）：{'已連上 ' + game.narrator.model if game.narrator.enabled else '未啟用，使用內建敘事'}")
    if debug:
        print("除錯模式：/api/debug/summary、/api/debug/chronicle、/api/debug/chains（會劇透）")
    print("按 Ctrl+C 關閉。")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    return httpd


def main(argv=None):
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from .config import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(description="青石鎮——文字 RPG")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)
    httpd = serve(a.host, a.port, not a.no_browser, debug=a.debug or None)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n青石鎮打烊了。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
