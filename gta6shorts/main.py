"""Run the whole daily pipeline: research -> script -> voice -> visuals -> edit -> package (-> upload)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from datetime import date, datetime

from . import config, montage, package, research, script, upload, visuals, voice

log = logging.getLogger("gta6shorts")


def _history() -> list[dict]:
    try:
        return json.loads(config.STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="No paid/online generation: template script, silent voice, procedural images.")
    ap.add_argument("--upload", action="store_true", help="Upload to YouTube (or set AUTO_UPLOAD=1).")
    ap.add_argument("--keep-work", action="store_true", help="Keep intermediate files.")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stamp = date.today().isoformat()
    out_dir = config.OUTPUT_DIR / stamp
    if out_dir.exists():
        out_dir = config.OUTPUT_DIR / f"{stamp}_{datetime.now():%H%M%S}"
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    history = _history()
    log.info("1/6 Research: what is working in the niche")
    trending = research.find_trending()

    log.info("2/6 Script")
    if args.dry_run or not script.have_claude():
        if not args.dry_run:
            log.warning("No ANTHROPIC_API_KEY: using the offline template script")
        sc, brief = script.offline_script(trending), "(dry run - no research brief)"
    else:
        sc, brief = script.write_script(trending, [h["topic"] for h in history])
    log.info("Title: %s", sc.title)

    log.info("3/6 Voice-over")
    vo = voice.synthesize([s.narration for s in sc.scenes], work / "voice", offline=args.dry_run)

    log.info("4/6 Visuals")
    vis = visuals.build(sc.scenes, vo["scene_durations"], work / "images", offline=args.dry_run)

    log.info("5/6 Edit")
    video = montage.render(vis, vo, sc.scenes, sc.hook_text, work, out_dir / f"short_{stamp}.mp4")

    log.info("6/6 Package")
    meta = package.write(out_dir, sc, brief, trending, video, vis)

    if (args.upload or os.getenv("AUTO_UPLOAD") == "1") and not args.dry_run:
        if upload.configured():
            meta["youtube_id"] = upload.upload(video, meta, out_dir / "thumbnail.jpg")
            (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        else:
            log.warning("Upload requested but YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN are missing")

    if not args.dry_run:
        history.append({"date": stamp, "topic": sc.topic, "title": sc.title,
                        "youtube_id": meta.get("youtube_id")})
        config.STATE_FILE.write_text(json.dumps(history[-200:], indent=2, ensure_ascii=False))

    if args.keep_work:
        for img in (work / "images").glob("*.jpg"):
            shutil.copy(img, out_dir / img.name)
    else:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\nDONE -> {out_dir}\n  video: {video.name}\n  title: {meta['title']}")


if __name__ == "__main__":
    main()
