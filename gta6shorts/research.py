"""Step 1: find which GTA 6 Shorts are performing right now.

Sources, in order:
  1. YouTube Data API v3 (YOUTUBE_API_KEY) - accurate views + publish time.
  2. yt-dlp search scraping (no key) - fallback, fewer stats.
Claude's web search (in script.py) adds the latest news on top of this.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from . import config

log = logging.getLogger(__name__)
YT = "https://www.googleapis.com/youtube/v3"


def _iso_duration_seconds(d: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def from_youtube_api(api_key: str) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)
    ids: set[str] = set()
    for q in config.SEARCH_QUERIES:
        r = requests.get(
            f"{YT}/search",
            params={
                "key": api_key,
                "part": "id",
                "q": q,
                "type": "video",
                "videoDuration": "short",
                "order": "viewCount",
                "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "relevanceLanguage": "en",
                "maxResults": 25,
            },
            timeout=30,
        )
        r.raise_for_status()
        ids.update(i["id"]["videoId"] for i in r.json().get("items", []))

    videos: list[dict] = []
    id_list = list(ids)
    for i in range(0, len(id_list), 50):
        r = requests.get(
            f"{YT}/videos",
            params={
                "key": api_key,
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(id_list[i : i + 50]),
            },
            timeout=30,
        )
        r.raise_for_status()
        now = datetime.now(timezone.utc)
        for v in r.json().get("items", []):
            secs = _iso_duration_seconds(v["contentDetails"].get("duration", ""))
            if secs == 0 or secs > 180:
                continue
            published = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
            hours = max((now - published).total_seconds() / 3600, 1)
            stats = v.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            videos.append(
                {
                    "id": v["id"],
                    "url": f"https://youtube.com/shorts/{v['id']}",
                    "title": v["snippet"]["title"],
                    "channel": v["snippet"]["channelTitle"],
                    "tags": v["snippet"].get("tags", [])[:15],
                    "published": v["snippet"]["publishedAt"],
                    "duration_s": secs,
                    "views": views,
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "views_per_hour": round(views / hours),
                }
            )
    videos.sort(key=lambda v: v["views_per_hour"], reverse=True)
    return videos


def from_ytdlp() -> list[dict]:
    import yt_dlp

    out: dict[str, dict] = {}
    opts = {"quiet": True, "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for q in config.SEARCH_QUERIES[:4]:
            try:
                # results page filtered to "uploaded this week"
                url = ("https://www.youtube.com/results?search_query="
                       + requests.utils.quote(f"{q} #shorts") + "&sp=EgIIAw%253D%253D")
                info = ydl.extract_info(url, download=False)
            except Exception as e:  # noqa: BLE001
                log.warning("yt-dlp search failed for %r: %s", q, e)
                continue
            for e in info.get("entries") or []:
                if not e or not e.get("id"):
                    continue
                dur = e.get("duration") or 0
                if dur and dur > 180:
                    continue
                out[e["id"]] = {
                    "id": e["id"],
                    "url": f"https://youtube.com/shorts/{e['id']}",
                    "title": e.get("title", ""),
                    "channel": e.get("channel") or e.get("uploader") or "",
                    "duration_s": dur,
                    "views": e.get("view_count") or 0,
                    "views_per_hour": None,
                }
    return sorted(out.values(), key=lambda v: v["views"] or 0, reverse=True)


def find_trending(limit: int = 20) -> list[dict]:
    key = os.getenv("YOUTUBE_API_KEY")
    if key:
        try:
            vids = from_youtube_api(key)
            log.info("YouTube API: %d candidate Shorts", len(vids))
            if vids:
                return vids[:limit]
        except Exception as e:  # noqa: BLE001
            log.warning("YouTube API failed (%s), falling back to yt-dlp", e)
    try:
        vids = from_ytdlp()
        log.info("yt-dlp: %d candidate Shorts", len(vids))
        return vids[:limit]
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp failed: %s", e)
        return []
