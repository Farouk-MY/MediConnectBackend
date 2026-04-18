"""
Notification API Routes

Endpoints for managing notifications and device tokens.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
    DeviceTokenRequest,
    DeviceTokenRemoveRequest,
    MarkReadRequest,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ==================== Notification List ====================

@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    unread_only: bool = Query(False, description="Only return unread notifications"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's notifications (paginated).
    
    Returns notifications sorted by most recent first.
    """
    offset = (page - 1) * page_size

    notifications, total, unread_count = await NotificationService.get_notifications(
        db=db,
        user_id=current_user.id,
        unread_only=unread_only,
        limit=page_size,
        offset=offset,
    )

    return NotificationListResponse(
        notifications=[
            NotificationResponse(
                id=n.id,
                type=n.type.value,
                title=n.title,
                body=n.body,
                data=n.data,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            for n in notifications
        ],
        unread_count=unread_count,
        total=total,
        page=page,
        page_size=page_size,
        has_next=offset + page_size < total,
    )


# ==================== Unread Count ====================

@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get unread notification count for badge display."""
    count = await NotificationService.get_unread_count(db, current_user.id)
    return UnreadCountResponse(count=count)


# ==================== Mark as Read ====================

@router.post("/mark-read")
async def mark_notifications_read(
    data: MarkReadRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark notifications as read.
    
    Pass specific notification_ids to mark individual notifications,
    or send empty/null to mark ALL as read.
    """
    updated = await NotificationService.mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_ids=data.notification_ids,
    )
    return {"message": f"{updated} notification(s) marked as read", "updated_count": updated}


# ==================== Device Token Management ====================

@router.post("/device-token")
async def register_device_token(
    data: DeviceTokenRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register an Expo push token for the current user.
    
    Call this on app launch after getting the Expo push token.
    If the token already exists, it will be reactivated and reassigned.
    """
    if not data.token.startswith("ExponentPushToken["):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Expo push token format. Expected: ExponentPushToken[xxx]",
        )

    device_token = await NotificationService.register_device_token(
        db=db,
        user_id=current_user.id,
        token=data.token,
        device_type=data.device_type,
    )

    return {
        "message": "Device token registered successfully",
        "token_id": str(device_token.id),
    }


@router.delete("/device-token")
async def remove_device_token(
    data: DeviceTokenRemoveRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deactivate a push token (call on logout).
    
    The user will stop receiving push notifications on this device.
    """
    removed = await NotificationService.remove_device_token(
        db=db,
        user_id=current_user.id,
        token=data.token,
    )

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device token not found",
        )

    return {"message": "Device token removed successfully"}
