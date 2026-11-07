"""Genera l'icona dell'app (PNG 1024 px): PyInstaller la converte in .ico/.icns."""
import sys
from PIL import Image, ImageDraw

size = 1024
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, size - 40, size - 40), radius=220, fill=(38, 70, 52))
d.ellipse((262, 262, 762, 762), fill=(214, 48, 49))
d.ellipse((412, 412, 612, 612), fill=(255, 255, 255))
img.save(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
if len(sys.argv) > 2:  # .ico per l'installer Windows
    img.save(sys.argv[2], sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
