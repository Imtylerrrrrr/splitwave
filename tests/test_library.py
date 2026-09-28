import json
import os

import pytest

import library


def touch(path, content=b"x", mtime=None):
    """파일을 만들고 필요하면 수정 시각을 지정한다."""
    with open(path, "wb") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ──────────────────────────────────────────────
# 1. library_dir / ensure_library
# ──────────────────────────────────────────────

def test_library_dir_appends_splitwave(tmp_path):
    base = str(tmp_path / "Downloads")
    assert library.library_dir(base) == os.path.join(base, "Splitwave")


@pytest.mark.parametrize("folder_name", ["Splitwave", "splitwave"])
def test_library_dir_keeps_existing_splitwave_folder(tmp_path, folder_name):
    base = str(tmp_path / folder_name)
    assert library.library_dir(base) == base


def test_library_dir_does_not_create_folder(tmp_path):
    base = str(tmp_path / "Downloads")
    result = library.library_dir(base)
    assert not os.path.exists(result)


def test_ensure_library_creates_folder(tmp_path):
    base = str(tmp_path / "Downloads")
    lib = library.ensure_library(base)
    assert lib == library.library_dir(base)
    assert os.path.isdir(lib)


# ──────────────────────────────────────────────
# 2. base_dir
# ──────────────────────────────────────────────

def test_base_dir_uses_last_dir_when_folder_exists(tmp_path):
    real = tmp_path / "MyDownloads"
    real.mkdir()
    assert library.base_dir({"last_dir": str(real)}) == str(real)


def test_base_dir_falls_back_when_key_missing():
    assert library.base_dir({}) == library.default_download_dir()


def test_base_dir_falls_back_when_last_dir_not_a_folder(tmp_path):
    missing = str(tmp_path / "nope")
    assert library.base_dir({"last_dir": missing}) == library.default_download_dir()


def test_base_dir_loads_settings_when_none(tmp_path, monkeypatch):
    real = tmp_path / "SavedFolder"
    real.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"last_dir": str(real)}), encoding="utf-8")
    monkeypatch.setattr(library, "config_path", lambda: cfg)
    assert library.base_dir() == str(real)


# ──────────────────────────────────────────────
# 3. list_songs
# ──────────────────────────────────────────────

def test_list_songs_filters_ext_case_dotfiles_and_subfolders(tmp_path):
    touch(tmp_path / "Song.M4A")            # 대문자 확장자도 포함
    touch(tmp_path / "notes.txt")           # 확장자 다름 -> 제외
    touch(tmp_path / ".hidden.m4a")         # 점으로 시작 -> 제외
    sub = tmp_path / "sub"
    sub.mkdir()
    touch(sub / "inside.m4a")               # 하위 폴더 -> 제외

    songs = library.list_songs(str(tmp_path))
    assert [t.song for t in songs] == ["Song"]
    assert songs[0].stem is None
    assert songs[0].label == "Song"
    assert songs[0].path == os.path.abspath(str(tmp_path / "Song.M4A"))


def test_list_songs_sorts_by_mtime_desc_then_name(tmp_path):
    touch(tmp_path / "b.m4a", mtime=100)
    touch(tmp_path / "a.m4a", mtime=200)
    touch(tmp_path / "z.m4a", mtime=200)    # a, z 는 시각 동일 -> 이름순

    songs = library.list_songs(str(tmp_path))
    assert [t.song for t in songs] == ["a", "z", "b"]


def test_list_songs_missing_folder_returns_empty(tmp_path):
    assert library.list_songs(str(tmp_path / "nope")) == []


# ──────────────────────────────────────────────
# 4. list_tracks
# ──────────────────────────────────────────────

def test_list_tracks_song_with_stems_bundle_order(tmp_path):
    touch(tmp_path / "A.m4a", mtime=100)
    stems = tmp_path / "A_stems"
    stems.mkdir()
    touch(stems / "drum.wav", mtime=200)
    touch(stems / "vocal.wav", mtime=150)

    tracks = library.list_tracks(str(tmp_path))
    assert [(t.song, t.stem) for t in tracks] == [
        ("A", None), ("A", "drum"), ("A", "vocal"),
    ]
    assert tracks[1].label == "A / drum"
    assert tracks[2].label == "A / vocal"


def test_list_tracks_stems_only_bundle(tmp_path):
    stems = tmp_path / "B_stems"
    stems.mkdir()
    touch(stems / "keys.wav")

    tracks = library.list_tracks(str(tmp_path))
    assert [(t.song, t.stem) for t in tracks] == [("B", "keys")]


def test_list_tracks_empty_stems_folder_ignored(tmp_path):
    (tmp_path / "C_stems").mkdir()  # 빈 스템 폴더, 곡 파일 없음

    assert library.list_tracks(str(tmp_path)) == []


def test_list_tracks_bundle_order_by_latest_mtime_then_song_name(tmp_path):
    touch(tmp_path / "Old.m4a", mtime=100)

    new_stems = tmp_path / "New_stems"
    new_stems.mkdir()
    touch(new_stems / "s.wav", mtime=300)

    tied_a = tmp_path / "TiedA_stems"
    tied_a.mkdir()
    touch(tied_a / "s.wav", mtime=200)

    tied_b = tmp_path / "TiedB_stems"
    tied_b.mkdir()
    touch(tied_b / "s.wav", mtime=200)

    tracks = library.list_tracks(str(tmp_path))
    songs_in_order = [t.song for t in tracks]
    assert songs_in_order == ["New", "TiedA", "TiedB", "Old"]


# ──────────────────────────────────────────────
# 5. menu_labels
# ──────────────────────────────────────────────

def test_menu_labels_preserves_input_order():
    tracks = [
        library.Track(label="B", path="/p/b", song="B", stem=None),
        library.Track(label="A", path="/p/a", song="A", stem=None),
    ]
    assert list(library.menu_labels(tracks).keys()) == ["B", "A"]


def test_menu_labels_truncates_long_song_name_to_exact_length():
    long_name = "x" * 60
    t = library.Track(label=long_name, path="/p", song=long_name, stem=None)
    labels = library.menu_labels([t], max_len=48)
    key = next(iter(labels))
    assert len(key) == 48
    assert key.endswith("...")


def test_menu_labels_stem_label_preserves_suffix():
    long_song = "y" * 60
    t = library.Track(label=f"{long_song} / 보컬", path="/p", song=long_song, stem="보컬")
    labels = library.menu_labels([t], max_len=48)
    key = next(iter(labels))
    assert key.endswith(" / 보컬")
    assert len(key) <= 48


def test_menu_labels_duplicate_names_get_numbered():
    tracks = [
        library.Track(label="Same", path="/p/1", song="Same", stem=None),
        library.Track(label="Same", path="/p/2", song="Same", stem=None),
        library.Track(label="Same", path="/p/3", song="Same", stem=None),
    ]
    labels = library.menu_labels(tracks)
    assert list(labels.keys()) == ["Same", "Same (2)", "Same (3)"]
    assert labels["Same"] == "/p/1"
    assert labels["Same (2)"] == "/p/2"
    assert labels["Same (3)"] == "/p/3"


# ──────────────────────────────────────────────
# 6. video_id
# ──────────────────────────────────────────────

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VIDEO_ID}",
    f"https://youtu.be/{VIDEO_ID}",
    f"https://www.youtube.com/shorts/{VIDEO_ID}",
    f"https://www.youtube.com/live/{VIDEO_ID}",
    f"https://www.youtube.com/embed/{VIDEO_ID}",
])
def test_video_id_recognizes_five_forms(url):
    assert library.video_id(url) == VIDEO_ID


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VIDEO_ID}&t=10s",
    f"https://youtu.be/{VIDEO_ID}?si=abcDEF12345",
])
def test_video_id_ignores_extra_params(url):
    assert library.video_id(url) == VIDEO_ID


def test_video_id_non_youtube_url_returns_none():
    assert library.video_id(f"https://example.com/watch?v={VIDEO_ID}") is None


def test_video_id_playlist_url_with_v_param():
    url = f"https://www.youtube.com/watch?list=PLabcdefgh12345678&v={VIDEO_ID}&index=3"
    assert library.video_id(url) == VIDEO_ID


def test_video_id_not_found_returns_none():
    assert library.video_id("https://www.youtube.com/playlist?list=PLabcdefgh12345678") is None


# ──────────────────────────────────────────────
# 7. downloads_from_info
# ──────────────────────────────────────────────

def test_downloads_from_info_single_entry(tmp_path):
    f = touch(tmp_path / "song.m4a")
    info = {"id": "vid1", "requested_downloads": [{"filepath": str(f)}]}
    assert library.downloads_from_info(info) == [("vid1", [str(f)])]


def test_downloads_from_info_playlist_with_none_entries(tmp_path):
    f1 = touch(tmp_path / "one.m4a")
    f2 = touch(tmp_path / "two.m4a")
    info = {"entries": [
        {"id": "vid1", "requested_downloads": [{"filepath": str(f1)}]},
        None,
        {"id": "vid2", "requested_downloads": [{"filepath": str(f2)}]},
    ]}
    assert library.downloads_from_info(info) == [
        ("vid1", [str(f1)]),
        ("vid2", [str(f2)]),
    ]


def test_downloads_from_info_excludes_missing_file_and_missing_id(tmp_path):
    f1 = touch(tmp_path / "ok.m4a")
    info = {"entries": [
        {"id": "vid1", "requested_downloads": [{"filepath": str(f1)}]},
        {"id": "vid2", "requested_downloads": [{"filepath": str(tmp_path / "missing.m4a")}]},
        {"requested_downloads": [{"filepath": str(f1)}]},  # id 없음
    ]}
    assert library.downloads_from_info(info) == [("vid1", [str(f1)])]


# ──────────────────────────────────────────────
# 8. record_download / find_downloaded
# ──────────────────────────────────────────────

def test_record_and_find_roundtrip(tmp_path):
    lib = str(tmp_path)
    f = touch(tmp_path / "song.m4a")
    library.record_download(lib, "vid1", [str(f)])
    assert library.find_downloaded(lib, "vid1") == [os.path.abspath(str(f))]


def test_record_download_same_file_twice_is_recorded_once(tmp_path):
    lib = str(tmp_path)
    f = touch(tmp_path / "song.m4a")
    library.record_download(lib, "vid1", [str(f)])
    library.record_download(lib, "vid1", [str(f)])

    with open(tmp_path / library.INDEX_NAME, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["videos"]["vid1"] == ["song.m4a"]


def test_find_downloaded_excludes_deleted_file(tmp_path):
    lib = str(tmp_path)
    f = touch(tmp_path / "song.m4a")
    library.record_download(lib, "vid1", [str(f)])
    os.remove(f)
    assert library.find_downloaded(lib, "vid1") == []


def test_record_download_ignores_paths_outside_library(tmp_path):
    lib = str(tmp_path / "Splitwave")
    os.makedirs(lib, exist_ok=True)
    outside = touch(tmp_path / "outside.m4a")

    library.record_download(lib, "vid1", [str(outside)])

    assert library.find_downloaded(lib, "vid1") == []
    assert not os.path.exists(os.path.join(lib, library.INDEX_NAME))


def test_record_download_survives_corrupt_index_file(tmp_path):
    lib = str(tmp_path)
    (tmp_path / library.INDEX_NAME).write_text("{ 이건 json이 아님", encoding="utf-8")

    f = touch(tmp_path / "song.m4a")
    library.record_download(lib, "vid1", [str(f)])

    assert library.find_downloaded(lib, "vid1") == [os.path.abspath(str(f))]


def test_index_file_format_and_relative_path_uses_slash(tmp_path):
    lib = str(tmp_path)
    stems = tmp_path / "A_stems"
    stems.mkdir()
    f = touch(stems / "vocal.wav")

    library.record_download(lib, "vid1", [str(f)])

    with open(tmp_path / library.INDEX_NAME, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == {"version": 1, "videos": {"vid1": ["A_stems/vocal.wav"]}}


def test_record_download_keeps_file_whose_name_starts_with_two_dots(tmp_path):
    """이름이 '..' 으로 시작하는 파일은 보관함 밖이 아니다."""
    lib = str(tmp_path / "Splitwave")
    os.makedirs(lib)
    path = touch(os.path.join(lib, "..and then.m4a"))
    library.record_download(lib, "abcdefghijk", [path])
    assert library.find_downloaded(lib, "abcdefghijk") == [os.path.abspath(path)]


def test_index_entry_that_is_not_a_list_is_treated_as_empty(tmp_path):
    """색인 항목이 목록이 아니어도(손으로 고친 파일 등) 죽지 않고 새로 기록한다."""
    lib = str(tmp_path / "Splitwave")
    os.makedirs(lib)
    with open(os.path.join(lib, library.INDEX_NAME), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "videos": {"abcdefghijk": "song.m4a", "zzzzzzzzzzz": [1, None]}}, f)
    assert library.find_downloaded(lib, "abcdefghijk") == []
    assert library.find_downloaded(lib, "zzzzzzzzzzz") == []
    path = touch(os.path.join(lib, "song.m4a"))
    library.record_download(lib, "abcdefghijk", [path])
    assert library.find_downloaded(lib, "abcdefghijk") == [os.path.abspath(path)]
