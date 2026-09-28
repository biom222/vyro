from functools import lru_cache
import os
from pathlib import Path
import sys

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SOURCE_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def _application_data_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    legacy = base / "ShortsStudio"
    # Keep existing installations on their original data directory without moving user media.
    return legacy if legacy.exists() else base / "vyro"


PROJECT_ROOT = _application_data_root() if getattr(sys, "frozen", False) else SOURCE_ROOT


class Settings(BaseSettings):
    app_name: str = "vyro"
    database_url: str = "sqlite:///./video_editor.sqlite3"

    # Local storage
    # Kept for old web-project configuration; desktop publishing uses direct APIs.
    taisly_api_key: str = Field(default="", repr=False)
    taisly_base_url: str = "https://app.taisly.com/api/private"
    upload_folder: Path = Path("./uploads")
    output_folder: Path = Path("./outputs")
    data_folder: Path = Path("./data")
    cache_folder: Path = Path("./cache")
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    max_file_size: int = Field(default=524_288_000, gt=0)
    max_video_duration: float = Field(default=600.0, gt=0)

    # AI content assistant. Mock mode is deterministic and needs no network.
    ai_provider: str = "mock"
    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-6-luna"

    # Local speech-to-text. Install requirements-ai.txt before selecting faster-whisper.
    transcription_provider: str = "mock"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"

    # YouTube discovery and analytics adapters.
    youtube_api_key: str = Field(default="", repr=False)
    youtube_region: str = "RU"
    youtube_language: str = "ru"
    youtube_access_token: str = Field(default="", repr=False)
    youtube_client_id: str = ""
    youtube_client_secret: str = Field(default="", repr=False)
    youtube_redirect_uri: str = "http://127.0.0.1:8765/oauth/callback"
    tiktok_client_key: str = ""
    tiktok_client_secret: str = Field(default="", repr=False)
    tiktok_redirect_uri: str = "http://127.0.0.1:8766/oauth/callback"
    instagram_app_id: str = ""
    instagram_app_secret: str = Field(default="", repr=False)
    instagram_redirect_uri: str = "http://127.0.0.1:8767/oauth/callback"
    instagram_graph_version: str = "v23.0"
    trends_mock_mode: bool = True
    credential_backend: str = "keyring"

    # Local publication scheduler.
    scheduler_enabled: bool = True
    scheduler_poll_seconds: float = Field(default=15.0, ge=1.0)
    scheduler_batch_size: int = Field(default=10, ge=1, le=100)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "taisly_api_key",
        "openai_api_key",
        "youtube_api_key",
        "youtube_access_token",
        "youtube_client_id",
        "youtube_client_secret",
        "tiktok_client_key",
        "tiktok_client_secret",
        "instagram_app_id",
        "instagram_app_secret",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("upload_folder", "output_folder", "data_folder", "cache_folder")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @field_validator("database_url")
    @classmethod
    def resolve_sqlite_database(cls, value: str) -> str:
        prefix = "sqlite:///./"
        if value.startswith(prefix):
            database_path = (PROJECT_ROOT / value.removeprefix(prefix)).resolve()
            return f"sqlite:///{database_path.as_posix()}"
        return value

    def ensure_directories(self) -> None:
        for folder in (
            self.upload_folder,
            self.output_folder,
            self.data_folder,
            self.cache_folder,
        ):
            folder.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
