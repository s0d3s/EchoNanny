from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.deps import get_current_user
from app.models import Label, Recording, User
from app.schemas import LabelOut, Message, RecordingOut, RecordingTimelineOut, TimelineSegmentOut

router = APIRouter(prefix="/recordings", tags=["recordings"])


def _merge_labels(labels: list[Label]) -> list[LabelOut]:
    threshold_ms = max(0, int(settings.labels_merging_threshold_seconds * 1000))
    merged: list[LabelOut] = []

    by_type: dict[str, list[Label]] = {}
    for label in labels:
        by_type.setdefault(label.label_type, []).append(label)

    for label_type, type_labels in by_type.items():
        _ = label_type
        ordered = sorted(type_labels, key=lambda l: (l.t_start_ms, l.t_end_ms))
        if not ordered:
            continue

        current = ordered[0]
        current_out = LabelOut(
            id=current.id,
            recording_id=current.recording_id,
            label_type=current.label_type,
            t_start_ms=current.t_start_ms,
            t_end_ms=current.t_end_ms,
            confidence=current.confidence,
            payload_json=current.payload_json,
        )

        for nxt in ordered[1:]:
            gap_ms = nxt.t_start_ms - current_out.t_end_ms
            if gap_ms <= threshold_ms:
                current_out.t_end_ms = max(current_out.t_end_ms, nxt.t_end_ms)
                current_out.confidence = max(current_out.confidence, nxt.confidence)
            else:
                merged.append(current_out)
                current_out = LabelOut(
                    id=nxt.id,
                    recording_id=nxt.recording_id,
                    label_type=nxt.label_type,
                    t_start_ms=nxt.t_start_ms,
                    t_end_ms=nxt.t_end_ms,
                    confidence=nxt.confidence,
                    payload_json=nxt.payload_json,
                )

        merged.append(current_out)

    return sorted(merged, key=lambda l: (l.t_start_ms, l.t_end_ms, l.label_type))


@router.get("", response_model=list[RecordingOut])
def list_recordings(
    query: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    label: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Recording).where(Recording.user_id == current_user.id)

    if from_date:
        stmt = stmt.where(Recording.started_at >= from_date)
    if to_date:
        stmt = stmt.where(Recording.started_at <= to_date)
    if query:
        stmt = stmt.where(Recording.file_path.ilike(f"%{query}%"))
    if label:
        stmt = stmt.join(Label).where(Label.label_type == label)

    stmt = stmt.order_by(Recording.started_at.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get("/active", response_model=RecordingOut | None)
def get_active_recording(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Recording)
        .where(Recording.user_id == current_user.id)
        .where(Recording.status == "active")
        .order_by(Recording.started_at.desc())
    )
    return db.execute(stmt).scalars().first()


@router.get("/{recording_id}", response_model=RecordingOut)
def get_recording(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.get(Recording, recording_id)
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recording not found")
    return rec


@router.delete("/{recording_id}", response_model=Message)
def delete_recording(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.get(Recording, recording_id)
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recording not found")

    if rec.status == "active":
        raise HTTPException(status_code=409, detail="Active recording cannot be deleted")

    file_path = Path(rec.file_path)
    if file_path.exists() and file_path.is_file():
        try:
            file_path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete recording file: {exc}") from exc

    db.delete(rec)
    db.commit()
    return Message(message="Recording deleted")


@router.get("/{recording_id}/labels", response_model=list[LabelOut])
def get_labels(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.get(Recording, recording_id)
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recording not found")

    stmt = select(Label).where(Label.recording_id == recording_id).order_by(Label.t_start_ms.asc())
    labels = list(db.execute(stmt).scalars().all())
    return _merge_labels(labels)


@router.get("/{recording_id}/timeline", response_model=RecordingTimelineOut)
def get_recording_timeline(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.get(Recording, recording_id)
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recording not found")

    stmt = select(Label).where(Label.recording_id == recording_id).order_by(Label.t_start_ms.asc())
    labels = list(db.execute(stmt).scalars().all())
    merged = _merge_labels(labels)
    segments = [TimelineSegmentOut(label_type=l.label_type, t_start_ms=l.t_start_ms, t_end_ms=l.t_end_ms) for l in merged]
    return RecordingTimelineOut(
        recording_id=recording_id,
        duration_ms=rec.duration_ms,
        is_active=rec.status == "active",
        segments=segments,
    )


@router.get("/{recording_id}/stream")
def stream_recording_file(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = db.get(Recording, recording_id)
    if not rec or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recording not found")

    ext = Path(rec.file_path).suffix.lower()
    media_type_by_ext = {
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }
    media_type = media_type_by_ext.get(ext, "application/octet-stream")
    return FileResponse(rec.file_path, media_type=media_type, filename=f"recording_{recording_id}{ext}")
