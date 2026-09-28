import os

import pytest

pytest.importorskip("customtkinter")
pytest.importorskip("sounddevice")

import tempofollow.app as tfapp  # noqa: E402
import library  # noqa: E402


def touch(path, content=b"x", mtime=None):
    """파일을 만들고 필요하면 수정 시각을 지정한다."""
    with open(path, "wb") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_import_tempofollow_app():
    assert hasattr(tfapp, "App")


def test_library_menu_mix_of_songs_and_stems(tmp_path):
    lib = tmp_path / "Splitwave"
    lib.mkdir()
    touch(lib / "노래1.m4a", mtime=200)
    stems_dir = lib / "노래2_stems"
    stems_dir.mkdir()
    touch(stems_dir / "보컬.wav", mtime=300)
    touch(stems_dir / "드럼.wav", mtime=300)

    items = tfapp.library_menu(str(lib))

    # library.py 의 list_tracks + menu_labels 을 그대로 감싼 것이어야 한다.
    assert items == library.menu_labels(library.list_tracks(str(lib)))
    assert list(items.keys()) == ["노래2 / 드럼", "노래2 / 보컬", "노래1"]
    assert items["노래2 / 드럼"] == os.path.abspath(str(stems_dir / "드럼.wav"))
    assert items["노래1"] == os.path.abspath(str(lib / "노래1.m4a"))


def test_menu_values_guide_item_first_when_items_exist(tmp_path):
    lib = tmp_path / "Splitwave"
    lib.mkdir()
    touch(lib / "노래1.m4a", mtime=200)
    touch(lib / "노래2.m4a", mtime=300)

    items = tfapp.library_menu(str(lib))
    values = tfapp.menu_values(items)

    assert values[0] == tfapp.LIBRARY_GUIDE_ITEM
    assert values[1:] == list(items.keys())
    assert values == [tfapp.LIBRARY_GUIDE_ITEM, "노래2", "노래1"]


@pytest.mark.parametrize("make_dir", [True, False])
def test_menu_values_empty_or_missing_library(tmp_path, make_dir):
    lib = tmp_path / "lib"
    if make_dir:
        lib.mkdir()

    items = tfapp.library_menu(str(lib))
    assert items == {}
    assert tfapp.menu_values(items) == [tfapp.LIBRARY_EMPTY_ITEM]


def test_library_dropdown_does_not_grow_with_long_labels():
    """긴 곡 이름을 골라도 드롭다운이 넓어져 새로고침 버튼을 밀어내면 안 된다."""
    import inspect

    app = pytest.importorskip("tempofollow.app")
    source = inspect.getsource(app.App._build_ui)
    start = source.index("self.library_menu = ctk.CTkOptionMenu(")
    call = source[start:source.index("self.library_menu.pack", start)]
    assert "dynamic_resizing=False" in call
