#!/usr/bin/env python3
"""Build a 1080x1920 product video from photos: slow crossfades, English
voiceover (Piper), original generated background music. Uses only the given
product photos."""
import argparse, hashlib, os, random, re, subprocess, sys, textwrap, urllib.request, wave
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
    return f"{clean(hook).rstrip('.!?')}. {body} Find it at Deco Dwelling. Tap the link to see the details."


VOICES = [("en_US", "amy", "low"), ("en_US", "amy", "medium"), ("en_US", "lessac", "medium"),
          ("en_GB", "alba", "medium"), ("en_GB", "jenny_dioco", "medium")]


def tts(text, out_wav, seed=0, scale=1.08):
    with open("voice.txt", "w") as fh:
        fh.write(text)
    order = VOICES[seed % len(VOICES):] + VOICES[:seed % len(VOICES)]
    for lang, name, q in order + [VOICES[0]]:
        model = f"{lang}-{name}-{q}.onnx"
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/{lang}/{name}/{q}/"
        try:
            for f in (model, model + ".json"):
                if not os.path.exists(f):
                    urllib.request.urlretrieve(base + f, f)
            sh(["piper", "-m", model, "-i", "voice.txt", "-f", out_wav, "--length-scale", str(scale)])
            print("voice:", model)
            return model
        except Exception as e:
            print("voice failed", model, e, flush=True)
    raise SystemExit("no voice worked")


def fit_voice(text, out_wav, model, target, scale=1.16):
    """Re-voice sentence by sentence and spread the lines with pauses so the
    voiceover runs close to `target` seconds instead of ending early."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    parts = []
    for i, snt in enumerate(sents):
        with open("voice.txt", "w") as fh:
            fh.write(snt)
        f = f"work/vo_{i}.wav"
        sh(["piper", "-m", model, "-i", "voice.txt", "-f", f, "--length-scale", str(scale)])
        parts.append(f)
    with wave.open(parts[0]) as w:
        params = w.getparams(); sr = w.getframerate()
    speech = sum(wav_len(f) for f in parts)
    gap = (target - speech) / max(len(parts) - 1, 1)
    gap = min(max(gap, 0.35), 1.8)
    with wave.open(out_wav, "w") as o:
        o.setparams(params)
        for i, f in enumerate(parts):
            with wave.open(f) as w:
                o.writeframes(w.readframes(w.getnframes()))
            if i < len(parts) - 1:
                o.writeframes(b"\x00" * int(sr * gap) * params.sampwidth * params.nchannels)
    print(f"voice fitted: speech {speech:.1f}s, gap {gap:.2f}s, total {wav_len(out_wav):.1f}s (target {target:.1f}s)")


def wav_len(p):
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()


def music(dur, out_wav, sr=48000, seed=0):
    rng = random.Random(seed)
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
        elif kind == "bell":
            w = np.sin(2*np.pi*f*tt) + .5*np.sin(2*np.pi*2.76*f*tt) + .25*np.sin(2*np.pi*5.4*f*tt)
            env = np.exp(-tt*1.6) * np.minimum(tt/.005, 1)
        else:
            w = np.sin(2*np.pi*f*tt) + .3*np.sin(2*np.pi*3*f*tt)
            env = np.exp(-tt*decay) * np.minimum(tt/.01, 1)
        w = w * np.clip(env, 0, 1) * amp
        e = min(s+l, n); m[s:e] = w[:e-s]; return m

    progs = [
        [[48,55,59,64],[45,52,60,64],[41,48,57,64],[43,50,59,62]],
        [[50,57,62,65],[46,53,60,65],[43,50,58,62],[45,52,60,64]],
        [[48,55,60,64],[53,57,60,65],[55,59,62,67],[48,55,60,64]],
        [[45,52,57,60],[41,48,53,60],[48,55,60,64],[43,50,55,59]],
        [[52,59,64,67],[48,55,60,64],[45,52,57,60],[43,50,55,62]],
        [[43,50,55,62],[40,47,52,59],[48,55,60,67],[50,57,62,69]],
    ]
    shift = rng.choice([-3, -2, 0, 0, 2, 3, 5])
    chords = [[p + shift for p in c] for c in rng.choice(progs)]
    arps = [[1,2,3,2,1,3,2,3], [1,3,2,3,1,3,2,1], [3,2,1,2,3,2,1,2], [1,2,3,3,2,1,2,3]]
    arp_ix = rng.choice(arps)
    cl = rng.choice([4.4, 5.0, 5.5, 6.2])
    decay = rng.choice([2.2, 3.2, 4.2])
    lead = rng.choice(["pluck", "bell"])
    oct_up = rng.choice([0, 12, 12])
    pad_amp = rng.choice([.10, .12, .14])
    mix = np.zeros(n)
    for k, st in enumerate(np.arange(0, dur, cl)):
        ch = chords[k % 4]
        for p in ch: mix += note(mid(p), st, cl+.8, pad_amp, "pad")
        arp = [ch[i] + oct_up for i in arp_ix]
        for j, p in enumerate(arp): mix += note(mid(p), st+j*cl/8, 1.0, .10, lead)
    mix = mix / np.max(np.abs(mix)) * .8
    d = int(rng.choice([.28, .32, .4])*sr); echo = np.zeros(n); echo[d:] = mix[:-d]*.35
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
        fid = m.group(1)
        ok = subprocess.run(["gdown", f"https://drive.google.com/uc?id={fid}", "-O", dst]).returncode == 0
        if not ok or not os.path.exists(dst) or os.path.getsize(dst) < 20000:
            sh(["curl", "-fL", "-o", dst,
                f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"])
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


def motion(i, seg, fps=30):
    """Slow Ken Burns move on a still: alternates zoom-in, zoom-out, pan left/right."""
    nf = int(round(seg * fps)) + 3
    kind = i % 4
    if kind == 0:    # slow zoom in, centered
        z, x, y = f"1+0.08*on/{nf}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif kind == 1:  # slow zoom out
        z, x, y = f"1.08-0.08*on/{nf}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif kind == 2:  # zoom in drifting to the right
        z, x, y = f"1.06+0.02*on/{nf}", f"(iw-iw/zoom)*on/{nf}", "ih/2-(ih/zoom/2)"
    else:            # zoom in drifting to the left
        z, x, y = f"1.06+0.02*on/{nf}", f"(iw-iw/zoom)*(1-on/{nf})", "ih/2-(ih/zoom/2)"
    return (f"scale=2160:-2,zoompan=z='{z}':x='{x}':y='{y}':d={nf}:s={W}x{H}:fps={fps},"
            f"trim=duration={seg:.3f},setpts=PTS-STARTPTS,settb=1/{fps}")


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
    fd = 0
    if has_clip:
        get_clip(a.clip.strip(), "work/clip_raw.mp4")
        fd = probe_dur("work/clip_raw.mp4")
        overlay_png(a.hook, "work/ov.png")
    npho = len(frames)
    seed = int(hashlib.md5((a.hook + a.images[:300]).encode()).hexdigest()[:8], 16)
    print("audio seed", seed, flush=True)
    vtext = voice_text(a.hook, a.caption)
    model = tts(vtext, "work/vo.wav", seed)
    vlen = wav_len("work/vo.wav")

    # Timeline. With a clip, alternate: clip, photo, clip, photo ... so the
    # product footage appears all the way through, not only at the start.
    # Each clip piece is cut from a different part of the uploaded video.
    if has_clip:
        xf = 0.6
        # Longer pieces so viewers can see what the product does; cap at 5
        # clip+photo pairs to keep the video around 30 seconds.
        npho = min(npho, 5); frames = frames[:npho]
        K = max(npho, 1)
        first_c, clip_c, pho_c = 4.0, 3.5, 3.0
        plan = []  # (kind, index, base duration)
        for i in range(K):
            plan.append(("clip", i, first_c if i == 0 else clip_c))
            if i < npho:
                plan.append(("photo", i, pho_c))
    else:
        xf = 0.9
        plan = [("photo", i, 3.2) for i in range(npho)]
    base = sum(d for _, _, d in plan) - xf * (len(plan) - 1)
    total = max(base, vlen + 2.5)
    stretch = (total + xf * (len(plan) - 1)) / sum(d for _, _, d in plan)
    plan = [(k, i, d * stretch) for k, i, d in plan]
    total = sum(d for _, _, d in plan) - xf * (len(plan) - 1)
    target = total - 0.8 - 1.2  # voice starts at 0.8s; leave ~1.2s at the end
    if vlen < target - 1.0:
        fit_voice(vtext, "work/vo.wav", model, target)
        vlen = wav_len("work/vo.wav")
    music(total + .5, "work/bg.wav", seed=seed)

    clips = [(i, d) for k, i, d in plan if k == "clip"]
    starts = {}
    for n, (i, d) in enumerate(clips):
        room = max(fd - d, 0)
        starts[i] = room * n / max(len(clips) - 1, 1) if len(clips) > 1 else 0
    cmd = ["ffmpeg", "-y", "-v", "error"]
    durs = []; idx = {}; n_in = 0
    for k, i, d in plan:
        if k == "clip":
            cmd += ["-ss", f"{starts[i]:.3f}", "-t", f"{d:.3f}", "-i", "work/clip_raw.mp4"]
        else:
            cmd += ["-i", frames[i]]
        idx[(k, i)] = n_in; n_in += 1; durs.append(d)
    ov_in = None
    if has_clip:
        cmd += ["-loop", "1", "-t", f"{plan[0][2]:.3f}", "-i", "work/ov.png"]
        ov_in = n_in; n_in += 1
    cmd += ["-i", "work/vo.wav", "-i", "work/bg.wav"]
    ai = n_in
    fc = ""; labels = []
    for j, (k, i, d) in enumerate(plan):
        src = idx[(k, i)]
        if k == "clip":
            fc += (f"[{src}:v]fps=30,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={d:.3f},trim=duration={d:.3f},split[c1_{j}][c2_{j}];"
                   f"[c1_{j}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:5[cb{j}];"
                   f"[c2_{j}]scale={W}:1100:force_original_aspect_ratio=decrease[cf{j}];"
                   f"[cb{j}][cf{j}]overlay=(W-w)/2:420+(1100-h)/2[cm{j}];")
            if j == 0:
                fc += f"[{ov_in}:v]format=rgba[ov];[cm{j}][ov]overlay=0:0,settb=1/30,setpts=PTS-STARTPTS,format=yuv420p[v{j}];"
            else:
                fc += f"[cm{j}]settb=1/30,setpts=PTS-STARTPTS,format=yuv420p[v{j}];"
        else:
            fc += f"[{src}:v]{motion(i, d)},format=yuv420p[v{j}];"
        labels.append(f"v{j}")
    prev = labels[0]; acc = durs[0]
    for i in range(1, len(labels)):
        off = acc - xf
        fc += f"[{prev}][{labels[i]}]xfade=transition=fade:duration={xf}:offset={off:.3f}[x{i}];"
        prev = f"x{i}"; acc = acc - xf + durs[i]
    fc += (f"[{ai}:a]adelay=800|800,aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={total+.5:.3f},asplit[vo][sc];"
           f"[{ai+1}:a]volume=.55[bg];[bg][sc]sidechaincompress=threshold=.03:ratio=8:attack=20:release=400[duck];"
           f"[vo][duck]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,"
           f"atrim=0:{total:.3f},afade=t=out:st={max(total-1.5,0):.3f}:d=1.5[a]")
    cmd += ["-filter_complex", fc, "-map", f"[{prev}]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", a.out]
    sh(cmd)
    print("done", a.out)


if __name__ == "__main__":
    main()
