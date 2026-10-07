"""HTTP 整合：用真的伺服器、真的 HTTP 請求玩一段。"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from support import ROOT  # noqa: F401  (sys.path)

from rpg.game import Game
from rpg.narrator import Narrator
from rpg.server import make_handler
from http.server import ThreadingHTTPServer


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.game = Game(save_dir=self.dir, narrator=Narrator(mode="off"))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.game, debug=False))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def req(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read()) if "json" in resp.headers["Content-Type"] else resp.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_full_session_over_http(self):
        code, st = self.req("/api/status")
        self.assertEqual((code, st["has_save"]), (200, False))
        code, bg = self.req("/api/backgrounds")
        self.assertEqual(len(bg["choices"]), 3)
        code, r = self.req("/api/new", {"background": bg["choices"][0]["key"]})
        self.assertEqual(code, 200)
        self.assertEqual(r["view"]["day"], 1)
        self.assertTrue(r["view"]["beats"])
        days = set()
        for i in range(60):
            acts = r["view"]["actions"]
            a = acts[(i * 7) % len(acts)]
            code, r = self.req("/api/act", {"id": a["id"]})
            self.assertEqual(code, 200, r)
            days.add(r["view"]["day"])
        self.assertGreater(len(days), 1, "time passes as you play")
        code, st = self.req("/api/status")
        self.assertTrue(st["has_save"])

    def test_rejects_bad_requests(self):
        _, bg = self.req("/api/backgrounds")
        code, _ = self.req("/api/new", {"background": "emperor"})
        self.assertEqual(code, 400, "only offered backgrounds")
        self.req("/api/new", {"background": bg["choices"][0]["key"]})
        self.assertEqual(self.req("/api/act", {"id": "steal:everything"})[0], 400)
        self.assertEqual(self.req("/api/act", {"id": 5})[0], 400)
        self.assertEqual(self.req("/api/act", {"id": "say", "text": "嗨"})[0], 400, "say needs a conversation")
        self.assertEqual(self.req("/api/act", raw=b"not json")[0], 400)
        self.assertEqual(self.req("/api/act", raw=b"x" * 20000)[0], 400)
        self.assertEqual(self.req("/api/act", {"id": "look", "text": "字" * 500})[0], 400)

    def test_debug_endpoints_are_off_by_default_and_static_is_sandboxed(self):
        _, bg = self.req("/api/backgrounds")
        self.req("/api/new", {"background": bg["choices"][0]["key"]})
        self.assertEqual(self.req("/api/debug/summary")[0], 404)
        self.assertEqual(self.req("/api/debug/world")[0], 404)
        self.assertEqual(self.req("/static/../rpg/world.py")[0], 404)
        self.assertEqual(self.req("/static/..%2frpg%2fworld.py")[0], 404)
        code, body = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn("青石鎮".encode(), body)

    def test_seed_is_ignored_without_debug(self):
        _, bg = self.req("/api/backgrounds")
        self.req("/api/new", {"background": bg["choices"][0]["key"], "seed": 1})
        self.assertNotEqual(self.game.world.seed, 1)


if __name__ == "__main__":
    unittest.main()
