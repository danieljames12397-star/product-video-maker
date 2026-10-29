#!/usr/bin/env python3
"""Turn product photos into uniform 1080x1080 squares. Near-square photos are
center-cropped; others are fitted whole on a soft blurred background."""
import argparse, json, os, re, sys
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(__file__))
from make_video import fetch

S = 1080


def square(src, out):
    img = Image.open(src).convert("RGB")
    r = img.width / img.height
    if 0.9 <= r <= 1.1:
        m = min(img.size); l = (img.width - m) // 2; t = (img.height - m) // 2
        img.crop((l, t, l + m, t + m)).resize((S, S), Image.LANCZOS).save(out, quality=92)
        return
    bg = img.copy(); s = max(S / bg.width, S / bg.height)
    bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1))
    l, t = (bg.width - S) // 2, (bg.height - S) // 2
    bg = bg.crop((l, t, l + S, t + S)).filter(ImageFilter.GaussianBlur(35))
    bg = Image.blend(bg, Image.new("RGB", (S, S), (255, 255, 255)), 0.25)
    fs = min(S / img.width, S / img.height)
    fg = img.resize((max(1, int(img.width * fs)), max(1, int(img.height * fs))), Image.LANCZOS)
    bg.paste(fg, ((S - fg.width) // 2, (S - fg.height) // 2))
    bg.save(out, quality=92)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--job", required=True); ap.add_argument("--outdir", default="sq")
    a = ap.parse_args()
    j = json.load(open(a.job))
    imgs = j["images"] if isinstance(j["images"], list) else re.split(r"[\s|]+|,(?=https?://)", j["images"])
    imgs = [x.strip() for x in imgs if x.strip()][:10]
    os.makedirs(a.outdir, exist_ok=True); os.makedirs("work", exist_ok=True)
    for i, s in enumerate(imgs, 1):
        raw = f"work/sq_raw{i}.jpg"; fetch(s, raw); square(raw, f"{a.outdir}/{i}.jpg")
        print("made", i, flush=True)


if __name__ == "__main__":
    main()
