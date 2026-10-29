#!/usr/bin/env python3
"""Build a 1080x1920 product video from photos: slow crossfades, English
voiceover (Piper), original generated background music. Uses only the given
product photos."""
import argparse, os, re, subprocess, sys, textwrap, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]
SHOP = "decodwelling.base.shop"


def sh(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def font(size):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def fetch(src, dst):
    if os.path.exists(src):
        Image.open(src).convert("RGB").save(dst)
        return
    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst + ".raw", "wb") as f:
        f.write(r.read())
    Image.open(dst + ".raw").convert("RGB").save(dst)


def make_frame(path, out, hook=None):
    img = Image.open(path).convert("RGB")
    bg = img.copy()
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1))
    l, t = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (255, 255, 255)), 0.25)
    fs = min(W / img.width, 1100 / img.height)
    fg = img.resize((int(img.width * fs), int(img.height * fs)))
    bg.paste(fg, ((W - fg.width) // 2, 420 + (1100 - fg.height) // 2))
    d = ImageDraw.Draw(bg, "RGBA")
    # shop banner
    d.rounded_rectangle((90, 1700, W - 90, 1800), 18, fill=(190, 165, 120, 235))
    f = font(44)
    tw = d.textlength(SHOP, font=f)
    d.text(((W - tw) / 2, 1722), SHOP, font=f, fill=(255, 255, 255))
    if hook:
        lines = textwrap.wrap(hook, 24)[:4]
        fh = font(58)
        bh = 40 + 76 * len(lines)
        d.rounded_rectangle((70, 90, W - 70, 90 + bh), 28, fill=(255, 255, 255, 225))
        for i, ln in enumerate(lines):
            lw = d.textlength(ln, font=fh)
            d.text(((W - lw) / 2, 112 + 76 * i), ln, font=fh, fill=(60, 45, 40))
    bg.save(out)


def clean(t):
    t = re.sub(r"[^\x00-\x7F]+", " ", t)
    t = re.sub(r"#\w+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def voice_text(hook, caption):
    sents = re.split(r"(?<=[.!?])\s+", clean(caption))
    body = " ".join(sents[:3])
    return f"{clean(hook).rstrip('.!?')}. {body} Find it at Deco Dwelling."


def tts(text, out_wav):
    model = "en_US-amy-low.onnx"
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/"
    for f in (model, model + ".json"):
        if not os.path.exists(f):
            urllib.request.urlretrieve(base + f, f)
    with open("voice.txt", "w") as fh:
        fh.write(text)
    sh(["piper", "-m", model, "-i", "voice.txt", "-f", out_wav, "--length-scale", "1.1"])


def wav_len(p):
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()


def music(dur, out_wav, sr=48000):
    n = int(sr * dur); t = np.arange(n) / sr
    mid = lambda m: 440 * 2 ** ((m - 69) / 12)

    def note(f, start, length, amp, kind):
        m = np.zeros(n); s = int(start * sr); l = int(length * sr)
        if s >= n:
            return m
        tt = np.arange(l) / sr
        if kind == "pad":
            w = np.sin(2*np.pi*f*tt) + .4*np.sin(2*np.pi*2*f*tt) + .2*np.sin(2*np.pi*f*1.003*tt)
            env = np.minimum(tt/.8, 1) * np.minimum((length-tt)/1.2, 1)
        else:
            w = np.sin(2*np.pi*f*tt) + .3*np.sin(2*np.pi*3*f*tt)
            env = np.exp(-tt*3.2) * np.minimum(tt/.01, 1)
        w = w * np.clip(env, 0, 1) * amp
        e = min(s+l, n); m[s:e] = w[:e-s]; return m

    chords = [[48,55,59,64],[45,52,60,64],[41,48,57,64],[43,50,59,62]]
    cl = 5.5; mix = np.zeros(n)
    for k, st in enumerate(np.arange(0, dur, cl)):
        ch = chords[k % 4]
        for p in ch: mix += note(mid(p), st, cl+.8, .12, "pad")
        arp = [ch[1]+12, ch[2]+12, ch[3]+12, ch[2]+12, ch[1]+12, ch[3]+12, ch[2]+12, ch[3]+12]
        for j, p in enumerate(arp): mix += note(mid(p), st+j*cl/8, 1.0, .10, "pluck")
    mix = mix / np.max(np.abs(mix)) * .8
    d = int(.32*sr); echo = np.zeros(n); echo[d:] = mix[:-d]*.35
    L = mix + echo; R = np.roll(mix, int(.012*sr)) + np.roll(echo, int(.02*sr))
    st = np.stack([L, R], 1); st = st / np.max(np.abs(st)) * .8
    st *= (np.minimum(t/1.5, 1) * np.minimum((dur-t)/2.0, 1))[:, None]
    with wave.open(out_wav, "w") as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(sr)
        f.writeframes((st*32767).astype("<i2").tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="comma-separated URLs or paths")
    ap.add_argument("--hook", required=True)
    ap.add_argument("--caption", required=True)
    ap.add_argument("--out", default="video.mp4")
    a = ap.parse_args()
    srcs = [s.strip() for s in a.images.split(",") if s.strip()][:7]
    os.makedirs("work", exist_ok=True)
    frames = []
    for i, s in enumerate(srcs):
        raw = f"work/raw{i}.jpg"; fr = f"work/f{i}.png"
        fetch(s, raw); make_frame(raw, fr, a.hook if i == 0 else None); frames.append(fr)
    n = len(frames)
    tts(voice_text(a.hook, a.caption), "work/vo.wav")
    vlen = wav_len("work/vo.wav")
    total = max(vlen + 2.5, n * 3.2)
    xf = 0.9
    seg = (total + xf * (n - 1)) / n
    music(total + .5, "work/bg.wav")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for fr in frames: cmd += ["-loop", "1", "-t", f"{seg:.3f}", "-i", fr]
    cmd += ["-i", "work/vo.wav", "-i", "work/bg.wav"]
    fc = "".join(f"[{i}:v]fps=30,settb=1/30,setpts=PTS-STARTPTS,format=yuv420p[v{i}];" for i in range(n))
    prev = "v0"
    for i in range(1, n):
        off = i * (seg - xf)
        fc += f"[{prev}][v{i}]xfade=transition=fade:duration={xf}:offset={off:.3f}[x{i}];"
        prev = f"x{i}"
    if n == 1: prev = "v0"
    fc += (f"[{n}:a]adelay=800|800,aformat=sample_rates=48000:channel_layouts=stereo,asplit[vo][sc];"
           f"[{n+1}:a]volume=.55[bg];[bg][sc]sidechaincompress=threshold=.03:ratio=8:attack=20:release=400[duck];"
           f"[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,"
           f"atrim=0:{total:.3f}[a]")
    cmd += ["-filter_complex", fc, "-map", f"[{prev}]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", a.out]
    sh(cmd)
    print("done", a.out)


if __name__ == "__main__":
    main()
