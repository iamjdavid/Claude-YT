"""Optional step 7: upload to YouTube with the Data API (needs one-time OAuth setup).

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (see scripts/get_youtube_token.py).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import config

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


def configured() -> bool:
    return all(os.getenv(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(video: Path, meta: dict, thumbnail: Path | None = None) -> str:
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": config.YT_CATEGORY_ID,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": config.YT_PRIVACY,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    log.info("Uploaded https://youtube.com/shorts/%s (%s)", vid, config.YT_PRIVACY)
    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail))).execute()
        except Exception as e:  # noqa: BLE001 - needs a verified channel
            log.warning("Thumbnail not set: %s", e)
    if meta.get("pinned_comment"):
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {
                "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": meta["pinned_comment"]}}}}).execute()
        except Exception as e:  # noqa: BLE001
            log.warning("Comment not posted: %s", e)
    return vid
