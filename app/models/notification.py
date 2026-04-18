"""
Notification Models

Database models for push notifications and device token management.
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class NotificationType(str, enum.Enum):
    """Types of notifications."""
    # Appointment lifecycle
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled"
    APPOINTMENT_COMPLETED = "appointment_completed"

    # Reminders
    REMINDER_24H = "reminder_24h"
    REMINDER_1H = "reminder_1h"
    REMINDER_30MIN = "reminder_30min"

    # Doctor-specific
    DAILY_SUMMARY = "daily_summary"
    PAYMENT_RECEIVED = "payment_received"

    # Absence
    DOCTOR_ABSENCE = "doctor_absence"

    # General
    GENERAL = "general"


class Notification(Base):
    """
    Persistent notification record.
    
    Stores all notifications sent to users for in-app notification history.
    """
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Notification content
    type = Column(Enum(NotificationType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)

    # Extra data (appointment_id, doctor_name, etc.)
    data = Column(JSON, default=dict)

    # Read tracking
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Notification {self.type.value} for user {self.user_id}>"


class DeviceToken(Base):
    """
    Expo push token for a user's device.
    
    Each user can have multiple devices (phone + tablet, etc.).
    Tokens are Expo push tokens like 'ExponentPushToken[xxx]'.
    """
    __tablename__ = "device_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Expo push token
    token = Column(String(255), nullable=False, unique=True)
    device_type = Column(String(20), nullable=True)  # 'ios', 'android'

    # Status
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DeviceToken {self.token[:30]}... for user {self.user_id}>"
