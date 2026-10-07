"""UI 與後端整合：用真的瀏覽器點介面。需要 node + playwright（找不到就跳過，不算失敗）。"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from support import ROOT, FakeOllama, template_from_request

from rpg.game import Game
from rpg.narrator import Narrator
from rpg.server import make_handler

NODE = shutil.which("node")


def node_env():
    env = dict(os.environ)
    for cand in ("/opt/node22/lib/node_modules", "/usr/lib/node_modules", "/usr/local/lib/node_modules"):
        if os.path.isdir(os.path.join(cand, "playwright")):
            env["NODE_PATH"] = cand
    return env


def has_playwright() -> bool:
    if not NODE:
        return False
    r = subprocess.run([NODE, "-e", "require('playwright')"], env=node_env(), capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(has_playwright(), "node + playwright not available")
class UiEndToEndTests(unittest.TestCase):
    def _serve(self, narrator):
        game = Game(save_dir=tempfile.mkdtemp(), narrator=narrator)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(game, debug=False))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"

    def _run(self, url, expect_narration):
        r = subprocess.run([NODE, os.path.join(ROOT, "tests", "ui_e2e.js"), url, "1" if expect_narration else "0"],
                           env=node_env(), capture_output=True, text=True, timeout=240)
        line = (r.stdout.strip().splitlines() or ["{}"])[-1]
        out = json.loads(line)
        self.assertTrue(out.get("ok"), f"{out}\n{r.stderr[-2000:]}")
        return out

    def test_play_through_the_browser_without_llm(self):
        httpd, url = self._serve(Narrator(mode="off"))
        try:
            out = self._run(url, False)
            self.assertGreater(out["turns"], 5)
            self.assertEqual(out["drawer"], 1, "mobile drawer opens")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_play_through_the_browser_with_a_storyteller(self):
        fake = FakeOllama(lambda body: json.dumps({"narrative": "（說書人）" + template_from_request(body)}, ensure_ascii=False))
        try:
            httpd, url = self._serve(Narrator(mode="ollama", url=fake.url, timeout=5))
            try:
                self._run(url, True)
            finally:
                httpd.shutdown()
                httpd.server_close()
        finally:
            fake.close()


if __name__ == "__main__":
    unittest.main()
