"""Splitwave 브랜드 에셋 생성 스크립트 (Pillow만 사용).

실행: .venv/bin/python assets/make_assets.py
생성: icon.png, icon.ico, mark.png, logo.svg, theme.json (+ /tmp/splitwave-preview.png)
"""
import json
import os
import re

import customtkinter
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

SIZE = 1024
SCALE = 4
BG = "#111827"
LINE = "#F9FAFB"
TEXT = "#F9FAFB"
RADIUS = 220
STROKE = 56
X0, X_SPLIT, X_END, Y_MID = 180, 430, 844, 512
Y_ENDS = (332, 452, 572, 692)
C1_X, C2_X = 600, 680
STEPS = 60


def branch_ctrl(y_end):
    return (X_SPLIT, Y_MID), (C1_X, Y_MID), (C2_X, y_end), (X_END, y_end)


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return tuple(
        u**3 * a + 3 * u**2 * t * b + 3 * u * t**2 * c + t**3 * d
        for a, b, c, d in zip(p0, p1, p2, p3)
    )


def draw_mark(draw, s):
    """s = 좌표 배율. 1024 기준 좌표에 곱해서 그린다."""
    w = STROKE * s
    r = w / 2

    def dot(x, y):
        draw.ellipse((x * s - r, y * s - r, x * s + r, y * s + r), fill=LINE)

    draw.line((X0 * s, Y_MID * s, X_SPLIT * s, Y_MID * s), fill=LINE, width=round(w))
    dot(X0, Y_MID)
    dot(X_SPLIT, Y_MID)
    for y_end in Y_ENDS:
        ctrl = branch_ctrl(y_end)
        pts = [bezier(*ctrl, i / STEPS) for i in range(STEPS + 1)]
        draw.line([(x * s, y * s) for x, y in pts], fill=LINE, width=round(w))
        for x, y in pts:
            dot(x, y)


def render(with_bg):
    big = SIZE * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if with_bg:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=RADIUS * SCALE, fill=BG)
    draw_mark(d, SCALE)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def write_svg(path, color=None):
    """color 를 주면 선·글자 색을 바꿔 쓴다 (README 라이트 모드용 어두운 버전)."""
    color = color or LINE
    parts = [f"M {X0} {Y_MID} L {X_SPLIT} {Y_MID}"]
    for y_end in Y_ENDS:
        parts.append(f"M {X_SPLIT} {Y_MID} C {C1_X} {Y_MID}, {C2_X} {y_end}, {X_END} {y_end}")
    d = " ".join(parts)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3200 1024" width="400" height="128">
  <path d="{d}" fill="none" stroke="{color}" stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="1000" y="640" font-family="Inter, Helvetica Neue, Arial, sans-serif" font-weight="600" font-size="400" fill="{color}">splitwave</text>
</svg>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


THEME_MAP = {
    "#3B8ED0": "#F3F4F6",
    "#1F6AA5": "#F3F4F6",
    "#36719F": "#D1D5DB",
    "#144870": "#9CA3AF",
    "#3a7ebf": "#F3F4F6",
    "#325882": "#9CA3AF",
    "#1f538d": "#F3F4F6",
    "#14375e": "#9CA3AF",
}


# 흑백 팔레트: 흰 바탕 위엔 어두운 글자, 회색 바탕 위엔 흰 글자
THEME_OVERRIDES = {
    "CTkButton": {"fg_color": "#F3F4F6", "hover_color": "#D1D5DB", "text_color": "#0B1220"},
    "CTkOptionMenu": {"fg_color": "#374151", "button_color": "#4B5563",
                      "button_hover_color": "#6B7280", "text_color": "#F9FAFB"},
    "CTkSegmentedButton": {"selected_color": "#6B7280", "selected_hover_color": "#9CA3AF",
                           "text_color": "#F9FAFB"},
    "CTkCheckBox": {"fg_color": "#F3F4F6", "hover_color": "#D1D5DB", "checkmark_color": "#0B1220"},
    "CTkProgressBar": {"progress_color": "#F3F4F6"},
}


def write_theme(path):
    src = os.path.join(os.path.dirname(customtkinter.__file__), "assets", "themes", "blue.json")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    for old, new in THEME_MAP.items():
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    theme = json.loads(text)
    for widget, colors in THEME_OVERRIDES.items():
        for key, value in colors.items():
            theme[widget][key] = [value, value]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(theme, f, indent=2)
        f.write("\n")


def load_font(size):
    for name in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc",
                 "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size, index=1) if name.endswith(".ttc") else ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def write_preview(mark, path):
    w, h = 1200, 400
    img = Image.new("RGBA", (w, h), BG)
    m = mark.resize((280, 280), Image.LANCZOS)
    img.alpha_composite(m, (60, 60))
    ImageDraw.Draw(img).text((370, 200), "splitwave", font=load_font(150), fill=TEXT, anchor="lm")
    img.convert("RGB").save(path)


def main():
    icon = render(with_bg=True)
    icon.save(os.path.join(HERE, "icon.png"))
    icon.save(os.path.join(HERE, "icon.ico"),
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    mark = render(with_bg=False)
    mark.resize((128, 128), Image.LANCZOS).save(os.path.join(HERE, "mark.png"))
    write_svg(os.path.join(HERE, "logo.svg"))
    write_svg(os.path.join(HERE, "logo-light.svg"), color="#111827")  # 밝은 배경용
    write_theme(os.path.join(HERE, "theme.json"))
    write_preview(mark, "/tmp/splitwave-preview.png")


if __name__ == "__main__":
    main()
