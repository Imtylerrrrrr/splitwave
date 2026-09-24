import json
import os

from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def test_icon_png_is_1024():
    with Image.open(os.path.join(ASSETS, "icon.png")) as im:
        assert im.size == (1024, 1024)


def test_ico_and_mark_exist():
    assert os.path.isfile(os.path.join(ASSETS, "icon.ico"))
    assert os.path.isfile(os.path.join(ASSETS, "mark.png"))


def test_theme_json_recolored():
    with open(os.path.join(ASSETS, "theme.json"), encoding="utf-8") as f:
        text = f.read()
    json.loads(text)
    assert "#3B8ED0" not in text.upper()


def test_theme_json_has_no_teal():
    with open(os.path.join(ASSETS, "theme.json"), encoding="utf-8") as f:
        assert "#2DD4BF" not in f.read().upper()
