"""Regenerates assets/check.png and assets/dash.png - the white tick / dash drawn
inside checked / partly-checked boxes (referenced from the stylesheet in
ui/theme.py). Needs Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

SIZE = 64  # drawn big, scaled down by Qt for crisp edges at any DPI
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.line([(14, 34), (27, 47), (51, 18)], fill=(255, 255, 255, 255), width=9, joint="curve")
for x, y in ((14, 34), (27, 47), (51, 18)):
    d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 255, 255, 255))
img.save(Path(__file__).resolve().parent.parent / "assets" / "check.png")

dash = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
dd = ImageDraw.Draw(dash)
dd.rounded_rectangle([14, 27, 50, 37], radius=5, fill=(255, 255, 255, 255))
dash.save(Path(__file__).resolve().parent.parent / "assets" / "dash.png")
