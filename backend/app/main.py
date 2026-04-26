import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import wave

import av
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text

from app.api.auth import router as auth_router
from app.api.live import router as live_router
from app.api.recordings import router as recordings_router
from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import Base, engine
from app.db.session import SessionLocal
from app.models import Recording, User
from app.services.audio import audio_stream_manager


def _migrate_recordings_table() -> None:
    inspector = inspect(engine)
    if "recordings" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("recordings")}
    with engine.begin() as conn:
        if "status" not in cols:
            conn.execute(text("ALTER TABLE recordings ADD COLUMN status VARCHAR(20) DEFAULT 'finished'"))
            conn.execute(text("UPDATE recordings SET status='active' WHERE ended_at IS NULL"))
            conn.execute(text("UPDATE recordings SET status='finished' WHERE ended_at IS NOT NULL AND status IS NULL"))
        if "selected_device" not in cols:
            conn.execute(text("ALTER TABLE recordings ADD COLUMN selected_device VARCHAR(100)"))
        if "source_device_name" not in cols:
            conn.execute(text("ALTER TABLE recordings ADD COLUMN source_device_name VARCHAR(255)"))


def _probe_recording_duration_ms(file_path: str) -> int | None:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                if sample_rate <= 0:
                    return None
                return int((frame_count / sample_rate) * 1000)

        with av.open(str(path), mode="r") as container:
            if container.duration is not None:
                # PyAV reports container duration in microseconds.
                return int(container.duration / 1000)

            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream and stream.duration is not None and stream.time_base is not None:
                return int(float(stream.duration * stream.time_base) * 1000)
    except Exception:
        return None

    return None


def _repair_recordings_on_startup() -> None:
    db = SessionLocal()
    try:
        recordings = db.execute(select(Recording)).scalars().all()
        now_utc = datetime.utcnow()

        for rec in recordings:
            path = Path(rec.file_path)
            if not path.exists() or not path.is_file():
                db.delete(rec)
                continue

            if rec.status == "active":
                probed_duration_ms = _probe_recording_duration_ms(rec.file_path)
                if probed_duration_ms is not None:
                    duration_ms = max(0, int(probed_duration_ms))
                else:
                    duration_ms = max(0, int(rec.duration_ms or 0))

                if duration_ms <= 0 and rec.started_at:
                    duration_ms = max(0, int((now_utc - rec.started_at).total_seconds() * 1000))

                rec.duration_ms = duration_ms
                rec.status = "finished"

                if rec.started_at:
                    ended_at = rec.started_at + timedelta(milliseconds=duration_ms)
                    rec.ended_at = ended_at if ended_at >= rec.started_at else now_utc
                else:
                    rec.ended_at = now_utc

        db.commit()
    finally:
        db.close()


def _resolve_web_ui_dist_dir_or_raise() -> Path | None:
    raw = settings.web_ui_dist_dir.strip()
    if not raw:
        bundled = Path(__file__).resolve().parent / "webui"
        bundled_index = bundled / "index.html"
        if bundled.is_dir() and bundled_index.is_file():
            return bundled
        return None

    backend_root = Path(__file__).resolve().parents[1]
    configured = Path(raw)
    candidates: list[Path]

    if configured.is_absolute():
        candidates = [configured]
    else:
        candidates = [Path.cwd() / configured, backend_root / configured]

    for candidate in candidates:
        resolved = candidate.resolve()
        index_file = resolved / "index.html"
        if resolved.is_dir() and index_file.is_file():
            return resolved

    searched = ", ".join(str(c.resolve()) for c in candidates)
    raise RuntimeError(
        "WEB_UI_DIST_DIR is set, but no valid Web UI directory was found "
        f"(expected directory with index.html). Searched: {searched}"
    )


def create_app() -> FastAPI:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _migrate_recordings_table()
    web_ui_dist_dir = _resolve_web_ui_dist_dir_or_raise()

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(recordings_router, prefix=settings.api_prefix)
    app.include_router(live_router, prefix=settings.api_prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.on_event("startup")
    async def on_startup() -> None:
        db = SessionLocal()
        try:
            configured_email = settings.instance_user_email.strip().lower()
            configured_password = settings.instance_user_password

            user = db.execute(select(User).where(User.email == configured_email)).scalar_one_or_none()
            if user is None:
                db.query(User).delete()
                db.commit()
                user = User(email=configured_email, password_hash=get_password_hash(configured_password), is_active=True)
                db.add(user)
                db.commit()
            else:
                user.password_hash = get_password_hash(configured_password)
                user.is_active = True
                db.commit()

            extra_users = db.execute(select(User).where(User.email != configured_email)).scalars().all()
            for u in extra_users:
                db.delete(u)
            db.commit()
        finally:
            db.close()

        if settings.startup_recordings_repair_enabled:
            _repair_recordings_on_startup()

        audio_stream_manager.set_loop(asyncio.get_running_loop())
        audio_stream_manager.ensure_started_for_instance_user()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        audio_stream_manager.stop_all()

    if web_ui_dist_dir is not None:
        web_ui_dist_root = web_ui_dist_dir.resolve()
        web_ui_index = (web_ui_dist_root / "index.html").resolve()

        @app.get("/", include_in_schema=False)
        async def serve_web_ui_root():
            return FileResponse(str(web_ui_index))

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_web_ui_fallback(full_path: str):
            requested = (web_ui_dist_root / full_path).resolve()
            try:
                requested.relative_to(web_ui_dist_root)
            except ValueError:
                return FileResponse(str(web_ui_index))

            if requested.is_file():
                return FileResponse(str(requested))

            return FileResponse(str(web_ui_index))

    return app


app = create_app()
