"""
Notification Schemas

Pydantic schemas for notification API requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime


# ==================== Request Schemas ====================

class DeviceTokenRequest(BaseModel):
    """Register an Expo push token."""
    token: str = Field(..., description="Expo push token (ExponentPushToken[xxx])")
    device_type: Optional[str] = Field(None, description="Device type: 'ios' or 'android'")


class DeviceTokenRemoveRequest(BaseModel):
    """Remove a device token (on logout)."""
    token: str


class MarkReadRequest(BaseModel):
    """Mark specific notifications as read."""
    notification_ids: Optional[List[UUID]] = Field(None, description="Specific IDs to mark read. If empty, marks all as read.")


# ==================== Response Schemas ====================

class NotificationResponse(BaseModel):
    """Single notification in the list."""
    id: UUID
    type: str
    title: str
    body: str
    data: Optional[Dict[str, Any]] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated notification list."""
    notifications: List[NotificationResponse]
    unread_count: int
    total: int
    page: int
    page_size: int
    has_next: bool


class UnreadCountResponse(BaseModel):
    """Unread notification count for badge."""
    count: int
