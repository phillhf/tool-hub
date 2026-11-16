"""Erzeugt installer/app.ico: vier Kacheln, eine mit Pfeil nach unten (Pillow nötig, nur einmal ausführen)."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


def draw(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256
    d.rounded_rectangle((8 * s, 8 * s, 248 * s, 248 * s), radius=52 * s, fill=(31, 111, 235))
    tiles = [(48, 48), (136, 48), (48, 136), (136, 136)]
    for i, (x, y) in enumerate(tiles):
        box = (x * s, y * s, (x + 72) * s, (y + 72) * s)
        if i == 3:
            d.rounded_rectangle(box, radius=16 * s, fill=(255, 196, 0))
            cx = (x + 36) * s
            d.rectangle((cx - 7 * s, (y + 14) * s, cx + 7 * s, (y + 40) * s), fill=(31, 111, 235))
            d.polygon([(cx - 20 * s, (y + 36) * s), (cx + 20 * s, (y + 36) * s), (cx, (y + 58) * s)], fill=(31, 111, 235))
        else:
            d.rounded_rectangle(box, radius=16 * s, fill=(255, 255, 255))
    return img


if __name__ == "__main__":
    big = draw(256)
    big.save(os.path.join(HERE, "app.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(HERE, "app_256.png"))
