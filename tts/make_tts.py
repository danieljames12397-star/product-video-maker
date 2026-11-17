"""Voiceover job: tts/in/<name>.json -> tts/out/<name>/line_<n>.wav (one file per line).
JSON: {"voice": "en_US-lessac-high", "scale": 1.0, "lines": ["...", "..."]}"""
import json, os, subprocess, sys, urllib.request

def model_files(voice):
    lang, name, q = voice.split("-")
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/{lang}/{name}/{q}/"
    m = f"{voice}.onnx"
    for f in (m, m + ".json"):
        if not os.path.exists(f):
            urllib.request.urlretrieve(base + f, f)
    return m

for path in sys.argv[1:]:
    job = json.load(open(path))
    name = os.path.splitext(os.path.basename(path))[0]
    out = f"tts/out/{name}"; os.makedirs(out, exist_ok=True)
    try:
        model = model_files(job.get("voice", "en_US-lessac-high"))
    except Exception as e:
        print("voice failed, falling back:", e); model = model_files("en_US-lessac-medium")
    for i, line in enumerate(job["lines"], 1):
        with open("line.txt", "w") as fh: fh.write(line)
        subprocess.run(["piper", "-m", model, "-i", "line.txt", "-f", f"{out}/line_{i}.wav",
                        "--length-scale", str(job.get("scale", 1.0))], check=True)
    print("done", name, len(job["lines"]), "lines")
