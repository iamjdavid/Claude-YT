"""Step 6: everything you need to upload, in one folder."""
from __future__ import annotations

import json
import textwrap
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .montage import pick_font


def thumbnail(image: Path | None, hook: str, out: Path) -> Path:
    from .visuals import cover, procedural

    img = cover(Image.open(image)) if image else procedural(42)
    img = img.convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, img.width, img.height], fill=(0, 0, 0, 60))
    font = ImageFont.truetype(str(pick_font()), 150)
    lines = textwrap.wrap(hook.upper(), 12)[:3]
    y = img.height // 2 - len(lines) * 90
    for line in lines:
        w = d.textlength(line, font=font)
        d.text(((img.width - w) / 2, y), line, font=font, fill=(255, 229, 0),
               stroke_width=12, stroke_fill=(0, 0, 0))
        y += 180
    img.save(out, quality=92)
    return out


def write(out_dir: Path, script, brief: str, trending: list[dict], video: Path, visuals: list[dict]) -> dict:
    hashtags = " ".join(dict.fromkeys(script.hashtags + ["#Shorts"]))
    description = f"{script.description}\n\n{hashtags}"
    if script.sources:
        description += "\n\nSources:\n" + "\n".join(script.sources[:5])
    meta = {
        "date": date.today().isoformat(),
        "title": script.title[:100],
        "description": description[:4900],
        "tags": script.tags[:15],
        "hashtags": script.hashtags,
        "pinned_comment": script.pinned_comment,
        "topic": script.topic,
        "angle": script.angle,
        "category": "Gaming (20)",
        "made_for_kids": False,
        "altered_or_synthetic_content": True,
        "video_file": video.name,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    (out_dir / "research.json").write_text(json.dumps(trending, indent=2, ensure_ascii=False))

    first_img = next((v["path"] for v in visuals if v["kind"] == "image"), None)
    thumbnail(first_img, script.hook_text, out_dir / "thumbnail.jpg")

    script_md = [f"# {script.title}", "", f"**Topic:** {script.topic}", f"**Angle:** {script.angle}",
                 f"**Hook:** {script.hook_text}", "", "## Scenes"]
    for i, s in enumerate(script.scenes, 1):
        script_md += [f"{i}. {s.narration}", f"   - on-screen: {s.on_screen_text or '-'}",
                      f"   - visual: {s.image_prompt}"]
    script_md += ["", "## Research brief", brief]
    (out_dir / "script.md").write_text("\n".join(script_md))

    (out_dir / "UPLOAD.md").write_text(f"""# Ready to upload - {meta['date']}

1. YouTube Studio -> Create -> Upload video -> `{video.name}`
2. **Title:** {meta['title']}
3. **Description:** copy from `description.txt`
4. **Tags:** {', '.join(meta['tags'])}
5. Audience: **No, it's not made for kids**
6. Category: Gaming
7. Altered or synthetic content: **Yes** (AI voice / AI images)
8. Publish, then pin this comment: "{script.pinned_comment}"

Before publishing, read `script.md` once: double-check every claim marked as news is still accurate.
""")
    (out_dir / "description.txt").write_text(description)
    return meta
