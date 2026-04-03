import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

load_dotenv()

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"


def _load_yaml() -> dict:
    config_path = BASE_DIR / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml()
_tpl = _yaml.get("template", {})
_title = _yaml.get("title", {})
_org = _yaml.get("org", {})
_sub = _yaml.get("subtitle", {})
_dl = _yaml.get("download", {})
_gem = _yaml.get("gemini", {})
_wh = _yaml.get("whisper", {})


class Settings:
    # API Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # YouTube OAuth
    YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "client_secret.json")
    YOUTUBE_TOKEN_PATH: str = os.getenv("YOUTUBE_TOKEN_PATH", "token.pickle")

    # Template
    BG_COLOR: str = _tpl.get("bg_color", "#1B2A4A")
    CANVAS_WIDTH: int = _tpl.get("canvas_width", 1080)
    CANVAS_HEIGHT: int = _tpl.get("canvas_height", 1920)
    VIDEO_CRF: int = _tpl.get("video_crf", 23)
    VIDEO_PRESET: str = _tpl.get("video_preset", "medium")

    # Title
    TITLE_FONT_SIZE: int = _title.get("font_size", 54)
    TITLE_LINE_GAP: int = _title.get("line_gap", 30)
    TITLE_COLOR: str = _title.get("color", "white")
    TITLE_Y: int = _title.get("y", 80)
    TITLE_BORDER: int = _title.get("border_width", 3)
    TITLE_BORDER_COLOR: str = _title.get("border_color", "black")

    # Org name
    ORG_FONT_SIZE: int = _org.get("font_size", 38)
    ORG_COLOR: str = _org.get("color", "white")
    ORG_Y_OFFSET: int = _org.get("y_offset", 120)
    ORG_BORDER: int = _org.get("border_width", 2)
    ORG_BORDER_COLOR: str = _org.get("border_color", "black")
    ORG_LOGO_PATH: str = _org.get("logo_path", "")

    # Subtitle
    SUB_FONT_NAME: str = _sub.get("font_name", "Malgun Gothic")
    SUB_FONT_SIZE: int = _sub.get("font_size", 24)
    SUB_OUTLINE: int = _sub.get("outline", 2)
    SUB_MARGIN_V: int = _sub.get("margin_v", 340)

    # Download
    MAX_RESOLUTION: int = _dl.get("max_resolution", 1080)
    DOWNLOAD_FORMAT: str = _dl.get("format", "mp4")

    # Gemini
    GEMINI_MODEL: str = _gem.get("model", "gemini-2.5-flash")
    MAX_VIDEO_DURATION: int = _gem.get("max_video_duration", 3600)

    # Whisper
    WHISPER_MODEL: str = _wh.get("model", "whisper-1")
    WHISPER_LANG: str = _wh.get("language", "ko")

    # Font
    DEFAULT_FONT: str = str(FONTS_DIR / "BlackHanSans.ttf")
    FALLBACK_FONT: str = "/usr/share/fonts/truetype/custom/BlackHanSans.ttf"

    @classmethod
    def get_font(cls) -> str:
        if Path(cls.DEFAULT_FONT).exists():
            return cls.DEFAULT_FONT
        return cls.FALLBACK_FONT


settings = Settings()
