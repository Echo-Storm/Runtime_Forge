"""
Generates assets/banner.png — the README hero image — from scratch (same
palette as gen_icon.py) so banner and icon stay visually consistent. Re-run
this after changing the app name or palette. Requires Pillow (not a runtime
dependency, dev-only).

Usage:
    python tools/gen_banner.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

W, H = 1536, 1024
BG = (18, 20, 23, 255)
BG_BOTTOM = (26, 29, 33, 255)
ACCENT = (91, 155, 213, 255)
ACCENT_LIGHT = (150, 197, 244, 255)
PANEL = (34, 38, 43, 255)
MUTED = (140, 148, 158, 255)

FONT_DIR = Path(r"C:\Windows\Fonts")


def _vertical_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGBA", size)
    for y in range(h):
        t = y / max(h - 1, 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4))
        ImageDraw.Draw(img).line([(0, y), (w, y)], fill=row)
    return img


def _icon_glyph(size: int) -> Image.Image:
    """The same download-arrow-into-tray motif as gen_icon.py, rendered at
    an arbitrary size for the banner."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = size // 32
    draw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=size // 6, fill=BG_BOTTOM, outline=(61, 68, 76, 255), width=max(2, size // 64))

    inset = size * 34 // 256
    draw.rounded_rectangle([inset, inset, size - inset, size - inset], radius=size * 28 // 256, fill=PANEL)

    cx = size // 2
    shaft_top = size * 66 // 256
    shaft_bottom = size * 150 // 256
    shaft_w = size * 22 // 256
    draw.rounded_rectangle([cx - shaft_w // 2, shaft_top, cx + shaft_w // 2, shaft_bottom], radius=shaft_w // 2, fill=ACCENT)

    head_w = size * 64 // 256
    head_h = size * 54 // 256
    draw.polygon(
        [
            (cx - head_w // 2, shaft_bottom - size * 6 // 256),
            (cx + head_w // 2, shaft_bottom - size * 6 // 256),
            (cx, shaft_bottom - size * 6 // 256 + head_h),
        ],
        fill=ACCENT_LIGHT,
    )

    tray_y = size * 196 // 256
    tray_left = size * 70 // 256
    tray_right = size - size * 70 // 256
    tray_h = size * 16 // 256
    draw.rounded_rectangle([tray_left, tray_y, tray_right, tray_y + tray_h], radius=tray_h // 2, fill=ACCENT)

    return img


def generate() -> None:
    img = _vertical_gradient((W, H), BG, BG_BOTTOM).convert("RGBA")

    # Soft radial accent glow behind the wordmark - depth without needing a
    # photographic background.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gcx, gcy, gr = W // 2, H // 2 - 40, 420
    gdraw.ellipse([gcx - gr, gcy - gr, gcx + gr, gcy + gr], fill=(*ACCENT[:3], 40))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)

    icon_size = 220
    title_font = ImageFont.truetype(str(FONT_DIR / "segoeuib.ttf"), 108)
    subtitle_font = ImageFont.truetype(str(FONT_DIR / "segoeui.ttf"), 34)

    title = "RUNTIME FORGE"
    subtitle = "Windows Dev & Runtime Tool Installer"

    # textbbox() is measured relative to a (0, 0) draw origin, so its top/
    # bottom values ARE the actual offsets from wherever text ends up being
    # drawn - using (bottom - top) as a "height" to add back onto the draw
    # position double-subtracts the top offset and lands the next element
    # too high (confirmed: an earlier version put the accent rule through
    # the middle of the title text because of exactly this mistake). Use
    # the bottom offset directly instead.
    tb = draw.textbbox((0, 0), title, font=title_font)
    tw, title_h = tb[2] - tb[0], tb[3]
    sb = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    sw, subtitle_h = sb[2] - sb[0], sb[3]

    icon_gap = 44
    rule_gap = 40
    rule_h = 4
    subtitle_gap = 30
    content_h = icon_size + icon_gap + title_h + rule_gap + rule_h + subtitle_gap + subtitle_h
    top = (H - content_h) // 2

    icon = _icon_glyph(icon_size)
    icon_x = (W - icon_size) // 2
    icon_y = top
    img.alpha_composite(icon, (icon_x, icon_y))

    title_y = icon_y + icon_size + icon_gap
    draw.text(((W - tw) // 2, title_y), title, font=title_font, fill=ACCENT_LIGHT)

    rule_y = title_y + title_h + rule_gap
    rule_w = 140
    draw.rounded_rectangle([(W - rule_w) // 2, rule_y, (W + rule_w) // 2, rule_y + rule_h], radius=rule_h // 2, fill=ACCENT)

    draw.text(((W - sw) // 2, rule_y + rule_h + subtitle_gap), subtitle, font=subtitle_font, fill=MUTED)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(ASSETS_DIR / "banner.png", optimize=True)
    print(f"Wrote {ASSETS_DIR / 'banner.png'}")


if __name__ == "__main__":
    generate()
