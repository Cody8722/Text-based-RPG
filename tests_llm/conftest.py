"""pytest（選用）：這個資料夾的測試都是 llm 標記，預設不跑（見 pytest.ini 的 -m "not llm"）；pytest -m llm 才會跑。"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    here = os.path.dirname(os.path.abspath(__file__))
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(pytest.mark.llm)


def pytest_terminal_summary(terminalreporter):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "latest.txt")
    if terminalreporter.config.getoption("-m") == "llm" and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            terminalreporter.write_line(f.read())
