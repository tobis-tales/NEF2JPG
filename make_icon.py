"""Erzeugt app.ico (Windows-Icon) und app.png aus einer einfachen Zeichnung. Benoetigt nur Pillow."""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont

CANDIDATES = ("arialbd.ttf", "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=(31, 42, 68, 255))
    d.text((size / 2, size * 0.29), "NEF", font=font(int(size * 0.27)), fill=(205, 214, 232, 255), anchor="mm")
    # Pfeil nach unten
    cx, top, bottom, w = size / 2, size * 0.43, size * 0.52, size * 0.06
    d.polygon([(cx - w, top), (cx + w, top), (cx, bottom)], fill=(245, 166, 35, 255))
    d.text((size / 2, size * 0.72), "JPG", font=font(int(size * 0.36)), fill=(245, 166, 35, 255), anchor="mm")
    return img


if __name__ == "__main__":
    base = draw_icon(256)
    base.save("app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    base.save("app.png")
    print("app.ico und app.png geschrieben")
