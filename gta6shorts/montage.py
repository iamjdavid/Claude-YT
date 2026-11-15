"""Step 5: edit everything into a 1080x1920 Short with animated captions."""
from __future__ import annotations

import logging
import math
import random
import re
import subprocess
from pathlib import Path

from PIL import ImageFont

from . import config

log = logging.getLogger(__name__)
FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def pick_font() -> Path:
    custom = sorted((config.ASSETS / "fonts").glob("*.[ot]tf"))
    for p in custom + [Path(f) for f in FALLBACK_FONTS]:
        if p.exists():
            return p
    raise FileNotFoundError("No bold font found; drop a .ttf in assets/fonts/")


def _ass_escape(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words: list[dict], scenes, durations: list[float], hook: str, font_name: str, path: Path) -> None:
    W, H = config.WIDTH, config.HEIGHT
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,7,4,2,60,60,560,1
Style: Hook,{font_name},104,&H0000E5FF,&H00FFFFFF,&H00000000,&HC8000000,-1,0,0,0,100,100,1,0,3,18,0,8,70,70,250,1
Style: Punch,{font_name},84,&H00FFFFFF,&H00FFFFFF,&H002A1AE6,&H00000000,-1,0,0,0,100,100,1,-3,3,16,0,8,90,90,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev: list[str] = []
    pop = r"{\fad(80,0)\t(0,120,\fscx112\fscy112)\t(120,220,\fscx100\fscy100)}"
    ev.append(f"Dialogue: 2,{_ts(0)},{_ts(min(2.6, durations[0]))},Hook,,0,0,0,,{pop}{_ass_escape(hook.upper())}")

    t = 0.0
    for i, (sc, d) in enumerate(zip(scenes, durations)):
        if i > 0 and sc.on_screen_text.strip():
            ev.append(f"Dialogue: 1,{_ts(t)},{_ts(t + min(d, 2.4))},Punch,,0,0,0,,{pop}"
                      f"{_ass_escape(sc.on_screen_text.upper())}")
        t += d

    # group words into 1-3 word chunks, breaking at punctuation
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.,!?;:]$", w["text"]) or (
            len(cur) >= 2 and sum(len(x["text"]) for x in cur) > 14
        ):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else ch[-1]["end"] + 0.4
        chunk_end = min(ch[-1]["end"] + 0.25, nxt)
        for wi, w in enumerate(ch):
            start = w["start"]
            end = ch[wi + 1]["start"] if wi + 1 < len(ch) else chunk_end
            parts = []
            for k, x in enumerate(ch):
                txt = _ass_escape(x["text"].upper())
                parts.append(r"{\c&H0000E5FF&\fscx108\fscy108}" + txt + r"{\r}" if k == wi else txt)
            ev.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
    path.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")


def _segment(vis: dict, dur: float, idx: int, out: Path) -> None:
    W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS
    n = max(math.ceil(dur * FPS), 1)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]
    if vis["kind"] == "clip":
        _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-ss", f"{vis['start']:.2f}",
              "-i", str(vis["path"]), "-frames:v", str(n),
              "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1",
              *enc, str(out)])
        return
    moves = [
        (f"min(1+0.10*on/{n},1.10)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),          # push in
        (f"1.12-0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),                 # pull out
        ("1.12", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),                          # pan right
        ("1.12", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),                      # pan left
    ]
    z, x, y = moves[idx % len(moves)] if idx else moves[0]
    vf = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},"
          "eq=contrast=1.05:saturation=1.12,setsar=1")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(vis["path"]), "-vf", vf, "-frames:v", str(n), *enc, str(out)])


def render(visuals: list[dict], voice: dict, scenes, hook: str, workdir: Path, out_file: Path) -> Path:
    durations = list(voice["scene_durations"])
    durations[-1] += 0.5  # breathing room at the end
    segs = []
    for i, (vis, d) in enumerate(zip(visuals, durations)):
        seg = workdir / f"seg_{i:02d}.mp4"
        _segment(vis, d, i, seg)
        segs.append(seg)
    lst = workdir / "segments.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    video = workdir / "video_noaudio.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])

    font = pick_font()
    font_name = ImageFont.truetype(str(font), 20).getname()[0]
    ass = workdir / "captions.ass"
    build_ass(voice["words"], scenes, durations, hook, font_name, ass)

    total = sum(durations)
    music = sorted(p for p in (config.ASSETS / "music").glob("*") if p.suffix.lower() in AUDIO_EXT)
    inputs = ["-i", str(video), "-i", str(voice["audio"])]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        afilter = ("[1:a]apad,asplit=2[vo][sc];[2:a]volume=0.22[m];"
                   "[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
                   "[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        afilter = "[1:a]apad,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    vf = f"[0:v]ass='{ass.resolve()}':fontsdir='{font.parent.resolve()}'[v]"
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", f"{vf};{afilter}",
          "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(config.FPS),
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_file)])
    log.info("Rendered %s (%.1fs)", out_file, total)
    return out_file
