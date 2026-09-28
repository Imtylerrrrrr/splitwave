"""Splitwave Hub 화면 (customtkinter). 이모지 금지."""
from __future__ import annotations

import functools
import sys
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from common import resource_path
from hub.core import NOT_INSTALLED, UP_TO_DATE, Hub, HubError, Source, Status, spawn

MB = 1024 * 1024


def fmt_mb(n: int) -> str:
    return f"{-(-n // MB)} MB"


def status_text(status: Status, latest: str | None, check_failed: bool) -> str:
    if status.state == NOT_INSTALLED:
        text = f"설치 안 됨 · 받을 크기 {fmt_mb(status.download_size)}"
    elif status.state == UP_TO_DATE:
        text = f"설치됨 v{status.installed_version}" + ("" if check_failed else " · 최신")
    else:
        text = (f"업데이트 있음 v{status.installed_version} → v{latest} · "
                f"받을 크기 {fmt_mb(status.download_size)}")
    if check_failed:
        text += " (업데이트 확인 실패)"
    return text


def buttons_for(state: str) -> list[str]:
    if state == NOT_INSTALLED:
        return ["설치"]
    if state == UP_TO_DATE:
        return ["실행", "삭제"]
    return ["업데이트", "실행", "삭제"]


def run(root: Path | None, base: str | None) -> None:
    try:
        App(root, base).mainloop()
    except Exception as e:
        # 최후의 방어선: 창을 만들다 실패해도 이유는 보여 준다 (기존 앱과 같은 방식)
        try:
            messagebox.showerror("오류", f"프로그램 실행 중 오류가 발생했습니다.\n{e}")
        except Exception:
            print(f"오류: {e}", file=sys.stderr)


class App(ctk.CTk):
    def __init__(self, root: Path | None = None, base: str | None = None):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(resource_path("assets/theme.json"))

        self.title("Splitwave Hub")
        self.geometry("520x600")
        self.resizable(False, False)
        self._set_window_icon()

        self.hub = Hub(root, Source(base))
        self.manifest = None
        self.busy = False
        self.names: dict[str, str] = {}
        self.static_buttons: list[ctk.CTkButton] = []
        self.card_buttons: list[ctk.CTkButton] = []

        self._build_ui()
        self.hub.cleanup_old_self()
        self.refresh()

    def _set_window_icon(self):
        self._icon_img = ImageTk.PhotoImage(Image.open(resource_path("assets/icon.png")).resize((256, 256)))
        self.iconphoto(True, self._icon_img)
        if sys.platform == "win32":
            try:
                self.iconbitmap(resource_path("assets/icon.ico"))
            except Exception:
                pass

    # ── UI 구성 ──

    def _build_ui(self):
        ctk.CTkLabel(self, text="Splitwave Hub", font=("", 20, "bold")).pack(pady=(16, 4))
        self.top_status = ctk.CTkLabel(self, text="")
        self.top_status.pack()
        self.refresh_btn = ctk.CTkButton(self, text="다시 확인", command=self.refresh)
        self.refresh_btn.pack(pady=(4, 8))
        self.static_buttons.append(self.refresh_btn)

        self.hub_update_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.hub_update_frame, text="허브 새 버전이 있어요").pack(side="left", padx=(0, 8))
        self.hub_update_btn = ctk.CTkButton(self.hub_update_frame, text="허브 업데이트",
                                             command=self._on_hub_update)
        self.hub_update_btn.pack(side="left")
        self.static_buttons.append(self.hub_update_btn)

        self.cards_frame = ctk.CTkScrollableFrame(self, width=480, height=380)
        self.cards_frame.pack(padx=16, pady=8, fill="both", expand=True)

        self.progress_bar = ctk.CTkProgressBar(self, width=480)
        self.progress_bar.set(0)
        self.progress_bar.pack(padx=16, pady=(8, 2))
        self.progress_label = ctk.CTkLabel(self, text="")
        self.progress_label.pack(pady=(0, 12))

    def _add_card(self, app_id: str, name: str, description: str, text: str, buttons: list[str]):
        card = ctk.CTkFrame(self.cards_frame)
        card.pack(fill="x", pady=6, padx=4)
        ctk.CTkLabel(card, text=name, font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        if description:
            ctk.CTkLabel(card, text=description).pack(anchor="w", padx=10)
        ctk.CTkLabel(card, text=text).pack(anchor="w", padx=10, pady=(0, 6))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=10, pady=(0, 8))
        handlers = {"설치": self._install, "업데이트": self._install,
                    "실행": self._launch, "삭제": self._remove}
        for label in buttons:
            btn = ctk.CTkButton(row, text=label, width=90,
                                 command=functools.partial(handlers[label], app_id))
            btn.pack(side="left", padx=(0, 6))
            self.card_buttons.append(btn)
            if self.busy:
                btn.configure(state="disabled")

    # ── 목록 갱신 ──

    def refresh(self):
        if self.busy:
            return
        self._set_busy(True)

        def worker():
            try:
                m = self.hub.fetch_manifest()
            except HubError as e:
                self.after(0, self._on_manifest, None, str(e))
                return
            self.after(0, self._on_manifest, m, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_manifest(self, manifest, error):
        self.manifest = manifest
        self.check_failed = error is not None
        self._set_busy(False)
        self._render()

    def _render(self):
        if self.manifest is not None:
            self.top_status.configure(text=f"최신 버전 v{self.manifest.version}")
        else:
            self.top_status.configure(text="목록을 가져오지 못했어요")

        if self.manifest is not None and self.hub.hub_update_available(self.manifest):
            self.hub_update_frame.pack(before=self.cards_frame, pady=(0, 8))
        else:
            self.hub_update_frame.pack_forget()

        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.card_buttons = []
        self.names = {}

        if self.manifest is not None:
            for app in self.manifest.apps:
                status = self.hub.status(app)
                self.names[app.id] = app.name
                self._add_card(app.id, app.name, app.description,
                               status_text(status, self.manifest.version, False),
                               buttons_for(status.state))
        else:
            for app_id, rec in self.hub.installed().items():
                self.names[app_id] = rec.get("name", app_id)
                status = Status(UP_TO_DATE, rec.get("version"), 0)
                self._add_card(app_id, rec.get("name", app_id), "",
                               status_text(status, None, True), buttons_for(UP_TO_DATE))

    # ── 작업 실행 ──

    def _run_task(self, fn, on_done=None):
        if self.busy:
            return
        self._set_busy(True)

        def worker():
            try:
                result = fn()
            except HubError as e:
                self.after(0, self._on_task_error, str(e))
                return
            except Exception as e:
                self.hub.log(f"unexpected error: {e!r}")
                self.after(0, self._on_task_error, f"예상하지 못한 오류가 났어요.\n{e}")
                return
            self.after(0, self._on_task_success, on_done, result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_error(self, msg):
        self._set_busy(False)
        self._reset_progress()
        messagebox.showerror("오류", msg)

    def _on_task_success(self, on_done, result):
        self._set_busy(False)
        self._reset_progress()
        if on_done:
            on_done(result)

    def _progress_cb(self):
        def cb(done, total, name):
            self.after(0, self._update_progress, done, total, name)
        return cb

    def _update_progress(self, done, total, name):
        self.progress_bar.set(done / total if total else 0)
        if total and done >= total:
            self.progress_label.configure(text="받기 완료, 설치하는 중...")
        else:
            self.progress_label.configure(text=f"{name} {fmt_mb(done)} / {fmt_mb(total)}")

    def _reset_progress(self):
        self.progress_bar.set(0)
        self.progress_label.configure(text="")

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for btn in self.static_buttons + self.card_buttons:
            btn.configure(state=state)

    # ── 버튼 동작 ──

    def _install(self, app_id: str):
        self._run_task(lambda: self.hub.install(self.manifest, app_id, self._progress_cb()),
                        on_done=lambda _: self._render())

    def _launch(self, app_id: str):
        self._run_task(lambda: self.hub.launch(app_id))

    def _remove(self, app_id: str):
        name = self.names.get(app_id, app_id)
        if not messagebox.askyesno("삭제", f"'{name}' 앱을 삭제할까요?"):
            return
        self._run_task(lambda: self.hub.remove(app_id), on_done=lambda _: self._render())

    def _on_hub_update(self):
        self._run_task(lambda: self.hub.self_update(self.manifest, self._progress_cb()),
                        on_done=self._finish_hub_update)

    def _finish_hub_update(self, path):
        spawn([str(path)])
        self.destroy()
