"""Step 4: one visual per scene.

Priority:
  1. Your own gameplay clips in assets/clips/ (best for the "clipping" niche, and you own them).
  2. OpenAI image generation (OPENAI_API_KEY) - highest quality AI images.
  3. Pollinations.ai (free, no key).
  4. Procedural neon artwork (offline fallback, never fails).
"""
from __future__ import annotations

import base64
import io
import logging
import math
import os
import random
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

from . import config
from .voice import probe_duration

log = logging.getLogger(__name__)
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def cover(img: Image.Image, w: int = config.WIDTH, h: int = config.HEIGHT) -> Image.Image:
    img = img.convert("RGB")
    s = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _openai(prompt: str) -> Image.Image:
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"), "prompt": prompt,
              "size": "1024x1536", "n": 1},
        timeout=180,
    )
    r.raise_for_status()
    return Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"])))


def _pollinations(prompt: str, seed: int) -> Image.Image:
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
    r = requests.get(
        url,
        params={"width": 1080, "height": 1920, "seed": seed, "nologo": "true", "model": "flux"},
        timeout=180,
    )
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def procedural(seed: int) -> Image.Image:
    rnd = random.Random(seed)
    w, h = config.WIDTH, config.HEIGHT
    top = (rnd.randint(20, 60), rnd.randint(0, 30), rnd.randint(60, 110))
    mid = (rnd.randint(200, 255), rnd.randint(40, 90), rnd.randint(120, 190))
    bot = (rnd.randint(240, 255), rnd.randint(140, 190), rnd.randint(40, 90))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.62)
    for y in range(horizon):
        f = y / horizon
        a, b, t = (top, mid, f * 2) if f < 0.5 else (mid, bot, (f - 0.5) * 2)
        d.line([(0, y), (w, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    sun_r = rnd.randint(180, 260)
    cx = rnd.randint(300, 780)
    d.ellipse([cx - sun_r, horizon - sun_r * 1.3, cx + sun_r, horizon + sun_r * 0.7], fill=(255, 200, 90))
    for i in range(8):  # retro sun stripes
        y = horizon - sun_r * 0.4 + i * 24
        d.rectangle([0, y, w, y + 6 + i], fill=mid)
    d.rectangle([0, horizon, w, h], fill=(18, 6, 40))
    for i in range(1, 22):  # perspective grid
        y = horizon + (h - horizon) * (i / 21) ** 2
        d.line([(0, y), (w, y)], fill=(255, 60, 200), width=2)
    for i in range(-12, 13):
        d.line([(w / 2, horizon), (w / 2 + i * 220, h)], fill=(255, 60, 200), width=2)
    for _ in range(rnd.randint(2, 4)):  # palm silhouettes
        px = rnd.choice([rnd.randint(-40, 260), rnd.randint(820, 1120)])
        base, top_y = horizon + 40, rnd.randint(int(h * 0.25), int(h * 0.4))
        d.line([(px, base), (px + rnd.randint(-60, 60), top_y)], fill=(10, 0, 25), width=26)
        tx = px + rnd.randint(-60, 60)
        for k in range(7):
            ang = math.pi * (0.1 + k * 0.13)
            d.line([(tx, top_y), (tx + math.cos(ang) * 230 * rnd.choice([-1, 1]), top_y + math.sin(ang) * 120)],
                   fill=(10, 0, 25), width=18)
    return img.filter(ImageFilter.GaussianBlur(1))


def _user_clips() -> list[Path]:
    d = config.ASSETS / "clips"
    return sorted(p for p in d.glob("*") if p.suffix.lower() in VIDEO_EXT)


def build(scenes, durations: list[float], workdir: Path, offline: bool = False) -> list[dict]:
    """Returns one dict per scene: {"kind": "image"|"clip", "path": Path, "start": float}."""
    workdir.mkdir(parents=True, exist_ok=True)
    clips = _user_clips()
    rnd = random.Random()
    out: list[dict] = []
    for i, (scene, dur) in enumerate(zip(scenes, durations)):
        if clips:
            clip = clips[i % len(clips)]
            length = probe_duration(clip)
            start = rnd.uniform(0, max(length - dur - 0.1, 0))
            out.append({"kind": "clip", "path": clip, "start": start})
            continue

        prompt = f"{scene.image_prompt}. {config.IMAGE_STYLE}"
        img = None
        providers = [] if offline else (
            [("openai", lambda: _openai(prompt))] if os.getenv("OPENAI_API_KEY") else []
        ) + [("pollinations", lambda: _pollinations(prompt, rnd.randint(1, 10**6)))]
        for name, fn in providers:
            for attempt in range(2):
                try:
                    img = fn()
                    log.info("Scene %d image via %s", i, name)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("Scene %d: %s attempt %d failed: %s", i, name, attempt + 1, e)
            if img:
                break
        if img is None:
            img = procedural(seed=i * 7919 + len(prompt))
            log.info("Scene %d image via procedural fallback", i)
        path = workdir / f"scene_{i:02d}.jpg"
        cover(img).save(path, quality=92)
        out.append({"kind": "image", "path": path, "start": 0.0})
    return out
