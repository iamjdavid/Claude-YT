"""Turn a livestream VOD (YouTube or Twitch) into vertical Shorts of its strongest moments.

    python -m gta6shorts.clips "https://www.twitch.tv/videos/123456789" --clips 5

How moments are found (per 5-second window across the whole stream):
  * chat speed      - messages per window (chat replay via chat-downloader / yt-dlp)
  * chat hype       - emotes/words like LUL, KEKW, OMG, W, CLIP, "!!!"
  * audio energy    - loudness spikes (shouting, explosions, music drops)
The top candidates are downloaded (only those minutes, not the full VOD), transcribed with
Whisper, and Claude picks the best ones, trims them and writes the titles.

Only clip streams you own or have the streamer's permission to clip.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import statistics
import subprocess
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from . import config
from .montage import build_ass, pick_font

log = logging.getLogger("gta6shorts.clips")
BIN = 5  # seconds per analysis window
CHAT_DELAY = 8  # chat reacts a few seconds after the moment happens
HYPE = re.compile(
    r"\b(LUL|LOL|LMAO+|LMFAO|KEKW|OMEGALUL|POG+|POGGERS|POGCHAMP|W+|HOLY|OMG|WTF|NO WAY|CLIP+ (IT|THAT)|"
    r"CLIP|JAJA+|XD+|SHEESH|INSANE)\b|[💀😂🤣🔥😱]|!{3,}|\?{3,}",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- download helpers
def _ydl_opts(**extra) -> dict:
    opts = {"quiet": True, "no_warnings": True}
    if os.getenv("YTDLP_COOKIES") and Path(os.environ["YTDLP_COOKIES"]).exists():
        opts["cookiefile"] = os.environ["YTDLP_COOKIES"]
    opts.update(extra)
    return opts


def stream_info(url: str) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("is_live"):
        raise SystemExit("The stream is still live. Run this once it has ended and the VOD is available.")
    return info


def fetch_chat(url: str, work: Path) -> list[tuple[float, str]]:
    msgs: list[tuple[float, str]] = []
    try:
        from chat_downloader import ChatDownloader

        for m in ChatDownloader().get_chat(url, message_types=["text_message"]):
            t = m.get("time_in_seconds")
            if t is not None and t >= 0:
                msgs.append((float(t), m.get("message") or ""))
        log.info("Chat via chat-downloader: %d messages", len(msgs))
    except Exception as e:  # noqa: BLE001
        log.warning("chat-downloader failed: %s", e)
    if msgs or "youtu" not in url:
        return msgs
    # YouTube fallback: yt-dlp live chat replay
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL(_ydl_opts(skip_download=True, writesubtitles=True, subtitleslangs=["live_chat"],
                                        outtmpl=str(work / "chat"))) as ydl:
            ydl.download([url])
        for line in (work / "chat.live_chat.json").read_text(encoding="utf-8").splitlines():
            d = json.loads(line).get("replayChatItemAction", {})
            for a in d.get("actions", []):
                r = a.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
                if r:
                    text = "".join(x.get("text", "") for x in r.get("message", {}).get("runs", []))
                    msgs.append((int(d.get("videoOffsetTimeMsec", 0)) / 1000, text))
        log.info("Chat via yt-dlp: %d messages", len(msgs))
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp chat replay failed: %s", e)
    return msgs


def audio_loudness(url: str, work: Path, duration: float) -> list[float]:
    """Mean loudness (dB RMS) per BIN seconds."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(format="bestaudio/worst", outtmpl=str(work / "audio.%(ext)s"))) as ydl:
            ydl.download([url])
        audio = next(work.glob("audio.*"))
    except Exception as e:  # noqa: BLE001
        log.warning("Audio download failed, using chat only: %s", e)
        return []
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-vn", "-ac", "1", "-af",
         f"aresample=8000,asetnsamples={8000 * BIN},astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    levels = [float(v) if v not in ("-inf", "inf") else -90.0
              for v in re.findall(r"RMS_level=(-?[\d.]+|-?inf)", proc.stdout)]
    audio.unlink(missing_ok=True)
    log.info("Audio loudness: %d windows", len(levels))
    return levels


# ---------------------------------------------------------------- moment detection
def _z(values: list[float]) -> list[float]:
    if len(values) < 2:
        return [0.0] * len(values)
    mu, sd = statistics.fmean(values), statistics.pstdev(values) or 1.0
    return [(v - mu) / sd for v in values]


def _smooth(v: list[float], k: int = 1) -> list[float]:
    return [statistics.fmean(v[max(0, i - k): i + k + 1]) for i in range(len(v))]


def find_moments(chat: list[tuple[float, str]], loudness: list[float], duration: float,
                 n: int, min_gap: float = 90) -> list[dict]:
    bins = max(math.ceil(duration / BIN), 1)
    count, hype = [0.0] * bins, [0.0] * bins
    samples: dict[int, list[str]] = {}
    for t, text in chat:
        b = int(max(t - CHAT_DELAY, 0) // BIN)
        if b < bins:
            count[b] += 1
            hype[b] += len(HYPE.findall(text))
            samples.setdefault(b, []).append(text)
    loud = (loudness + [min(loudness or [-90])] * bins)[:bins] if loudness else [0.0] * bins
    # chat activity is the strongest signal; audio breaks ties and covers chat-less VODs
    w_chat, w_hype, w_audio = (1.0, 0.7, 0.5) if chat else (0, 0, 1.0)
    score = [w_chat * c + w_hype * h + w_audio * a
             for c, h, a in zip(_smooth(_z(count)), _smooth(_z(hype)), _smooth(_z(loud)))]

    order = sorted(range(bins), key=lambda i: score[i], reverse=True)
    chosen: list[int] = []
    for i in order:
        if i * BIN < 30 or (duration - i * BIN) < 15:
            continue  # skip intro / outro edges
        if all(abs(i - j) * BIN >= min_gap for j in chosen):
            chosen.append(i)
        if len(chosen) == n:
            break
    moments = []
    for i in sorted(chosen):
        peak = i * BIN + BIN / 2
        near = [m for b in range(i - 1, i + 3) for m in samples.get(b, [])]
        near.sort(key=lambda m: not HYPE.search(m))  # hype messages first
        moments.append({
            "peak": peak,
            "start": max(peak - 40, 0),
            "end": min(peak + 20, duration),
            "score": round(score[i], 2),
            "chat_per_min": round(count[i] * 60 / BIN),
            "chat_sample": near[:40],
        })
    return moments


# ---------------------------------------------------------------- clip download + transcription
def download_section(url: str, start: float, end: float, out: Path) -> Path:
    import yt_dlp
    from yt_dlp.utils import download_range_func

    opts = _ydl_opts(
        format="bv*[height<=1080]+ba/b[height<=1080]/b",
        download_ranges=download_range_func(None, [(start, end)]),
        force_keyframes_at_cuts=True,
        merge_output_format="mp4",
        outtmpl=str(out.with_suffix(".%(ext)s")),
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return next(out.parent.glob(out.stem + ".*"))


_whisper = None


def transcribe(path: Path) -> tuple[list[dict], str]:
    """Word timings relative to the file start + detected language."""
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        _whisper = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segments, info = _whisper.transcribe(str(path), word_timestamps=True, vad_filter=True)
    words = [{"text": w.word.strip(), "start": w.start, "end": w.end}
             for s in segments for w in (s.words or []) if w.word.strip()]
    return words, info.language


# ---------------------------------------------------------------- Claude picks + trims
class ClipPick(BaseModel):
    candidate: int = Field(description="Index of the candidate")
    start: float = Field(description="Clip start, seconds from candidate file start")
    end: float = Field(description="Clip end, seconds from candidate file start (15-59s long)")
    title: str = Field(description="Max 70 chars, in the language spoken in the clip")
    hook_text: str = Field(description="Max 6 words shown on top of the video")
    description: str
    hashtags: list[str]
    tags: list[str]


class ClipPlan(BaseModel):
    clips: list[ClipPick]


def plan_with_claude(stream: dict, cands: list[dict], n: int) -> list[ClipPick]:
    import anthropic

    payload = [{
        "candidate": i,
        "file_length_s": round(c["end"] - c["start"], 1),
        "chat_peak_at_s": round(c["peak"] - c["start"], 1),
        "chat_per_min": c["chat_per_min"],
        "score": c["score"],
        "chat_sample": c["chat_sample"],
        "transcript": " ".join(f"[{w['start']:.1f}]{w['text']}" for w in c["words"]),
    } for i, c in enumerate(cands)]
    resp = anthropic.Anthropic().beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_format=ClipPlan,
        system="You are an expert Shorts/TikTok clipper for gaming livestreams (GTA niche). You pick moments "
               "that work out of context, start right before the action (no dead air), and end on the "
               "punchline or reaction. Titles are honest, curiosity-driven, no misleading claims.",
        messages=[{"role": "user", "content":
                   f"Stream: {stream.get('title')} by {stream.get('uploader') or stream.get('channel')}.\n"
                   f"Candidates (transcript words are prefixed with their timestamp in seconds):\n"
                   f"{json.dumps(payload, ensure_ascii=False)[:150000]}\n\n"
                   f"Choose the best {n} candidates (fewer if some are weak). For each, set start/end "
                   "inside the candidate file so the clip is 15-59 s, starts with the setup and ends on "
                   "the payoff. Then write the title, on-screen hook, description and tags."}],
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"Claude returned no plan (stop_reason={resp.stop_reason})")
    return resp.parsed_output.clips


def default_plan(stream: dict, cands: list[dict], n: int) -> list[ClipPick]:
    best = sorted(range(len(cands)), key=lambda i: cands[i]["score"], reverse=True)[:n]
    return [ClipPick(candidate=i, start=max(cands[i]["peak"] - cands[i]["start"] - 25, 0),
                     end=cands[i]["peak"] - cands[i]["start"] + 8,
                     title=f"{(stream.get('title') or 'Stream')[:55]} #{k + 1}", hook_text="WAIT FOR IT",
                     description="", hashtags=["#GTA6", "#Shorts"], tags=["gta 6", "stream highlights"])
            for k, i in enumerate(best)]


# ---------------------------------------------------------------- vertical render
def render_clip(src: Path, start: float, end: float, words: list[dict], hook: str, out: Path,
                layout: str, work: Path) -> Path:
    W, H = config.WIDTH, config.HEIGHT
    dur = end - start
    rel = [{**w, "start": w["start"] - start, "end": w["end"] - start}
           for w in words if w["start"] >= start and w["end"] <= end]
    font = pick_font()
    from PIL import ImageFont

    ass = work / f"{out.stem}.ass"
    build_ass(rel, [], [dur], hook, ImageFont.truetype(str(font), 20).getname()[0], ass)
    if layout == "crop":
        vf = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[base]"
    else:  # "blur": full 16:9 frame centred over a blurred, zoomed copy
        vf = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=25:2,eq=brightness=-0.08[bg];[b]scale={W}:-2[fg];"
              f"[bg][fg]overlay=0:(H-h)/2-120,setsar=1[base]")
    vf += f";[base]ass='{ass.resolve()}':fontsdir='{font.parent.resolve()}'[v]"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(config.FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)],
        check=True,
    )
    return out


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="Clip the best moments of a stream VOD into Shorts.")
    ap.add_argument("url")
    ap.add_argument("--clips", type=int, default=5, help="How many Shorts to produce")
    ap.add_argument("--layout", choices=["blur", "crop"], default="blur",
                    help="blur = whole frame over blurred background; crop = fill screen (cuts sides)")
    ap.add_argument("--candidates", type=int, default=0, help="Moments to analyse (default clips*2)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    info = stream_info(args.url)
    duration = float(info.get("duration") or 0)
    if not duration:
        raise SystemExit("Could not read the VOD duration.")
    slug = re.sub(r"[^a-z0-9]+", "-", (info.get("title") or "stream").lower())[:40].strip("-")
    out_dir = config.OUTPUT_DIR / "clips" / f"{date.today().isoformat()}_{slug}"
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    log.info("Stream: %s (%.0f min)", info.get("title"), duration / 60)

    log.info("1/5 Reading chat replay + audio energy")
    chat = fetch_chat(args.url, work)
    loud = audio_loudness(args.url, work, duration)
    if not chat and not loud:
        raise SystemExit("No chat and no audio available - cannot find highlights.")

    log.info("2/5 Finding peaks")
    cands = find_moments(chat, loud, duration, args.candidates or args.clips * 2)
    for c in cands:
        log.info("  candidate @ %s  score=%.2f chat/min=%d", _hms(c["peak"]), c["score"], c["chat_per_min"])

    log.info("3/5 Downloading only those moments + transcribing")
    for i, c in enumerate(cands):
        c["file"] = download_section(args.url, c["start"], c["end"], work / f"cand_{i:02d}")
        try:
            c["words"], c["language"] = transcribe(c["file"])
        except Exception as e:  # noqa: BLE001
            log.warning("Transcription failed for candidate %d: %s", i, e)
            c["words"], c["language"] = [], None

    log.info("4/5 Choosing and trimming the best clips")
    if os.getenv("ANTHROPIC_API_KEY"):
        picks = plan_with_claude(info, cands, args.clips)
    else:
        log.warning("No ANTHROPIC_API_KEY: using chat peaks with default trims and generic titles")
        picks = default_plan(info, cands, args.clips)

    log.info("5/5 Rendering vertical Shorts")
    credit = f"Clip from {info.get('uploader') or info.get('channel') or 'the'} stream: {info.get('webpage_url', args.url)}"
    results = []
    for k, p in enumerate(picks, 1):
        if not 0 <= p.candidate < len(cands):
            continue
        c = cands[p.candidate]
        length = c["end"] - c["start"]
        start, end = max(0.0, p.start), min(p.end, length, p.start + 59)
        if end - start < 5:
            continue
        mp4 = render_clip(c["file"], start, end, c["words"], p.hook_text, out_dir / f"clip_{k:02d}.mp4",
                          args.layout, work)
        hashtags = " ".join(dict.fromkeys(p.hashtags + ["#Shorts"]))
        meta = {
            "file": mp4.name,
            "title": p.title[:100],
            "description": f"{p.description}\n\n{credit}\n\n{hashtags}".strip(),
            "tags": p.tags[:15],
            "stream_timestamp": _hms(c["start"] + start),
            "chat_per_min": c["chat_per_min"],
            "language": c.get("language"),
        }
        (out_dir / f"clip_{k:02d}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        results.append(meta)
        log.info("clip_%02d: %s (%.0fs, stream @ %s)", k, p.title, end - start, meta["stream_timestamp"])

    (out_dir / "UPLOAD.md").write_text(
        "# Stream clips ready to upload\n\n" + "\n".join(
            f"## {r['file']}\n- **Title:** {r['title']}\n- **Moment in stream:** {r['stream_timestamp']}\n"
            f"- **Tags:** {', '.join(r['tags'])}\n- **Description:**\n\n```\n{r['description']}\n```\n"
            for r in results)
        + "\nOnly publish clips of streams you own or have permission to clip.\n")
    (out_dir / "candidates.json").write_text(json.dumps(
        [{k: v for k, v in c.items() if k not in ("file", "words")} for c in cands], indent=2, ensure_ascii=False))
    import shutil

    shutil.rmtree(work, ignore_errors=True)
    print(f"\nDONE -> {out_dir}  ({len(results)} clips)")


def _hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


if __name__ == "__main__":
    main()
