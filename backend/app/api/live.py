from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.deps import get_current_user
from app.models import User
from app.schemas import ConfigureDeviceRequest, DeviceOut, LiveStatusOut, StreamControlResponse
from app.services.audio import audio_stream_manager

router = APIRouter(prefix="/live", tags=["live"])


@router.post("/start", response_model=StreamControlResponse)
def start_live(current_user: User = Depends(get_current_user)):
    recording_id = audio_stream_manager.start_for_user(current_user.id)
    return StreamControlResponse(status="started", recording_id=recording_id)


@router.post("/stop", response_model=StreamControlResponse)
def stop_live(current_user: User = Depends(get_current_user)):
    recording_id = audio_stream_manager.stop_for_user(current_user.id)
    return StreamControlResponse(status="stopped", recording_id=recording_id)


@router.get("/status", response_model=LiveStatusOut)
def live_status(current_user: User = Depends(get_current_user)):
    return LiveStatusOut(**audio_stream_manager.get_status_for_user(current_user.id))


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(current_user: User = Depends(get_current_user)):
    _ = current_user
    devices = audio_stream_manager.list_input_devices()
    return [DeviceOut(**d.__dict__) for d in devices]


@router.post("/configure", response_model=LiveStatusOut)
def configure_live_device(payload: ConfigureDeviceRequest, current_user: User = Depends(get_current_user)):
    status = audio_stream_manager.configure_device_for_user(current_user.id, payload.device_id)
    return LiveStatusOut(**status)


@router.websocket("/ws")
async def live_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    try:
        payload = decode_token(token)
    except ValueError:
        await websocket.close(code=4401)
        return

    if payload.get("type") != "access":
        await websocket.close(code=4401)
        return

    user_id = payload.get("sub")
    if user_id is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        await audio_stream_manager.subscribe(int(user_id), websocket)
    except RuntimeError:
        await websocket.send_json({"type": "error", "message": "Stream is not active. Call /api/live/start first."})
        await websocket.close(code=4404)
        return

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await audio_stream_manager.unsubscribe(int(user_id), websocket)
