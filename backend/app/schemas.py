from datetime import datetime
from pydantic import BaseModel, EmailStr


class Message(BaseModel):
    message: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class LabelOut(BaseModel):
    id: int
    recording_id: int
    label_type: str
    t_start_ms: int
    t_end_ms: int
    confidence: float
    payload_json: str

    class Config:
        from_attributes = True


class RecordingOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int
    status: str
    selected_device: str | None
    source_device_name: str | None
    sample_rate: int
    channels: int
    created_at: datetime

    class Config:
        from_attributes = True


class StreamControlResponse(BaseModel):
    status: str
    recording_id: int | None = None


class LiveStatusOut(BaseModel):
    is_active: bool
    status: str
    recording_id: int | None
    duration_ms: int
    last_error: str | None
    selected_device: int | None


class DeviceOut(BaseModel):
    id: int | None
    name: str
    max_input_channels: int
    default_samplerate: float


class ConfigureDeviceRequest(BaseModel):
    device_id: int | None


class TimelineSegmentOut(BaseModel):
    label_type: str
    t_start_ms: int
    t_end_ms: int


class RecordingTimelineOut(BaseModel):
    recording_id: int
    duration_ms: int
    is_active: bool
    segments: list[TimelineSegmentOut]
