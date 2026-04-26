from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_SETTINGS_ENV_KEYS = {
    "APP_NAME",
    "API_PREFIX",
    "SECRET_KEY",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "REFRESH_TOKEN_EXPIRE_MINUTES",
    "ALGORITHM",
    "INSTANCE_USER_EMAIL",
    "INSTANCE_USER_PASSWORD",
    "DATABASE_URL",
    "DATA_DIR",
    "RECORDINGS_DIR",
    "STREAM_SAMPLE_RATE",
    "STREAM_CHANNELS",
    "STREAM_CHUNK_MS",
    "USE_SYNTHETIC_AUDIO",
    "SYNTHETIC_AUDIO_STUB_NAME",
    "COMPRESS_FINISHED_RECORDINGS",
    "LABELS_MERGING_THRESHOLD_SECONDS",
    "AUTO_CUT_MIN_RECORDING_MINUTES",
    "AUTO_CUT_INACTIVE_WINDOW_MINUTES",
    "AUTO_CUT_LABEL_TYPES",
    "STARTUP_RECORDINGS_REPAIR_ENABLED",
    "WEB_UI_DIST_DIR",
    "CORS_ORIGINS",
}

_PREEXISTING_ENV_KEYS: set[str] = set()
_LOADED_ENV_KEYS: set[str] = set()
_LOADED_ENV_FILE: Path | None = None


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]

    return key, value


def _bootstrap_env() -> None:
    global _PREEXISTING_ENV_KEYS, _LOADED_ENV_KEYS, _LOADED_ENV_FILE

    _PREEXISTING_ENV_KEYS = set(os.environ.keys())

    explicit_env_file = os.environ.get("ECHONANNY_ENV_FILE", "").strip()
    env_path = Path(explicit_env_file) if explicit_env_file else Path.cwd() / ".env"

    if not env_path.exists() or not env_path.is_file():
        print(f"[config] env source: no .env file loaded (checked: {env_path})")
        return

    _LOADED_ENV_FILE = env_path.resolve()

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if not parsed:
            continue

        key, value = parsed
        if key in _SETTINGS_ENV_KEYS and key not in os.environ:
            os.environ[key] = value
            _LOADED_ENV_KEYS.add(key)

    print(f"[config] env source: loaded file {_LOADED_ENV_FILE}")


_bootstrap_env()


class Settings(BaseSettings):
    app_name: str = "EchoNanny"
    api_prefix: str = "/api"
    secret_key: str = "change-this-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 60 * 24 * 7
    algorithm: str = "HS256"
    instance_user_email: str = "admin@example.com"
    instance_user_password: str = "change-me-now-123"

    database_url: str = "sqlite:///./data/echonanny.db"
    data_dir: str = "./data"
    recordings_dir: str = "./data/audio"

    stream_sample_rate: int = 16000
    stream_channels: int = 1
    stream_chunk_ms: int = 20
    use_synthetic_audio: bool = False
    synthetic_audio_stub_name: str = "audio_stub.wav"
    compress_finished_recordings: bool = True
    labels_merging_threshold_seconds: float = 0.3
    auto_cut_min_recording_minutes: int = 45
    auto_cut_inactive_window_minutes: int = 10
    auto_cut_label_types: str = "speech"
    startup_recordings_repair_enabled: bool = True
    web_ui_dist_dir: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auto_cut_label_type_list(self) -> list[str]:
        return [t.strip().lower() for t in self.auto_cut_label_types.split(",") if t.strip()]

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.recordings_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()


def _log_settings_sources() -> None:
    for field_name in Settings.model_fields.keys():
        env_key = field_name.upper()

        if env_key in _PREEXISTING_ENV_KEYS:
            source = "os_env"
        elif env_key in _LOADED_ENV_KEYS and _LOADED_ENV_FILE is not None:
            source = f"env_file:{_LOADED_ENV_FILE}"
        else:
            source = "default"

        print(f"[config] {env_key} source={source}")


_log_settings_sources()
