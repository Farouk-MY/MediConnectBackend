from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.core.database import engine, Base
from app.api.v1 import auth, patients, qr, doctors, appointments, availability, absences, payments, notifications, statistics, consultations, questionnaire
from app.core.websocket import profile_manager, schedule_manager, video_call_manager
from app.core.security import decode_token
from app.video_call_template import VIDEO_CALL_HTML
from app.services.scheduler import start_scheduler, stop_scheduler
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Create tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables, RAG service, and notification scheduler on startup."""
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    # Initialize RAG service for AI questionnaire
    try:
        from app.services.rag_service import rag_service
        await rag_service.initialize()
        logger.info("📚 RAG service initialized successfully")
    except Exception as e:
        logger.warning(f"⚠️ RAG service initialization failed (non-blocking): {e}")

    # Warm up AI model (pre-load into GPU memory)
    try:
        from app.services.ai_service import ai_service
        health = await ai_service.health_check()
        await ai_service.keepalive()
        logger.info(f"🧠 AI service ready: {health.get('active_provider', 'none')} | chain: {health.get('provider_chain', [])}")
    except Exception as e:
        logger.warning(f"⚠️ AI warmup failed (non-blocking): {e}")

    # Start notification scheduler
    start_scheduler()
    logger.info("🚀 MediConnect API started with notification scheduler")
    
    yield
    
    # Cleanup on shutdown
    stop_scheduler()
    await engine.dispose()


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="MediConnect API - Healthcare Management System",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if "*" not in settings.cors_origins else [],
    allow_origin_regex=".*" if "*" in settings.cors_origins else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/")
async def root():
    return {
        "message": "Welcome to MediConnect API",
        "version": "1.0.0",
        "status": "healthy"
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/health/ai")
async def ai_health_check():
    """Check Ollama + RAG health. No auth required."""
    from app.services.ai_service import ai_service
    from app.services.rag_service import rag_service

    ollama_health = await ai_service.health_check()
    rag_status = {
        "ready": rag_service.is_ready,
        "chunks_loaded": rag_service.chunk_count,
    }

    # Health check now reflects multi-provider architecture
    overall = "healthy"
    ai_status = ollama_health.get("status", "unknown")
    if ai_status == "error":
        overall = "unhealthy"
    elif not rag_status["ready"]:
        overall = "degraded"

    return {
        "status": overall,
        "ai": ollama_health,
        "rag": rag_status,
    }


# WebSocket endpoint for real-time profile updates
@app.websocket("/ws/profile/{user_id}")
async def websocket_profile(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(None)
):
    """
    WebSocket endpoint for real-time profile updates.
    
    Connect with: ws://host/ws/profile/{user_id}?token={access_token}
    """
    # Must accept the connection first before we can send close codes
    await websocket.accept()
    
    # Verify token
    try:
        if not token:
            await websocket.close(code=4001, reason="Token required")
            return
            
        payload = decode_token(token)
        if payload is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
            
        if payload.get("sub") != user_id:
            await websocket.close(code=4001, reason="Token mismatch")
            return
            
    except Exception as e:
        print(f"WebSocket auth error: {e}")
        await websocket.close(code=4001, reason="Authentication failed")
        return
    
    # Token valid, register connection
    await profile_manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive, wait for messages (ping/pong)
            data = await websocket.receive_text()
            # Echo back for ping-pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        profile_manager.disconnect(websocket, user_id)


# WebSocket endpoint for real-time schedule updates
@app.websocket("/ws/schedule/{doctor_id}")
async def websocket_schedule(
    websocket: WebSocket,
    doctor_id: str,
    token: str = Query(None)
):
    """
    WebSocket endpoint for real-time schedule updates.
    
    Connect with: ws://host/ws/schedule/{doctor_id}?token={access_token}
    
    Events:
    - schedule_update: Weekly schedule changed
    - absence_update: Absence created/updated/cancelled
    - appointment_update: Appointment status changed
    """
    await websocket.accept()
    
    # Verify token
    try:
        if not token:
            await websocket.close(code=4001, reason="Token required")
            return
            
        payload = decode_token(token)
        if payload is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
            
    except Exception as e:
        print(f"WebSocket auth error: {e}")
        await websocket.close(code=4001, reason="Authentication failed")
        return
    
    # Register connection
    await schedule_manager.connect_doctor(websocket, doctor_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        schedule_manager.disconnect_doctor(websocket, doctor_id)


# Video call page — serves the WebRTC HTML
@app.get("/video/call", response_class=HTMLResponse)
async def video_call_page():
    """Serve the WebRTC video call page. Config is read from URL query params by the HTML."""
    return HTMLResponse(content=VIDEO_CALL_HTML)


# WebSocket endpoint for video call signaling
@app.websocket("/ws/video/{room_id}")
async def websocket_video_call(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(None),
    role: str = Query("patient"),
    display_name: str = Query("User")
):
    """
    WebSocket endpoint for real-time video call signaling.
    
    Connect with: ws://host/ws/video/{room_id}?token={access_token}&role=patient&display_name=John
    
    Messages:
    - participant_joined: Someone joined the room
    - participant_left: Someone left the room
    - signal: WebRTC signaling data (SDP offers/answers, ICE candidates)
    """
    print(f"\n[WS-VIDEO] New connection: room={room_id}, role={role}, name={display_name}")
    await websocket.accept()
    print(f"[WS-VIDEO] Connection accepted")
    
    # Verify token
    try:
        if not token:
            print(f"[WS-VIDEO] No token provided, closing")
            await websocket.close(code=4001, reason="Token required")
            return
            
        payload = decode_token(token)
        if payload is None:
            print(f"[WS-VIDEO] Invalid token, closing")
            await websocket.close(code=4001, reason="Invalid token")
            return
        
        user_id = payload.get("sub")
        if not user_id:
            print(f"[WS-VIDEO] No user_id in token, closing")
            await websocket.close(code=4001, reason="Invalid token")
            return
        
        print(f"[WS-VIDEO] Auth OK: user_id={user_id}")
            
    except Exception as e:
        print(f"[WS-VIDEO] Auth error: {e}")
        await websocket.close(code=4001, reason="Authentication failed")
        return
    
    # Join the video room
    await video_call_manager.join_room(websocket, room_id, user_id, role, display_name)
    
    try:
        while True:
            data = await websocket.receive_text()
            import json as _json
            try:
                message = _json.loads(data)
                msg_type = message.get("type", "")
                
                if msg_type == "signal":
                    # Relay WebRTC signaling data
                    await video_call_manager.relay_signal(
                        room_id, user_id, message.get("data", {})
                    )
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    
            except _json.JSONDecodeError:
                if data == "ping":
                    await websocket.send_text("pong")
                    
    except WebSocketDisconnect:
        print(f"[WS-VIDEO] Disconnected: user={user_id}, role={role}")
        room = video_call_manager.leave_room(websocket, user_id)
        if room:
            await video_call_manager.notify_leave(room, user_id, role, display_name)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(patients.router, prefix="/api/v1")
app.include_router(qr.router, prefix="/api/v1")
app.include_router(doctors.router, prefix="/api/v1")
app.include_router(appointments.router, prefix="/api/v1")
app.include_router(availability.router, prefix="/api/v1")
app.include_router(availability.public_router, prefix="/api/v1")
app.include_router(absences.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(statistics.router, prefix="/api/v1")
app.include_router(consultations.router, prefix="/api/v1")
app.include_router(questionnaire.router, prefix="/api/v1")


