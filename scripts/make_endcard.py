#!/usr/bin/env python3
"""Make a 1080x1080 JPEG 'Shop now' end card for a carousel.
usage: make_endcard.py OUT.jpg "Product title" "$28.99" "Shop name" [PHOTO_URL_OR_PATH]
"""
import io, sys, textwrap, urllib.request
from PIL import Image, ImageDraw, ImageFont

out, title, price, shop = sys.argv[1:5]
photo = sys.argv[5] if len(sys.argv) > 5 else None
W = 1080
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
f = lambda p, s: ImageFont.truetype(p, s)

img = Image.new("RGB", (W, W), (250, 245, 236))
d = ImageDraw.Draw(img)
top_h = 600
if photo:
    try:
        data = urllib.request.urlopen(urllib.request.Request(photo, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read() if photo.startswith("http") else open(photo, "rb").read()
        p = Image.open(io.BytesIO(data)).convert("RGB")
        s = max(W / p.width, top_h / p.height)
        p = p.resize((int(p.width * s) + 1, int(p.height * s) + 1))
        l, t = (p.width - W) // 2, (p.height - top_h) // 2
        img.paste(p.crop((l, t, l + W, t + top_h)), (0, 0))
    except Exception as e:
        print("photo failed:", e, file=sys.stderr)
        d.rectangle((0, 0, W, top_h), fill=(91, 107, 58))
else:
    d.rectangle((0, 0, W, top_h), fill=(91, 107, 58))

# short title (max 2 lines)
short = title.split("|")[0].split(",")[0].strip()
lines = textwrap.wrap(short, 30)[:2]
y = top_h + 38
for ln in lines:
    d.text((W // 2, y), ln, font=f(BOLD, 44), fill=(40, 40, 40), anchor="mt")
    y += 56
d.text((W // 2, y + 6), price, font=f(BOLD, 52), fill=(91, 107, 58), anchor="mt")
bx0, by0, bx1, by1 = 290, 905, 790, 985
d.rounded_rectangle((bx0, by0, bx1, by1), radius=40, fill=(91, 107, 58))
d.text(((bx0 + bx1) // 2, (by0 + by1) // 2), "Shop now  ->", font=f(BOLD, 40), fill=(255, 255, 255), anchor="mm")
d.text((W // 2, 1020), shop + "  |  link in the caption", font=f(REG, 28), fill=(90, 90, 90), anchor="mt")
img.save(out, "JPEG", quality=90)
print("saved", out, img.size)
