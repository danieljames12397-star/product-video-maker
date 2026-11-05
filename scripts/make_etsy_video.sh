#!/bin/bash
# Builds a 1440x1080 (4:3) listing video from photo URLs. Inputs (env): IMAGES (space or | separated URLs), CAPTION
set -euo pipefail
W=1440; H=1080; SEG=2.0; XF=0.4
F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
rm -rf work && mkdir -p work && cd work
mapfile -t URLS < <(echo "${IMAGES}" | tr ' |' '\n\n' | sed '/^$/d' | head -7)
n=0
for u in "${URLS[@]}"; do
  if curl -fsSL -m 60 -o "raw.jpg" "$u"; then n=$((n+1)); mv raw.jpg "img$n.jpg"; else echo "skip $u"; fi
done
echo "photos downloaded: $n"
[ "$n" -ge 1 ] || { echo "no photos"; exit 1; }
for i in $(seq 1 $n); do : > c$i.txt; done
printf '%s' "${CAPTION:-}" | fold -s -w 24 > c1.txt
if [ "$n" -ge 2 ]; then printf 'Shop AlluredHomeCanvas\non Etsy' > c$n.txt; fi
for i in $(seq 1 $n); do
  if [ -s c$i.txt ]; then
    dt="drawtext=fontfile=$F:textfile=c$i.txt:fontsize=62:fontcolor=white:box=1:boxcolor=0x5B6B3Acc:boxborderw=26:x=(w-text_w)/2:y=h-text_h-110:line_spacing=14,"
  else dt=""; fi
  ffmpeg -v error -y -loop 1 -framerate 30 -i img$i.jpg -filter_complex "[0:v]split[a][b];[a]scale=$W:$H:force_original_aspect_ratio=increase,crop=$W:$H,boxblur=30:5[bg];[b]scale=2400:2400:force_original_aspect_ratio=increase,crop=2400:2400,zoompan=z='min(zoom+0.0012,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=60:s=1080x1080:fps=30[fg];[bg][fg]overlay=(W-w)/2:0,${dt}format=yuv420p[v]" -map "[v]" -t $SEG -an -c:v libx264 -preset veryfast -crf 20 g$i.mp4
done
if [ "$n" -eq 1 ]; then cp g1.mp4 ../video.mp4; exit 0; fi
inputs=""; filter=""; prev="[0]"
for i in $(seq 1 $n); do inputs="$inputs -i g$i.mp4"; done
for i in $(seq 1 $((n-1))); do
  off=$(python3 -c "print(round($i*($SEG-$XF),2))")
  if [ $i -eq $((n-1)) ]; then out="[v]"; tail=",format=yuv420p"; else out="[x$i]"; tail=""; fi
  filter="${filter}${prev}[$i]xfade=transition=fade:duration=$XF:offset=$off${tail}${out};"
  prev="[x$i]"
done
filter="${filter%;}"
ffmpeg -v error -y $inputs -filter_complex "$filter" -map "[v]" -an -c:v libx264 -preset veryfast -crf 20 -movflags +faststart ../video.mp4
ffprobe -v error -show_entries stream=width,height,duration -of csv=p=0 ../video.mp4
