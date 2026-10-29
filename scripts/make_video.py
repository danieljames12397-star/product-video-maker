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


def overlay_png(hook, out):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((90, 1700, W - 90, 1800), 18, fill=(190, 165, 120, 235))
    f = font(44); tw = d.textlength(SHOP, font=f)
    d.text(((W - tw) / 2, 1722), SHOP, font=f, fill=(255, 255, 255))
    if hook:
        lines = textwrap.wrap(hook, 24)[:4]; fh = font(58); bh = 40 + 76 * len(lines)
        d.rounded_rectangle((70, 90, W - 70, 90 + bh), 28, fill=(255, 255, 255, 225))
        for k, ln in enumerate(lines):
            lw = d.textlength(ln, font=fh)
            d.text(((W - lw) / 2, 112 + 76 * k), ln, font=fh, fill=(60, 45, 40))
    img.save(out)


def get_clip(src, dst):
    m = re.search(r"drive\.google\.com.*?(?:id=|/d/)([\w-]+)", src)
    if m:
        sh([sys.executable, "-m", "gdown", "--id", m.group(1), "-O", dst])
    elif os.path.exists(src):
        subprocess.run(["cp", src, dst], check=True)
    else:
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
            f.write(r.read())


def probe_dur(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True, check=True)
    return float(o.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="", help="URLs or paths separated by space/newline/|")
    ap.add_argument("--hook", default="")
    ap.add_argument("--caption", default="")
    ap.add_argument("--clip", default="", help="optional product video URL / Drive link")
    ap.add_argument("--job", default="", help="JSON file with images/hook/caption/clip")
    ap.add_argument("--out", default="video.mp4")
    a = ap.parse_args()
    if a.job:
        import json
        j = json.load(open(a.job))
        a.images = j.get("images", a.images); a.hook = j.get("hook", a.hook)
        a.caption = j.get("caption", a.caption); a.clip = j.get("clip", a.clip)
    imgs = a.images if isinstance(a.images, list) else re.split(r"[\s|]+|,(?=https?://)", a.images)
    srcs = [s.strip() for s in imgs if s.strip()][:7]
    os.makedirs("work", exist_ok=True)
    has_clip = bool(a.clip.strip())
    frames = []
    for i, s in enumerate(srcs):
        raw = f"work/raw{i}.jpg"; fr = f"work/f{i}.png"
        fetch(s, raw); make_frame(raw, fr, a.hook if (i == 0 and not has_clip) else None); frames.append(fr)
    cd = 0
    if has_clip:
        get_clip(a.clip.strip(), "work/clip_raw.mp4")
        cd = min(probe_dur("work/clip_raw.mp4"), 9.0)
        overlay_png(a.hook, "work/ov.png")
    npho = len(frames); N = npho + (1 if has_clip else 0)
    tts(voice_text(a.hook, a.caption), "work/vo.wav")
    vlen = wav_len("work/vo.wav")
    xf = 0.9
    total = max(vlen + 2.5, cd + npho * 3.0 - xf * (N - 1) + 0.5, N * 3.2 - xf * (N - 1))
    seg = (total - cd + xf * (N - 1)) / max(npho, 1) if npho else 0
    music(total + .5, "work/bg.wav")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    durs = []
    if has_clip:
        cmd += ["-t", f"{cd:.3f}", "-i", "work/clip_raw.mp4", "-loop", "1", "-t", f"{cd:.3f}", "-i", "work/ov.png"]
        durs.append(cd)
    for fr in frames:
        cmd += ["-loop", "1", "-t", f"{seg:.3f}", "-i", fr]; durs.append(seg)
    cmd += ["-i", "work/vo.wav", "-i", "work/bg.wav"]
    ai = (2 if has_clip else 0) + npho
    fc = ""; labels = []; k = 0
    if has_clip:
        fc += (f"[0:v]fps=30,setpts=PTS-STARTPTS,split[c1][c2];"
               f"[c1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:5[cb];"
               f"[c2]scale={W}:1100:force_original_aspect_ratio=decrease[cf];"
               f"[cb][cf]overlay=(W-w)/2:420+(1100-h)/2[cm];"
               f"[1:v]format=rgba[ov];[cm][ov]overlay=0:0,settb=1/30,setpts=PTS-STARTPTS,format=yuv420p[v0];")
        labels.append("v0"); k = 2
    for i in range(npho):
        j = len(labels)
        fc += f"[{k+i}:v]fps=30,settb=1/30,setpts=PTS-STARTPTS,format=yuv420p[v{j}];"; labels.append(f"v{j}")
    prev = labels[0]; acc = durs[0]
    for i in range(1, len(labels)):
        off = acc - xf
        fc += f"[{prev}][{labels[i]}]xfade=transition=fade:duration={xf}:offset={off:.3f}[x{i}];"
        prev = f"x{i}"; acc = acc - xf + durs[i]
    fc += (f"[{ai}:a]adelay=800|800,aformat=sample_rates=48000:channel_layouts=stereo,asplit[vo][sc];"
           f"[{ai+1}:a]volume=.55[bg];[bg][sc]sidechaincompress=threshold=.03:ratio=8:attack=20:release=400[duck];"
           f"[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,"
           f"atrim=0:{total:.3f}[a]")
    cmd += ["-filter_complex", fc, "-map", f"[{prev}]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", a.out]
    sh(cmd)
    print("done", a.out)


if __name__ == "__main__":
    main()
