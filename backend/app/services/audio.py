from __future__ import annotations

import asyncio
import fractions
import math
import queue
import struct
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import av
import webrtcvad
from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Label, Recording, User

try:
    if sys.platform.startswith("win"):
        import pyaudiowpatch as pyaudio
    else:
        import pyaudio
except Exception:  # pragma: no cover - environment dependent
    pyaudio = None


@dataclass
class DeviceInfo:
    id: int | None
    name: str
    max_input_channels: int
    default_samplerate: float


@dataclass
class StreamSession:
    user_id: int
    recording_id: int
    file_path: str
    selected_device: int | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    writer_thread: threading.Thread | None = None
    detector_thread: threading.Thread | None = None
    subscribers: set[WebSocket] = field(default_factory=set)
    detect_queue: queue.Queue[tuple[bytes, int, int]] = field(default_factory=lambda: queue.Queue(maxsize=500))
    started_at: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0
    status: str = "active"
    last_error: str | None = None


class AudioStreamManager:
    def __init__(self) -> None:
        self._sessions: dict[int, StreamSession] = {}
        self._device_preferences: dict[int, int | None] = {}
        self._compression_jobs: set[int] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _build_wav_path(self, user_id: int, now: datetime) -> Path:
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        user_dir = Path(settings.recordings_dir) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"rec_{timestamp}.wav"

    def _resolve_source_device_name(self, selected_device: int | None) -> str:
        if pyaudio is None:
            return "Default device" if selected_device is None else f"Device #{selected_device}"

        pa = None
        try:
            pa = pyaudio.PyAudio()
            if selected_device is None:
                try:
                    default_info = pa.get_default_input_device_info()
                    name = str(default_info.get("name", "")).strip()
                    if name:
                        return name
                except Exception:
                    return "Default device"
            else:
                info = pa.get_device_info_by_index(int(selected_device))
                if int(info.get("maxInputChannels", 0)) > 0:
                    name = str(info.get("name", "")).strip()
                    if name:
                        return name
        except Exception:
            pass
        finally:
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass

        return f"Device #{selected_device}"

    def _resolve_input_device_info(self, pa: Any, selected_device: int | None) -> tuple[int, dict[str, Any]]:
        """Resolve selected/default device to an actual input-capable device info.

        On Windows with pyaudiowpatch, selected device may be an output WASAPI endpoint;
        in that case resolve it to its loopback analogue.
        """
        if selected_device is None:
            info = pa.get_default_input_device_info()
            return int(info.get("index")), info

        info = pa.get_device_info_by_index(int(selected_device))
        max_input = int(info.get("maxInputChannels", 0))
        if max_input > 0:
            return int(info.get("index", selected_device)), info

        # pyaudiowpatch convenience: map selected output endpoint to WASAPI loopback input.
        if hasattr(pa, "get_wasapi_loopback_analogue_by_index"):
            loop_info = pa.get_wasapi_loopback_analogue_by_index(int(selected_device))
            return int(loop_info.get("index")), loop_info

        raise ValueError(f"Selected device #{selected_device} is not input-capable")

    def _create_recording(self, db: Session, user_id: int, selected_device: int | None, now: datetime) -> Recording:
        wav_path = self._build_wav_path(user_id, now)
        source_device_name = self._resolve_source_device_name(selected_device)
        rec = Recording(
            user_id=user_id,
            file_path=str(wav_path),
            started_at=now,
            sample_rate=settings.stream_sample_rate,
            channels=settings.stream_channels,
            duration_ms=0,
            status="active",
            selected_device=str(selected_device) if selected_device is not None else "default",
            source_device_name=source_device_name,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec

    def _should_auto_cut_recording(self, db, recording_id: int, duration_ms: int) -> bool:
        min_ms = max(0, int(settings.auto_cut_min_recording_minutes * 60 * 1000))
        if duration_ms < min_ms:
            return False

        inactive_window_ms = max(0, int(settings.auto_cut_inactive_window_minutes * 60 * 1000))
        monitored_types = settings.auto_cut_label_type_list
        if not monitored_types:
            return False

        window_start = max(0, duration_ms - inactive_window_ms)
        stmt = (
            select(Label.id)
            .where(Label.recording_id == recording_id)
            .where(Label.label_type.in_(monitored_types))
            .where(Label.t_end_ms > window_start)
            .limit(1)
        )
        has_recent_monitored_labels = db.execute(stmt).first() is not None
        return not has_recent_monitored_labels

    def _schedule_finished_recording_compression(self, recording_id: int) -> None:
        if not settings.compress_finished_recordings:
            return

        with self._lock:
            if recording_id in self._compression_jobs:
                return
            self._compression_jobs.add(recording_id)

        thread = threading.Thread(
            target=self._compress_finished_recording,
            args=(recording_id,),
            daemon=True,
        )
        thread.start()

    def _compress_finished_recording(self, recording_id: int) -> None:
        db = SessionLocal()
        old_path_str: str | None = None
        compressed_tmp_path: Path | None = None
        compressed_final_path: Path | None = None

        try:
            rec = db.get(Recording, recording_id)
            if not rec or rec.status != "finished":
                return

            old_path = Path(rec.file_path)
            old_path_str = rec.file_path
            if not old_path.exists() or old_path.suffix.lower() == ".m4a":
                return

            compressed_tmp_path = old_path.with_suffix(old_path.suffix + ".compressing.m4a")
            compressed_final_path = old_path.with_suffix(".m4a")

            if compressed_tmp_path.exists():
                compressed_tmp_path.unlink()

            if not self._compress_audio_to_m4a(old_path, compressed_tmp_path):
                return

            if compressed_final_path.exists():
                compressed_final_path.unlink()
            compressed_tmp_path.replace(compressed_final_path)

            rec.file_path = str(compressed_final_path)
            db.commit()

            try:
                old_path.unlink()
            except Exception:
                pass
        except Exception:
            db.rollback()
            if compressed_final_path is not None and old_path_str is not None:
                rec = db.get(Recording, recording_id)
                if rec and rec.file_path == str(compressed_final_path):
                    rec.file_path = old_path_str
                    db.commit()
            return
        finally:
            if compressed_tmp_path is not None and compressed_tmp_path.exists():
                try:
                    compressed_tmp_path.unlink()
                except Exception:
                    pass
            db.close()
            with self._lock:
                self._compression_jobs.discard(recording_id)

    def _compress_audio_to_m4a(self, src_path: Path, dst_path: Path) -> bool:
        try:
            with av.open(str(src_path), mode="r") as in_container:
                in_stream = next((s for s in in_container.streams if s.type == "audio"), None)
                if in_stream is None:
                    return False

                input_rate = int(in_stream.rate or settings.stream_sample_rate)
                input_channels = int(in_stream.channels or settings.stream_channels)
                layout_name = "mono" if input_channels == 1 else "stereo"
                if input_channels > 2:
                    layout_name = "stereo"

                with av.open(str(dst_path), mode="w", format="mp4") as out_container:
                    out_stream = out_container.add_stream("aac", rate=input_rate)
                    out_stream.bit_rate = 128_000
                    out_stream.layout = layout_name
                    out_stream.time_base = fractions.Fraction(1, input_rate)

                    resampler = av.audio.resampler.AudioResampler(
                        format="fltp",
                        layout=layout_name,
                        rate=input_rate,
                    )

                    for frame in in_container.decode(in_stream):
                        for resampled in resampler.resample(frame):
                            for packet in out_stream.encode(resampled):
                                out_container.mux(packet)

                    for packet in out_stream.encode(None):
                        out_container.mux(packet)

            return dst_path.exists()
        except Exception:
            return False

    def start_for_user(self, user_id: int) -> int:
        with self._lock:
            existing = self._sessions.get(user_id)
            if (
                existing
                and existing.writer_thread
                and existing.writer_thread.is_alive()
                and existing.status == "active"
            ):
                return existing.recording_id

            now = datetime.utcnow()

            selected_device = self._device_preferences.get(user_id)

            db = SessionLocal()
            try:
                rec = self._create_recording(db, user_id, selected_device, now)
                recording_id = rec.id
            finally:
                db.close()

            session = StreamSession(
                user_id=user_id,
                recording_id=recording_id,
                file_path=rec.file_path,
                selected_device=selected_device,
            )
            session.writer_thread = threading.Thread(target=self._writer_loop, args=(session,), daemon=True)
            session.detector_thread = threading.Thread(target=self._detector_loop, args=(session,), daemon=True)
            self._sessions[user_id] = session
            session.writer_thread.start()
            session.detector_thread.start()
            return recording_id

    def stop_for_user(self, user_id: int) -> int | None:
        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return None
            session.status = "stopping"
            session.stop_event.set()

        if session.writer_thread and session.writer_thread.is_alive():
            session.writer_thread.join(timeout=5)
        if session.detector_thread and session.detector_thread.is_alive():
            session.detector_thread.join(timeout=5)

        with self._lock:
            self._sessions.pop(user_id, None)
        return session.recording_id

    def stop_all(self) -> None:
        with self._lock:
            user_ids = list(self._sessions.keys())
        for uid in user_ids:
            self.stop_for_user(uid)

    def get_status_for_user(self, user_id: int) -> dict:
        with self._lock:
            session = self._sessions.get(user_id)
            preferred = self._device_preferences.get(user_id)
        if not session:
            return {
                "is_active": False,
                "status": "idle",
                "recording_id": None,
                "duration_ms": 0,
                "last_error": None,
                "selected_device": preferred,
            }
        return {
            "is_active": session.status == "active",
            "status": session.status,
            "recording_id": session.recording_id,
            "duration_ms": session.duration_ms,
            "last_error": session.last_error,
            "selected_device": session.selected_device,
        }

    async def subscribe(self, user_id: int, websocket: WebSocket) -> None:
        with self._lock:
            session = self._sessions.get(user_id)
            if not session or session.status != "active":
                raise RuntimeError("Stream is not active")
            session.subscribers.add(websocket)

    async def unsubscribe(self, user_id: int, websocket: WebSocket) -> None:
        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return
            session.subscribers.discard(websocket)

    def set_device_for_user(self, user_id: int, device_id: int | None) -> None:
        self._device_preferences[user_id] = device_id

    def configure_device_for_user(self, user_id: int, device_id: int | None) -> dict:
        self.set_device_for_user(user_id, device_id)

        with self._lock:
            active_session = self._sessions.get(user_id)
            should_restart = bool(
                active_session
                and active_session.status == "active"
                and active_session.writer_thread
                and active_session.writer_thread.is_alive()
            )

        if should_restart:
            self.stop_for_user(user_id)
            self.start_for_user(user_id)

        return self.get_status_for_user(user_id)

    def list_input_devices(self) -> list[DeviceInfo]:
        if pyaudio is None:
            return []

        pa = None
        try:
            pa = pyaudio.PyAudio()
            count = pa.get_device_count()
        except Exception:
            return []

        result: list[DeviceInfo] = []
        try:
            for idx in range(count):
                item = pa.get_device_info_by_index(idx)
                max_in = int(item.get("maxInputChannels", 0))
                if max_in <= 0:
                    continue
                result.append(
                    DeviceInfo(
                        id=idx,
                        name=str(item.get("name", f"Device {idx}")),
                        max_input_channels=max_in,
                        default_samplerate=float(item.get("defaultSampleRate", settings.stream_sample_rate)),
                    )
                )
        finally:
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass
        return result

    def ensure_started_for_instance_user(self) -> int | None:
        db = SessionLocal()
        try:
            configured_email = settings.instance_user_email.strip().lower()
            user = db.execute(select(User).where(User.email == configured_email)).scalar_one_or_none()
            if not user:
                return None
            return self.start_for_user(user.id)
        finally:
            db.close()

    def _writer_loop(self, session: StreamSession) -> None:
        target_chunk_samples = int(settings.stream_sample_rate * settings.stream_chunk_ms / 1000)

        def open_wav_writer(path: str):
            wav = wave.open(path, "wb")
            wav.setnchannels(settings.stream_channels)
            wav.setsampwidth(2)
            wav.setframerate(settings.stream_sample_rate)
            return wav

        wf = open_wav_writer(session.file_path)

        elapsed_ms = 0
        sequence = 0
        last_commit_monotonic = time.monotonic()
        last_auto_cut_check_monotonic = 0.0
        auto_cut_check_interval_sec = 5.0
        min_auto_cut_ms = max(0, int(settings.auto_cut_min_recording_minutes * 60 * 1000))

        db = SessionLocal()
        audio_stream = None
        pa_runtime = None
        reopen_attempt = 0
        stub_samples = self._load_stub_audio_samples() if settings.use_synthetic_audio else None
        stub_cursor = 0

        if settings.use_synthetic_audio and stub_samples is None:
            raise RuntimeError("Synthetic audio is enabled but stub samples were not loaded")

        stream_sample_rate = settings.stream_sample_rate
        stream_channels = settings.stream_channels
        stream_chunk_samples = target_chunk_samples

        def open_stream() -> Any | None:
            nonlocal stream_sample_rate, stream_channels, stream_chunk_samples
            nonlocal pa_runtime

            if settings.use_synthetic_audio or pyaudio is None:
                return None
            try:
                if pa_runtime is not None:
                    try:
                        pa_runtime.terminate()
                    except Exception:
                        pass
                pa_runtime = pyaudio.PyAudio()

                desired_rate = settings.stream_sample_rate
                desired_channels = max(1, settings.stream_channels)
                resolved_rate = desired_rate
                resolved_channels = desired_channels
                device_index: int | None = None
                device_info: dict[str, Any] | None = None

                try:
                    device_index, device_info = self._resolve_input_device_info(pa_runtime, session.selected_device)

                    max_input_channels = int(device_info.get("maxInputChannels", desired_channels))
                    default_samplerate = float(device_info.get("defaultSampleRate", desired_rate))
                    is_loopback = bool(device_info.get("isLoopbackDevice", False))

                    if is_loopback:
                        # Loopback endpoints are most stable at their native sample rate.
                        if default_samplerate > 0:
                            resolved_rate = int(default_samplerate)

                        # Prefer stereo for loopback; avoid forcing mono on multi-channel output endpoints.
                        resolved_channels = max(1, min(max_input_channels, 2)) if max_input_channels > 0 else 2
                    elif max_input_channels > 0:
                        resolved_channels = min(desired_channels, max_input_channels)

                    try:
                        pa_runtime.is_format_supported(
                            resolved_rate,
                            input_device=int(device_index),
                            input_channels=resolved_channels,
                            input_format=pyaudio.paInt16,
                        )
                    except Exception:
                        resolved_rate = int(default_samplerate) if default_samplerate > 0 else desired_rate
                except Exception:
                    pass

                stream_sample_rate = resolved_rate
                stream_channels = resolved_channels
                stream_chunk_samples = max(1, int(stream_sample_rate * settings.stream_chunk_ms / 1000))

                stream = pa_runtime.open(
                    format=pyaudio.paInt16,
                    rate=stream_sample_rate,
                    channels=stream_channels,
                    input=True,
                    frames_per_buffer=stream_chunk_samples,
                    input_device_index=int(device_index) if device_index is not None else None,
                )
                return stream
            except Exception as exc:
                session.last_error = f"audio_device_open_failed: {exc}"
                return None

        try:
            audio_stream = open_stream()
            while not session.stop_event.is_set():
                try:
                    if audio_stream is not None:
                        raw_input_chunk = audio_stream.read(stream_chunk_samples, exception_on_overflow=False)
                        chunk = self._normalize_input_chunk(
                            raw_input_chunk,
                            input_sample_rate=stream_sample_rate,
                            input_channels=stream_channels,
                            output_sample_rate=settings.stream_sample_rate,
                            output_channels=settings.stream_channels,
                            output_chunk_samples=target_chunk_samples,
                        )
                    else:
                        if settings.use_synthetic_audio:
                            assert stub_samples is not None
                            chunk, stub_cursor = self._stub_chunk(stub_samples, stub_cursor, target_chunk_samples)
                        else:
                            chunk = self._synthetic_chunk(sequence, target_chunk_samples)
                        time.sleep(settings.stream_chunk_ms / 1000)
                except Exception as exc:
                    session.last_error = f"audio_read_failed: {exc}"
                    if audio_stream is not None:
                        try:
                            audio_stream.stop_stream()
                            audio_stream.close()
                        except Exception:
                            pass
                    reopen_attempt += 1
                    time.sleep(min(5.0, 0.5 * reopen_attempt))
                    audio_stream = open_stream()
                    continue

                reopen_attempt = 0
                enhanced = self._enhance_chunk(chunk)
                wf.writeframes(chunk)
                self._broadcast(session, chunk)

                try:
                    session.detect_queue.put_nowait((enhanced, elapsed_ms, session.recording_id))
                except queue.Full:
                    try:
                        session.detect_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        session.detect_queue.put_nowait((enhanced, elapsed_ms, session.recording_id))
                    except queue.Full:
                        pass

                elapsed_ms += settings.stream_chunk_ms
                sequence += 1
                session.duration_ms = elapsed_ms

                now_monotonic = time.monotonic()
                if now_monotonic - last_commit_monotonic >= 1.0:
                    rec = db.get(Recording, session.recording_id)
                    if rec:
                        rec.duration_ms = elapsed_ms
                    db.commit()
                    last_commit_monotonic = now_monotonic

                should_check_auto_cut = (
                    elapsed_ms >= min_auto_cut_ms
                    and (now_monotonic - last_auto_cut_check_monotonic) >= auto_cut_check_interval_sec
                )
                if should_check_auto_cut:
                    last_auto_cut_check_monotonic = now_monotonic

                if should_check_auto_cut and self._should_auto_cut_recording(db, session.recording_id, elapsed_ms):
                    finished_recording_id = session.recording_id
                    rec = db.get(Recording, session.recording_id)
                    if rec:
                        rec.duration_ms = elapsed_ms
                        rec.ended_at = datetime.utcnow()
                        rec.status = "finished"
                    db.commit()
                    self._schedule_finished_recording_compression(finished_recording_id)

                    now = datetime.utcnow()
                    next_rec = self._create_recording(db, session.user_id, session.selected_device, now)

                    try:
                        wf.close()
                    except Exception:
                        pass

                    session.recording_id = next_rec.id
                    session.file_path = next_rec.file_path
                    session.started_at = now
                    session.duration_ms = 0
                    session.status = "active"
                    elapsed_ms = 0
                    sequence = 0
                    last_commit_monotonic = time.monotonic()
                    wf = open_wav_writer(session.file_path)

            rec = db.get(Recording, session.recording_id)
            if rec:
                rec.duration_ms = elapsed_ms
                rec.ended_at = datetime.utcnow()
                rec.status = "finished"
            db.commit()
            self._schedule_finished_recording_compression(session.recording_id)
            session.status = "finished"
        except Exception as exc:
            session.last_error = str(exc)
            session.status = "error"
            rec = db.get(Recording, session.recording_id)
            if rec:
                rec.ended_at = datetime.utcnow()
                rec.status = "error"
            db.commit()
        finally:
            if audio_stream is not None:
                try:
                    audio_stream.stop_stream()
                    audio_stream.close()
                except Exception:
                    pass
            if pa_runtime is not None:
                try:
                    pa_runtime.terminate()
                except Exception:
                    pass
            wf.close()
            db.close()
            session.stop_event.set()

    def _normalize_input_chunk(
        self,
        chunk: bytes,
        input_sample_rate: int,
        input_channels: int,
        output_sample_rate: int,
        output_channels: int,
        output_chunk_samples: int,
    ) -> bytes:
        audio = np.frombuffer(chunk, dtype=np.int16)
        if len(audio) == 0:
            return self._silence_chunk(output_chunk_samples)

        in_channels = max(1, input_channels)
        out_channels = max(1, output_channels)

        if len(audio) % in_channels != 0:
            valid = (len(audio) // in_channels) * in_channels
            audio = audio[:valid]
            if len(audio) == 0:
                return self._silence_chunk(output_chunk_samples)

        frames = audio.reshape(-1, in_channels).astype(np.float32)

        if in_channels != out_channels:
            if out_channels == 1:
                frames = np.mean(frames, axis=1, keepdims=True)
            elif in_channels == 1:
                frames = np.repeat(frames, out_channels, axis=1)
            else:
                frames = frames[:, :out_channels]

        if input_sample_rate != output_sample_rate and len(frames) > 1:
            ratio = output_sample_rate / float(input_sample_rate)
            target_len = max(1, int(round(len(frames) * ratio)))
            x_in = np.arange(len(frames), dtype=np.float32)
            x_out = np.linspace(0, len(frames) - 1, target_len, dtype=np.float32)

            if frames.shape[1] == 1:
                frames = np.interp(x_out, x_in, frames[:, 0]).reshape(-1, 1)
            else:
                channels: list[np.ndarray] = []
                for ch in range(frames.shape[1]):
                    channels.append(np.interp(x_out, x_in, frames[:, ch]))
                frames = np.stack(channels, axis=1)

        if len(frames) < output_chunk_samples:
            pad = np.zeros((output_chunk_samples - len(frames), frames.shape[1]), dtype=np.float32)
            frames = np.concatenate([frames, pad], axis=0)
        elif len(frames) > output_chunk_samples:
            frames = frames[:output_chunk_samples]

        output = np.clip(frames, -32768, 32767).astype(np.int16)
        return output.tobytes()

    def _detector_loop(self, session: StreamSession) -> None:
        vad = webrtcvad.Vad(2)
        speech_open = False
        loud_open = False
        speech_start_ts = 0
        loud_start_ts = 0
        current_recording_id = session.recording_id

        db = SessionLocal()
        pending: list[Label] = []
        last_flush = time.monotonic()

        try:
            while not (session.stop_event.is_set() and session.detect_queue.empty()):
                try:
                    enhanced, elapsed_ms, recording_id = session.detect_queue.get(timeout=0.2)
                except queue.Empty:
                    if pending and (time.monotonic() - last_flush) >= 1.0:
                        db.add_all(pending)
                        db.commit()
                        pending.clear()
                        last_flush = time.monotonic()
                    continue

                if recording_id != current_recording_id:
                    if speech_open:
                        pending.append(
                            Label(
                                recording_id=current_recording_id,
                                label_type="speech",
                                t_start_ms=speech_start_ts,
                                t_end_ms=elapsed_ms,
                                confidence=0.85,
                                payload_json="{}",
                            )
                        )
                    if loud_open:
                        pending.append(
                            Label(
                                recording_id=current_recording_id,
                                label_type="noise_event",
                                t_start_ms=loud_start_ts,
                                t_end_ms=elapsed_ms,
                                confidence=0.9,
                                payload_json='{"kind": "loud_peak"}',
                            )
                        )
                    if pending:
                        db.add_all(pending)
                        db.commit()
                        pending.clear()
                    speech_open = False
                    loud_open = False
                    speech_start_ts = 0
                    loud_start_ts = 0
                    current_recording_id = recording_id

                try:
                    is_speech = vad.is_speech(enhanced, settings.stream_sample_rate)
                except Exception:
                    is_speech = False

                dbfs = self._dbfs(enhanced)
                is_loud = dbfs > -22

                if is_speech and not speech_open:
                    speech_open = True
                    speech_start_ts = elapsed_ms
                elif not is_speech and speech_open:
                    pending.append(
                        Label(
                            recording_id=current_recording_id,
                            label_type="speech",
                            t_start_ms=speech_start_ts,
                            t_end_ms=elapsed_ms,
                            confidence=0.85,
                            payload_json="{}",
                        )
                    )
                    speech_open = False

                if is_loud and not loud_open:
                    loud_open = True
                    loud_start_ts = elapsed_ms
                elif not is_loud and loud_open:
                    pending.append(
                        Label(
                            recording_id=current_recording_id,
                            label_type="noise_event",
                            t_start_ms=loud_start_ts,
                            t_end_ms=elapsed_ms,
                            confidence=0.9,
                            payload_json='{"kind": "loud_peak"}',
                        )
                    )
                    loud_open = False

                now = time.monotonic()
                if pending and (len(pending) >= 25 or (now - last_flush) >= 1.0):
                    db.add_all(pending)
                    db.commit()
                    pending.clear()
                    last_flush = now

            final_ts = session.duration_ms
            if speech_open:
                pending.append(
                    Label(
                        recording_id=current_recording_id,
                        label_type="speech",
                        t_start_ms=speech_start_ts,
                        t_end_ms=final_ts,
                        confidence=0.85,
                        payload_json="{}",
                    )
                )
            if loud_open:
                pending.append(
                    Label(
                        recording_id=current_recording_id,
                        label_type="noise_event",
                        t_start_ms=loud_start_ts,
                        t_end_ms=final_ts,
                        confidence=0.9,
                        payload_json='{"kind": "loud_peak"}',
                    )
                )
            if pending:
                db.add_all(pending)
                db.commit()
        finally:
            db.close()

    def _synthetic_chunk(self, sequence: int, chunk_samples: int) -> bytes:
        sr = settings.stream_sample_rate
        t0 = sequence * chunk_samples / sr
        samples = []
        for i in range(chunk_samples):
            t = t0 + i / sr
            val = 0.15 * math.sin(2 * math.pi * 440 * t)
            if int(t) % 4 == 0:
                val += 0.25 * math.sin(2 * math.pi * 880 * t)
            pcm = max(-1.0, min(1.0, val))
            samples.append(int(pcm * 32767))
        return struct.pack("<" + "h" * len(samples), *samples)

    def _stub_chunk(self, samples: np.ndarray, cursor: int, chunk_samples: int) -> tuple[bytes, int]:
        if len(samples) == 0:
            return (self._synthetic_chunk(0, chunk_samples), cursor)

        end = cursor + chunk_samples
        if end <= len(samples):
            chunk = samples[cursor:end]
            next_cursor = end % len(samples)
        else:
            first = samples[cursor:]
            remaining = chunk_samples - len(first)
            second = samples[:remaining]
            chunk = np.concatenate([first, second])
            next_cursor = remaining % len(samples)
        return (chunk.astype(np.int16).tobytes(), next_cursor)

    def _silence_chunk(self, chunk_samples: int) -> bytes:
        return (np.zeros(chunk_samples, dtype=np.int16)).tobytes()

    def _load_stub_audio_samples(self) -> np.ndarray:
        stub_name = settings.synthetic_audio_stub_name.strip()
        if not stub_name:
            raise ValueError("SYNTHETIC_AUDIO_STUB_NAME must not be empty when USE_SYNTHETIC_AUDIO=true")

        base_dir = Path(__file__).resolve()
        candidates = [
            base_dir.parents[1] / "assets" / stub_name,  # app/assets (packaged)
            base_dir.parents[2] / "assets" / stub_name,  # backend/assets (source tree)
        ]

        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "app" / "assets" / stub_name)
            candidates.append(Path(meipass) / "assets" / stub_name)

        stub_path = next((p for p in candidates if p.exists()), candidates[0])
        if not stub_path.exists():
            raise FileNotFoundError(f"Synthetic audio stub not found: {stub_path}")

        with wave.open(str(stub_path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            source_sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if sample_width == 1:
            # 8-bit PCM WAV is unsigned [0..255], convert to signed int16.
            audio_u8 = np.frombuffer(frames, dtype=np.uint8).astype(np.int16)
            audio = ((audio_u8 - 128) << 8).astype(np.int16)
        elif sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16)
        else:
            raise ValueError(f"Unsupported WAV sample width ({sample_width}) in synthetic stub: {stub_path}")

        if channels > 1:
            audio = audio.reshape(-1, channels)[:, 0]

        if len(audio) == 0:
            raise ValueError(f"Synthetic audio stub has no samples: {stub_path}")

        if source_sr != settings.stream_sample_rate and len(audio) > 1:
            ratio = settings.stream_sample_rate / source_sr
            target_len = max(1, int(len(audio) * ratio))
            indices = np.linspace(0, len(audio) - 1, target_len)
            audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.int16)

        return audio

    def _enhance_chunk(self, chunk: bytes) -> bytes:
        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        gate = 500.0
        audio[np.abs(audio) < gate] = 0
        audio = np.clip(audio, -32768, 32767).astype(np.int16)
        return audio.tobytes()

    def _dbfs(self, chunk: bytes) -> float:
        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        if len(audio) == 0:
            return -120.0
        rms = np.sqrt(np.mean(np.square(audio)))
        if rms <= 1e-9:
            return -120.0
        return 20 * np.log10(rms / 32767.0)

    def _broadcast(self, session: StreamSession, chunk: bytes) -> None:
        if not self._loop:
            return
        with self._lock:
            subscribers = list(session.subscribers)
        for ws in subscribers:
            asyncio.run_coroutine_threadsafe(ws.send_bytes(chunk), self._loop)


audio_stream_manager = AudioStreamManager()
