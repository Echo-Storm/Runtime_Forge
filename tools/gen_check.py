"""Regenerates assets/check.png, dash.png, chevron_right.png and chevron_down.png -
the white tick / dash drawn
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

GREY = (139, 147, 157, 255)  # theme.TEXT_DIM
right = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
ImageDraw.Draw(right).line([(24, 14), (42, 32), (24, 50)], fill=GREY, width=8, joint="curve")
right.save(Path(__file__).resolve().parent.parent / "assets" / "chevron_right.png")
down = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
ImageDraw.Draw(down).line([(14, 24), (32, 42), (50, 24)], fill=GREY, width=8, joint="curve")
down.save(Path(__file__).resolve().parent.parent / "assets" / "chevron_down.png")
