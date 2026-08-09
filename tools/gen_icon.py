"""
Generates assets/icon.ico + assets/icon.png — a rounded steel/blue square
with a download-arrow-into-a-tray motif, matching the app's dark theme.
Re-run this after changing the palette or icon design instead of hand-editing
the .ico. Requires Pillow (not a runtime dependency, dev-only).

Usage:
    python tools/gen_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

SIZE = 256
BG = (26, 29, 33, 255)
ACCENT = (91, 155, 213, 255)
ACCENT_LIGHT = (124, 184, 240, 255)
PANEL = (34, 38, 43, 255)


def generate() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 8
    draw.rounded_rectangle([margin, margin, SIZE - margin, SIZE - margin], radius=44, fill=BG, outline=(61, 68, 76, 255), width=4)

    inset = 34
    draw.rounded_rectangle([inset, inset, SIZE - inset, SIZE - inset], radius=28, fill=PANEL)

    cx = SIZE // 2
    shaft_top = 66
    shaft_bottom = 150
    shaft_w = 22
    draw.rounded_rectangle([cx - shaft_w // 2, shaft_top, cx + shaft_w // 2, shaft_bottom], radius=10, fill=ACCENT)

    head_w = 64
    head_h = 54
    draw.polygon(
        [
            (cx - head_w // 2, shaft_bottom - 6),
            (cx + head_w // 2, shaft_bottom - 6),
            (cx, shaft_bottom - 6 + head_h),
        ],
        fill=ACCENT_LIGHT,
    )

    tray_y = 196
    tray_left = 70
    tray_right = SIZE - 70
    tray_h = 16
    draw.rounded_rectangle([tray_left, tray_y, tray_right, tray_y + tray_h], radius=8, fill=ACCENT)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    img.save(ASSETS_DIR / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(ASSETS_DIR / "icon.png")
    print(f"Wrote {ASSETS_DIR / 'icon.ico'} and {ASSETS_DIR / 'icon.png'}")


if __name__ == "__main__":
    generate()
