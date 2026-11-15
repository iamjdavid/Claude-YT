"""Step 3: voice-over (Microsoft Edge neural TTS, free) with word timings for captions."""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def _tts(text: str, mp3: Path) -> list[dict]:
    import edge_tts

    words: list[dict] = []
    comm = edge_tts.Communicate(text, config.TTS_VOICE, rate=config.TTS_RATE, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(
                    {
                        "text": chunk["text"],
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    }
                )
    return words


def _silent(text: str, wav: Path) -> list[dict]:
    """Dry-run stand-in: silence with evenly spaced fake word timings."""
    tokens = text.split()
    dur = max(len(tokens) / 2.7, 1.5)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{dur:.2f}", str(wav)],
        check=True,
    )
    step = dur / len(tokens)
    return [{"text": t, "start": i * step, "end": (i + 1) * step} for i, t in enumerate(tokens)]


def synthesize(narrations: list[str], workdir: Path, offline: bool = False) -> dict:
    """Returns {"audio": Path, "scene_durations": [...], "words": [...global timings...]}."""
    workdir.mkdir(parents=True, exist_ok=True)
    parts, durations, all_words = [], [], []
    t = 0.0
    for i, text in enumerate(narrations):
        if offline:
            path = workdir / f"vo_{i:02d}.wav"
            words = _silent(text, path)
        else:
            path = workdir / f"vo_{i:02d}.mp3"
            words = asyncio.run(_tts(text, path))
        d = probe_duration(path)
        parts.append(path)
        durations.append(d)
        all_words += [{**w, "start": w["start"] + t, "end": w["end"] + t, "scene": i} for w in words]
        t += d

    concat_list = workdir / "vo_list.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    audio = workdir / "narration.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-ar", "48000", "-ac", "2", str(audio)],
        check=True,
    )
    log.info("Voice-over: %.1fs across %d scenes", sum(durations), len(durations))
    return {"audio": audio, "scene_durations": durations, "words": all_words}
