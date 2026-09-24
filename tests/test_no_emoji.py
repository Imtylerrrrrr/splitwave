import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


@pytest.mark.parametrize("name", ["main.py", "stems_page.py", "common.py", "separator.py"])
def test_no_emoji_in_source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        hits = [(i, line.strip()) for i, line in enumerate(f, 1) if EMOJI.search(line)]
    assert hits == []
