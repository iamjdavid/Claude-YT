"""Step 2: Claude studies today's trends + news and writes an original Short."""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import anthropic
from pydantic import BaseModel, Field

from . import config

log = logging.getLogger(__name__)
BETAS = ["server-side-fallback-2026-07-01"]


class Scene(BaseModel):
    narration: str = Field(description="Voice-over line for this scene, 1-2 short spoken sentences.")
    image_prompt: str = Field(
        description="Visual description for an AI image generator. Describe an original scene "
        "(places, vehicles, characters, mood). Never ask for logos, real brand marks or text."
    )
    on_screen_text: str = Field(description="Optional 1-4 word punch text, or empty string.")


class ShortScript(BaseModel):
    topic: str
    angle: str = Field(description="Why this should perform today, based on the research.")
    hook_text: str = Field(description="Max 6 words shown big on screen in the first 2 seconds.")
    scenes: list[Scene] = Field(description="5-8 scenes; the first narration line IS the hook.")
    title: str = Field(description="YouTube title, max 70 chars, curiosity-driven, no clickbait lies.")
    description: str = Field(description="2-4 sentence description ending with a question for comments.")
    hashtags: list[str] = Field(description="3-5 hashtags without spaces, e.g. #GTA6")
    tags: list[str] = Field(description="10-15 search tags.")
    pinned_comment: str
    sources: list[str] = Field(description="URLs used to verify facts.")


SYSTEM = f"""You are the head writer of a fast-growing YouTube Shorts channel in the niche: {config.NICHE}.
Audience: English-speaking gamers hyped about Grand Theft Auto VI.

Rules:
- Facts first. Clearly separate CONFIRMED info (Rockstar/Take-Two official) from leaks, rumors and
  fan theories ("rumor says", "leakers claim"). Never invent dates, prices, features or quotes.
- Original content only: write our own commentary/breakdown. Don't copy another creator's script or title.
- Shorts style: a hook in the first 1.5 seconds, one idea per scene, pattern interrupts, punchy
  conversational English, end with a loop or a question that drives comments.
- Total narration {config.TARGET_SECONDS[0]}-{config.TARGET_SECONDS[1]} seconds when read aloud (~110-140 words).
- No profanity in titles, no misleading thumbnails/titles, nothing that would break YouTube policies.
"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def research_brief(trending: list[dict], recent_topics: list[str]) -> str:
    """Claude + live web search -> short strategy brief for today's video."""
    today = date.today().isoformat()
    prompt = f"""Today is {today}.

Here are the GTA 6 Shorts with the most traction in the last {config.LOOKBACK_HOURS}h
(views_per_hour = velocity; null when unknown):
{json.dumps(trending, indent=1, ensure_ascii=False)[:20000]}

Topics our channel already covered recently (avoid repeating them unless there is genuinely new info):
{json.dumps(recent_topics[-30:], ensure_ascii=False)}

1. Use web search to check the latest GTA 6 news from the past few days (official Rockstar news,
   release/pre-order info, trailers, credible leaks, viral community discoveries).
2. Identify the 3 strongest patterns in the trending list (topics, hook styles, title formats).
3. Pick ONE topic for today's Short that combines proven demand with something fresh, and explain why.
Return a concise brief (max 300 words) with: chosen topic, key verified facts with source URLs,
hook ideas, and what to avoid."""
    client = _client()
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}]
    resp = None
    for _ in range(5):  # resume server-side tool loop on pause_turn
        resp = client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=BETAS,
            fallbacks="default",
            tools=tools,
            messages=messages,
        )
        if resp.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the research step: {resp.stop_details}")
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def write_script(trending: list[dict], recent_topics: list[str]) -> tuple[ShortScript, str]:
    brief = research_brief(trending, recent_topics)
    log.info("Research brief:\n%s", brief)
    client = _client()
    resp = client.beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        betas=BETAS,
        fallbacks="default",
        output_format=ShortScript,
        messages=[
            {
                "role": "user",
                "content": f"Research brief for today:\n\n{brief}\n\n"
                "Write today's Short following the brief. Image prompts must describe original, "
                "stylized scenes (no official artwork, no logos, no text in image) and should "
                "visually match each line of narration.",
            }
        ],
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Claude did not return a script (stop_reason={resp.stop_reason})")
    return resp.parsed_output, brief


def offline_script(trending: list[dict]) -> ShortScript:
    """Used by --dry-run (no API key) so the rest of the pipeline can be tested."""
    ref = trending[0]["title"] if trending else "GTA 6 hype"
    lines = [
        ("GTA 6 is days away, and one detail changes everything.", "Neon Vice-style skyline at dusk, sports car drifting", "DAYS AWAY"),
        ("Everyone is talking about the new map, and it is huge.", "Aerial view of sprawling tropical coastal city with highways", "HUGE MAP"),
        ("Two protagonists, one heist, zero room for mistakes.", "Two silhouettes in front of a convenience store at night", "2 LEADS"),
        ("The world reacts to you, from traffic to social media.", "Busy beach boulevard full of people filming on phones", ""),
        ("So, are you playing day one, or waiting for reviews? Tell me below.", "Gamer room lit by neon, controller on desk, city outside window", "DAY ONE?"),
    ]
    return ShortScript(
        topic=f"Dry run inspired by: {ref}",
        angle="Offline test script",
        hook_text="GTA 6 CHANGES EVERYTHING",
        scenes=[Scene(narration=n, image_prompt=p, on_screen_text=t) for n, p, t in lines],
        title="GTA 6: The Detail Everyone Missed",
        description="Test render of the automated pipeline. Are you playing day one?",
        hashtags=["#GTA6", "#GTAVI", "#Shorts"],
        tags=["gta 6", "gta vi", "grand theft auto 6", "gta 6 news", "gta 6 release"],
        pinned_comment="Day one or wait for reviews?",
        sources=[],
    )


def have_claude() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
