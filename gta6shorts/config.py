"""Channel settings. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
STATE_FILE = ROOT / "state" / "history.json"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT / "output"))

NICHE = os.getenv("NICHE", "GTA 6 (Grand Theft Auto VI) clipping")
SEARCH_QUERIES = [
    q.strip()
    for q in os.getenv(
        "SEARCH_QUERIES",
        "GTA 6,GTA VI,GTA 6 gameplay,GTA 6 leak,GTA 6 trailer,GTA 6 secrets",
    ).split(",")
    if q.strip()
]
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "72"))
LANGUAGE = "en"

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
TTS_RATE = os.getenv("TTS_RATE", "+10%")

WIDTH, HEIGHT, FPS = 1080, 1920, 30
TARGET_SECONDS = (35, 55)

IMAGE_STYLE = os.getenv(
    "IMAGE_STYLE",
    "cinematic vertical 9:16 shot, modern open-world crime game aesthetic, "
    "neon sunset over a Miami-like Florida city, palm trees, humid haze, "
    "photorealistic, dramatic lighting, high detail, no text, no logos, no watermark",
)

# Upload defaults (only used if AUTO_UPLOAD=1 and YouTube OAuth secrets exist)
YT_PRIVACY = os.getenv("YT_PRIVACY", "private")
YT_CATEGORY_ID = "20"  # Gaming
