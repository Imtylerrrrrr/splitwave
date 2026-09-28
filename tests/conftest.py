import sys

import pytest

import library


@pytest.fixture(autouse=True)
def isolated_user_folders(tmp_path_factory, monkeypatch):
    """테스트가 실제 설정 파일과 실제 다운로드 폴더를 건드리지 않게 한다.
    (App 을 만들기만 해도 보관함 폴더가 생기므로 모든 테스트에 적용한다.)"""
    home = tmp_path_factory.mktemp("home")
    downloads = home / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(library, "config_path", lambda: home / "config.json")
    monkeypatch.setattr(library, "default_download_dir", lambda: str(downloads))
    main = sys.modules.get("main")
    if main is not None:   # main 은 이름을 가져다 쓰므로 따로 바꿔 준다
        monkeypatch.setattr(main, "default_download_dir", lambda: str(downloads))
