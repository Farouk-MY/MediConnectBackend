"""
WebSocket Connection Manager for Real-Time Updates
Handles WebSocket connections and broadcasts profile updates to connected clients.
"""

from typing import Dict, Set
from fastapi import WebSocket
import json


class ConnectionManager:
    """Manages WebSocket connections for real-time profile updates."""
    
    def __init__(self):
        # Maps user_id to set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """Register an already-accepted WebSocket connection for a user."""
        # Note: websocket.accept() is called in main.py before authentication
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        """Remove a WebSocket connection for a user."""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
    
    async def broadcast_to_user(self, user_id: str, data: dict):
        """Send data to all connections for a specific user."""
        if user_id not in self._connections:
            return
        
        disconnected = set()
        for websocket in self._connections[user_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.add(websocket)
        
        # Clean up disconnected websockets
        for ws in disconnected:
            self._connections[user_id].discard(ws)


class ScheduleConnectionManager:
    """Manages WebSocket connections for real-time schedule updates."""
    
    def __init__(self):
        # Maps doctor_id to set of active WebSocket connections
        self._doctor_connections: Dict[str, Set[WebSocket]] = {}
        # Maps patient_id to set of active WebSocket connections (for receiving schedule updates)
        self._patient_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect_doctor(self, websocket: WebSocket, doctor_id: str):
        """Register a WebSocket connection for a doctor."""
        if doctor_id not in self._doctor_connections:
            self._doctor_connections[doctor_id] = set()
        self._doctor_connections[doctor_id].add(websocket)
    
    def disconnect_doctor(self, websocket: WebSocket, doctor_id: str):
        """Remove a WebSocket connection for a doctor."""
        if doctor_id in self._doctor_connections:
            self._doctor_connections[doctor_id].discard(websocket)
            if not self._doctor_connections[doctor_id]:
                del self._doctor_connections[doctor_id]
    
    async def connect_patient(self, websocket: WebSocket, patient_id: str):
        """Register a WebSocket connection for a patient."""
        if patient_id not in self._patient_connections:
            self._patient_connections[patient_id] = set()
        self._patient_connections[patient_id].add(websocket)
    
    def disconnect_patient(self, websocket: WebSocket, patient_id: str):
        """Remove a WebSocket connection for a patient."""
        if patient_id in self._patient_connections:
            self._patient_connections[patient_id].discard(websocket)
            if not self._patient_connections[patient_id]:
                del self._patient_connections[patient_id]
    
    async def broadcast_to_doctor(self, doctor_id: str, data: dict):
        """Send schedule update to a specific doctor."""
        if doctor_id not in self._doctor_connections:
            return
        
        disconnected = set()
        for websocket in self._doctor_connections[doctor_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.add(websocket)
        
        for ws in disconnected:
            self._doctor_connections[doctor_id].discard(ws)
    
    async def broadcast_to_patients(self, patient_ids: list, data: dict):
        """Send schedule update to multiple patients."""
        for patient_id in patient_ids:
            if patient_id not in self._patient_connections:
                continue
            
            disconnected = set()
            for websocket in self._patient_connections[patient_id]:
                try:
                    await websocket.send_json(data)
                except Exception:
                    disconnected.add(websocket)
            
            for ws in disconnected:
                self._patient_connections[patient_id].discard(ws)
    
    async def broadcast_schedule_update(self, doctor_id: str, event_type: str, event_data: dict):
        """Broadcast a schedule update event."""
        data = {
            "type": "schedule_update",
            "event": event_type,
            "doctor_id": doctor_id,
            "data": event_data
        }
        await self.broadcast_to_doctor(doctor_id, data)
    
    async def broadcast_absence_event(self, doctor_id: str, event_type: str, absence_data: dict, affected_patient_ids: list = None):
        """Broadcast an absence event to doctor and affected patients."""
        data = {
            "type": "absence_update",
            "event": event_type,
            "doctor_id": doctor_id,
            "data": absence_data
        }
        
        # Notify doctor
        await self.broadcast_to_doctor(doctor_id, data)
        
        # Notify affected patients
        if affected_patient_ids:
            await self.broadcast_to_patients(affected_patient_ids, data)


# Global instances
profile_manager = ConnectionManager()
schedule_manager = ScheduleConnectionManager()


class VideoCallManager:
    """
    Manages WebSocket connections for real-time video call signaling.
    
    Handles:
    - Participant join/leave notifications
    - Call state synchronization between doctor and patient
    """
    
    def __init__(self):
        # Maps room_id to set of (websocket, user_id, role) tuples
        self._rooms: Dict[str, Set] = {}
        # Maps user_id to room_id for quick lookup
        self._user_rooms: Dict[str, str] = {}
    
    async def join_room(self, websocket: WebSocket, room_id: str, user_id: str, role: str, display_name: str):
        """Register a participant in a video call room."""
        print(f"\n{'='*60}")
        print(f"[VIDEO] JOIN_ROOM: user={user_id}, role={role}, name={display_name}")
        print(f"[VIDEO] room_id={room_id}")
        
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
            print(f"[VIDEO] Created new room: {room_id}")
        
        participant = (websocket, user_id, role, display_name)
        self._rooms[room_id].add(participant)
        self._user_rooms[user_id] = room_id
        
        # Log current room state
        current_participants = [(uid, r, dn) for (_, uid, r, dn) in self._rooms[room_id]]
        print(f"[VIDEO] Room now has {len(current_participants)} participants: {current_participants}")
        
        # Notify other participants
        print(f"[VIDEO] Broadcasting participant_joined to others in room...")
        await self._broadcast_to_room(room_id, {
            "type": "participant_joined",
            "user_id": user_id,
            "role": role,
            "display_name": display_name,
            "participant_count": len(self._rooms[room_id])
        }, exclude_user=user_id)
        
        # Send current participants to the new joiner
        participants = [
            {"user_id": uid, "role": r, "display_name": dn}
            for (_, uid, r, dn) in self._rooms[room_id]
            if uid != user_id
        ]
        print(f"[VIDEO] Sending room_state to new joiner: {len(participants)} existing participants")
        try:
            await websocket.send_json({
                "type": "room_state",
                "room_id": room_id,
                "participants": participants,
                "participant_count": len(self._rooms[room_id])
            })
            print(f"[VIDEO] room_state sent successfully")
        except Exception as e:
            print(f"[VIDEO] ERROR sending room_state: {e}")
        print(f"{'='*60}\n")
    
    def leave_room(self, websocket: WebSocket, user_id: str):
        """Remove a participant from their video call room."""
        room_id = self._user_rooms.pop(user_id, None)
        print(f"[VIDEO] LEAVE_ROOM: user={user_id}, room={room_id}")
        if not room_id or room_id not in self._rooms:
            return room_id
        
        # Remove participant
        self._rooms[room_id] = {
            p for p in self._rooms[room_id] if p[1] != user_id
        }
        
        remaining = len(self._rooms[room_id])
        print(f"[VIDEO] Room {room_id} now has {remaining} participants")
        
        # Clean up empty rooms
        if not self._rooms[room_id]:
            del self._rooms[room_id]
            print(f"[VIDEO] Room {room_id} deleted (empty)")
        
        return room_id
    
    async def notify_leave(self, room_id: str, user_id: str, role: str, display_name: str):
        """Notify remaining participants that someone left."""
        print(f"[VIDEO] NOTIFY_LEAVE: user={user_id}, role={role}, room={room_id}")
        if room_id not in self._rooms:
            return
        await self._broadcast_to_room(room_id, {
            "type": "participant_left",
            "user_id": user_id,
            "role": role,
            "display_name": display_name,
            "participant_count": len(self._rooms.get(room_id, set()))
        })
    
    async def relay_signal(self, room_id: str, from_user: str, signal_data: dict):
        """Relay WebRTC signaling data between participants."""
        signal_type = signal_data.get("type", "unknown")
        print(f"[VIDEO] RELAY_SIGNAL: from={from_user}, type={signal_type}, room={room_id}")
        if room_id not in self._rooms:
            print(f"[VIDEO] WARNING: Room {room_id} not found for relay!")
            return
        await self._broadcast_to_room(room_id, {
            "type": "signal",
            "from_user": from_user,
            "data": signal_data
        }, exclude_user=from_user)
    
    async def _broadcast_to_room(self, room_id: str, data: dict, exclude_user: str = None):
        """Send message to all participants in a room."""
        if room_id not in self._rooms:
            print(f"[VIDEO] BROADCAST: room {room_id} not found")
            return
        
        msg_type = data.get("type", "?")
        targets = [(uid, r) for (_, uid, r, _) in self._rooms[room_id] if uid != exclude_user]
        print(f"[VIDEO] BROADCAST '{msg_type}' to {len(targets)} targets: {targets} (excluding: {exclude_user})")
        
        disconnected = set()
        for participant in self._rooms[room_id]:
            ws, uid, _, _ = participant
            if uid == exclude_user:
                continue
            try:
                await ws.send_json(data)
                print(f"[VIDEO]   -> Sent '{msg_type}' to {uid} OK")
            except Exception as e:
                print(f"[VIDEO]   -> FAILED to send '{msg_type}' to {uid}: {e}")
                disconnected.add(participant)
        
        for p in disconnected:
            self._rooms[room_id].discard(p)


video_call_manager = VideoCallManager()

