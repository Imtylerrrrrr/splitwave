# -*- coding: utf-8 -*-
"""스템 분리 탭.
demucs 가 설치돼 있으면 StemsPage, 없으면(라이트 버전) LitePlaceholder 를 만든다.
demucs/torch 는 여기서 최상단 import 하지 않는다 — 라이트 환경에서도 이 모듈은 로드돼야 한다."""

import customtkinter as ctk


def stems_available() -> bool:
    """풀 버전 여부는 오직 demucs import 가능 여부로 판단한다."""
    try:
        import demucs.api
    except ImportError:
        return False
    return demucs.api is not None


LITE_NOTICE = (
    "🎛️ 스템 분리는 풀 버전에서 지원돼요.\n\n"
    "• 풀 버전(zip)을 받아서 실행하거나\n"
    "• 소스로 실행 중이라면 터미널에서\n"
    "    pip install -r requirements-stems.txt\n"
    "  를 실행한 뒤 프로그램을 다시 켜 주세요.\n\n"
    "(풀 버전은 PyTorch가 들어 있어 수백 MB예요)"
)


class LitePlaceholder(ctk.CTkFrame):
    """라이트 버전에서 스템 탭에 보여줄 안내."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        ctk.CTkLabel(
            self, text=LITE_NOTICE, justify="left", anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=20, pady=30)


def make_stems_tab(parent, app) -> ctk.CTkFrame:
    if not stems_available():
        return LitePlaceholder(parent)
    from stems_page import StemsPage   # 같은 모듈. Task 4 에서 클래스가 추가된다
    return StemsPage(parent, app)
