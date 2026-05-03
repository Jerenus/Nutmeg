"""Render PNG overlays for v3.2 clean-plate captioned master.

Outputs:
  captions/hook-card.png        — opening hook card (0–2s)
  captions/subtitle-N.png       — N=1..7, one PNG per SRT cue (bottom band)
  captions/closing-card.png     — closing compliance footer (last 2.5s)

All PNGs are 720x1280 RGBA, transparent background, only the relevant band drawn.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 1280
BASE = Path(
    "/Users/jz71/Projects/Nutmeg/.nutmeg-data/daily-content/20260428/run-134330/matches/周二004/captions"
)
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"

SUBTITLES = [
    "今晚这场欧冠，巴黎对拜仁，看的是谁先把节奏抢到自己脚下。",
    "巴黎开局若把前场压迫推到边线，拜仁第一脚出球会很难受。",
    "风险在于：前后场距离一拉开，肋部冲刺点就会打到身后。",
    "中场节拍器够快，边路与肋部就能连续制造二次进攻。",
    "市场预期克制：主场优势在，但更像一球差或平局拉锯。",
    "重点信号：开局压迫时长、谁负责提速、第一粒进球归属。",
    "以上仅为赛前数据观察，不构成投注建议，理性看球。",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_rounded_band(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    fnt: ImageFont.FreeTypeFont,
    *,
    fill=(255, 255, 255, 255),
    stroke=(0, 0, 0, 255),
    stroke_width: int = 3,
) -> None:
    tw, th = text_size(draw, text, fnt)
    draw.text(
        (cx - tw / 2, cy - th / 2),
        text,
        font=fnt,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke,
    )


def render_subtitle(text: str, out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fnt = font(30)
    margin_x = 32
    # Wrap by character width
    max_chars_per_line = 22
    lines: list[str] = []
    current = text
    while current:
        if len(current) <= max_chars_per_line:
            lines.append(current)
            break
        # find a soft break
        chunk = current[:max_chars_per_line]
        # try to break at punctuation
        break_idx = max(
            chunk.rfind(c) for c in ["，", "。", "、", "：", "；", " "]
        )
        if break_idx <= 0:
            break_idx = max_chars_per_line
        else:
            break_idx += 1
        lines.append(current[:break_idx])
        current = current[break_idx:]
    line_h = 42
    band_h = max(line_h * len(lines) + 36, 90)
    band_y0 = H - 80 - band_h
    band_y1 = H - 80
    draw_rounded_band(
        draw,
        (margin_x, band_y0, W - margin_x, band_y1),
        radius=22,
        fill=(0, 0, 0, 170),
    )
    cy = band_y0 + 18 + line_h // 2
    for line in lines:
        draw_centered_text(draw, line, W // 2, cy, fnt)
        cy += line_h
    img.save(out_path)


def render_hook_card(out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    band_x0, band_x1 = 60, W - 60
    band_y0, band_y1 = 140, 440
    draw_rounded_band(draw, (band_x0, band_y0, band_x1, band_y1), radius=28, fill=(0, 0, 0, 180))
    # Top kicker
    draw_centered_text(draw, "欧冠半决赛 · 首回合", W // 2, band_y0 + 56, font(30))
    # Big title
    draw_centered_text(
        draw,
        "巴黎 vs 拜仁",
        W // 2,
        band_y0 + 140,
        font(64),
        stroke_width=4,
    )
    # Hint
    draw_centered_text(
        draw,
        "今晚关注总进球 3–4 球区间",
        W // 2,
        band_y0 + 230,
        font(28),
        fill=(255, 220, 120, 255),
    )
    img.save(out_path)


def render_closing_card(out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    band_x0, band_x1 = 80, W - 80
    band_y0, band_y1 = H // 2 - 80, H // 2 + 80
    draw_rounded_band(draw, (band_x0, band_y0, band_x1, band_y1), radius=24, fill=(0, 0, 0, 180))
    draw_centered_text(draw, "理性看球 · 仅供参考", W // 2, H // 2 - 22, font(34))
    draw_centered_text(
        draw,
        "Retro Football Manga v3.2",
        W // 2,
        H // 2 + 28,
        font(22),
        fill=(255, 220, 120, 255),
    )
    img.save(out_path)


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    render_hook_card(BASE / "hook-card.png")
    render_closing_card(BASE / "closing-card.png")
    for i, line in enumerate(SUBTITLES, start=1):
        render_subtitle(line, BASE / f"subtitle-{i}.png")
    print("rendered", sorted(p.name for p in BASE.glob("*.png")))


if __name__ == "__main__":
    main()
