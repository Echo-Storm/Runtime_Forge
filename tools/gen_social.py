"""
Generates assets/social-preview.png (1280x640, GitHub's recommended size) - the
image shown when the repo is linked on social sites and in search results.

GitHub has no API for this: upload it by hand under
  Settings -> General -> Social preview -> Edit -> Upload an image.

Needs Pillow and the Segoe UI fonts that ship with Windows. Re-run after the app
name, palette or main screenshot changes.

    python tools/gen_social.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONTS = Path(r"C:\Windows\Fonts")
W, H = 1280, 640

BG_TOP, BG_BOTTOM = (16, 19, 23), (27, 33, 41)
ACCENT = (90, 169, 242)
TEXT = (232, 236, 241)
DIM = (139, 147, 157)
CHIP_BG, CHIP_BORDER = (31, 38, 47), (58, 66, 76)


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


def rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, image.width, image.height], radius=radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def main() -> None:
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(H):                                   # vertical gradient
        t = y / (H - 1)
        draw.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))

    # soft accent glow behind the screenshot
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([640, 60, 1240, 600], fill=(30, 70, 120))
    img = Image.blend(img, Image.composite(glow, img, glow.convert("L").point(lambda v: 255 if v else 0)).filter(ImageFilter.GaussianBlur(90)), 0.55)
    draw = ImageDraw.Draw(img)

    # the real window, rounded, with a shadow
    shot = Image.open(ASSETS / "screenshot.png").convert("RGB")
    target_w = 540
    shot = shot.resize((target_w, round(shot.height * target_w / shot.width)), Image.LANCZOS)
    shot = shot.crop((0, 0, target_w, min(shot.height, 500)))
    card = rounded(shot, 16)
    shadow = Image.new("RGBA", (card.width + 80, card.height + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 50, 40 + card.width, 50 + card.height], radius=16, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    x, y = W - card.width - 40, (H - card.height) // 2 + 8
    img.paste(shadow, (x - 40, y - 40), shadow)
    img.paste(card, (x, y), card)
    draw = ImageDraw.Draw(img)

    # icon + title
    icon = Image.open(ASSETS / "icon.png").convert("RGBA").resize((92, 92), Image.LANCZOS)
    img.paste(icon, (64, 70), icon)
    draw.text((176, 70), "Runtime Forge", font=font("segoeuib.ttf", 58), fill=TEXT)
    draw.text((178, 142), "Windows runtimes, dev tools & apps", font=font("segoeui.ttf", 23), fill=ACCENT)

    tagline = font("segoeui.ttf", 31)
    for i, line in enumerate(["See what's installed.", "Install, update or remove it.", "Every download verified."]):
        draw.text((66, 232 + i * 48), line, font=tagline, fill=TEXT if i < 2 else DIM)

    # chips
    chip_font = font("segoeuisb.ttf" if (FONTS / "segoeuisb.ttf").exists() else "seguisb.ttf", 21)
    rows = [["DirectX", "VC++", ".NET", "Java"], ["Python", "Go", "Rust", "Git"], ["Node", "Terminal", "+ 60 more"]]
    cy = 410
    for row in rows:
        cx = 66
        for label in row:
            tw = draw.textlength(label, font=chip_font)
            box = [cx, cy, cx + tw + 34, cy + 42]
            draw.rounded_rectangle(box, radius=21, fill=CHIP_BG, outline=CHIP_BORDER, width=2)
            draw.text((cx + 17, cy + 6), label, font=chip_font, fill=TEXT if label != "+ 60 more" else ACCENT)
            cx = box[2] + 12
        cy += 54

    draw.text((66, H - 52), "Open source  ·  MIT  ·  Windows 10 / 11  ·  github.com/Echo-Storm/Runtime_Forge", font=font("segoeui.ttf", 20), fill=DIM)
    out = ASSETS / "social-preview.png"
    img.save(out)
    print(f"Wrote {out} ({W}x{H})")


if __name__ == "__main__":
    main()
