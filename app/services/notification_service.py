"""
Notification Service

Business logic for creating, sending, and managing notifications.
Combines database persistence with Expo push delivery.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, update
from typing import Optional, List, Tuple
from uuid import UUID
from datetime import datetime
import logging

from app.models.notification import Notification, DeviceToken, NotificationType
from app.models.user import User
from app.core.notifications import send_push_notification, send_push_notifications_bulk

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for managing notifications."""

    # ==================== Core: Create & Send ====================

    @staticmethod
    async def create_and_send(
        db: AsyncSession,
        user_id: UUID,
        notification_type: NotificationType,
        title: str,
        body: str,
        data: Optional[dict] = None,
    ) -> Notification:
        """
        Create a notification record and send push to all user devices.
        
        This is the main entry point for all notifications.
        """
        logger.info(f"[NOTIFY] Creating notification for user {user_id}: {title}")
        
        # 1. Persist to DB — inject type into data for frontend icon matching
        enriched_data = {
            "type": notification_type.value,
            **(data or {}),
        }
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            data=enriched_data,
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        logger.info(f"[NOTIFY] Saved notification {notification.id} to DB")

        # 2. Send push to all active device tokens
        tokens = await NotificationService.get_user_push_tokens(db, user_id)
        
        if not tokens:
            logger.warning(f"[NOTIFY] No active push tokens for user {user_id} — notification saved to DB only (no push sent)")
            return notification
        
        logger.info(f"[NOTIFY] Found {len(tokens)} active token(s) for user {user_id}")
        
        push_data = {
            "notification_id": str(notification.id),
            "type": notification_type.value,
            **(data or {}),
        }

        for token_str in tokens:
            logger.info(f"[NOTIFY] Sending push to token: {token_str[:40]}...")
            success = await send_push_notification(
                token=token_str,
                title=title,
                body=body,
                data=push_data,
            )
            
            if success:
                logger.info(f"[NOTIFY] ✅ Push delivered to {token_str[:40]}...")
            else:
                logger.warning(f"[NOTIFY] ❌ Push failed for {token_str[:40]}...")
                await NotificationService._maybe_deactivate_token(db, token_str)

        return notification

    # ==================== Formatted Notification Helpers ====================

    @staticmethod
    async def notify_doctor_new_appointment(
        db: AsyncSession,
        doctor_user_id: UUID,
        patient_name: str,
        appointment_date: datetime,
        consultation_type: str,
        appointment_id: UUID,
    ):
        """Notify doctor about a new appointment booking."""
        date_str = appointment_date.strftime("%B %d, %Y at %H:%M")
        type_label = "in-person" if consultation_type == "presentiel" else "online"

        await NotificationService.create_and_send(
            db=db,
            user_id=doctor_user_id,
            notification_type=NotificationType.APPOINTMENT_BOOKED,
            title="📅 New Appointment",
            body=f"{patient_name} booked a {type_label} appointment for {date_str}",
            data={
                "appointment_id": str(appointment_id),
                "patient_name": patient_name,
                "appointment_date": appointment_date.isoformat(),
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_patient_confirmed(
        db: AsyncSession,
        patient_user_id: UUID,
        doctor_name: str,
        appointment_date: datetime,
        confirmation_code: str,
        appointment_id: UUID,
    ):
        """Notify patient that their appointment is confirmed."""
        date_str = appointment_date.strftime("%B %d, %Y at %H:%M")

        await NotificationService.create_and_send(
            db=db,
            user_id=patient_user_id,
            notification_type=NotificationType.APPOINTMENT_CONFIRMED,
            title="✅ Appointment Confirmed",
            body=f"Dr. {doctor_name} confirmed your appointment for {date_str}. Code: {confirmation_code}",
            data={
                "appointment_id": str(appointment_id),
                "doctor_name": doctor_name,
                "appointment_date": appointment_date.isoformat(),
                "confirmation_code": confirmation_code,
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_appointment_cancelled(
        db: AsyncSession,
        target_user_id: UUID,
        cancelled_by_role: str,
        other_party_name: str,
        appointment_date: datetime,
        reason: Optional[str],
        appointment_id: UUID,
    ):
        """Notify the other party about appointment cancellation."""
        date_str = appointment_date.strftime("%B %d, %Y at %H:%M")
        
        if cancelled_by_role == "doctor":
            title = "❌ Appointment Cancelled by Doctor"
            body = f"Dr. {other_party_name} cancelled your appointment for {date_str}"
        else:
            title = "❌ Appointment Cancelled"
            body = f"{other_party_name} cancelled their appointment for {date_str}"
        
        if reason:
            body += f". Reason: {reason}"

        await NotificationService.create_and_send(
            db=db,
            user_id=target_user_id,
            notification_type=NotificationType.APPOINTMENT_CANCELLED,
            title=title,
            body=body,
            data={
                "appointment_id": str(appointment_id),
                "cancelled_by": cancelled_by_role,
                "reason": reason,
                "screen": "appointments",
            },
        )

    @staticmethod
    async def notify_doctor_rescheduled(
        db: AsyncSession,
        doctor_user_id: UUID,
        patient_name: str,
        new_date: datetime,
        appointment_id: UUID,
    ):
        """Notify doctor that a patient rescheduled their appointment."""
        date_str = new_date.strftime("%B %d, %Y at %H:%M")

        await NotificationService.create_and_send(
            db=db,
            user_id=doctor_user_id,
            notification_type=NotificationType.APPOINTMENT_RESCHEDULED,
            title="🔄 Appointment Rescheduled",
            body=f"{patient_name} rescheduled their appointment to {date_str}",
            data={
                "appointment_id": str(appointment_id),
                "patient_name": patient_name,
                "new_date": new_date.isoformat(),
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_patient_completed(
        db: AsyncSession,
        patient_user_id: UUID,
        doctor_name: str,
        appointment_id: UUID,
    ):
        """Notify patient that their appointment is marked as completed."""
        await NotificationService.create_and_send(
            db=db,
            user_id=patient_user_id,
            notification_type=NotificationType.APPOINTMENT_COMPLETED,
            title="✅ Consultation Complete",
            body=f"Your consultation with Dr. {doctor_name} has been completed. Thank you!",
            data={
                "appointment_id": str(appointment_id),
                "doctor_name": doctor_name,
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_patient_absence(
        db: AsyncSession,
        patient_user_id: UUID,
        doctor_name: str,
        absence_start: str,
        absence_end: str,
        absence_type: str,
        appointment_id: Optional[UUID] = None,
    ):
        """Notify patient about doctor absence affecting their appointment."""
        await NotificationService.create_and_send(
            db=db,
            user_id=patient_user_id,
            notification_type=NotificationType.DOCTOR_ABSENCE,
            title="⚠️ Doctor Unavailable",
            body=f"Dr. {doctor_name} will be unavailable from {absence_start} to {absence_end} ({absence_type}). Your appointment may be affected.",
            data={
                "doctor_name": doctor_name,
                "absence_start": absence_start,
                "absence_end": absence_end,
                "appointment_id": str(appointment_id) if appointment_id else None,
                "screen": "appointments",
            },
        )

    @staticmethod
    async def notify_reminder_24h(
        db: AsyncSession,
        patient_user_id: UUID,
        doctor_name: str,
        appointment_date: datetime,
        consultation_type: str,
        appointment_id: UUID,
    ):
        """Send 24-hour reminder to patient."""
        date_str = appointment_date.strftime("%B %d at %H:%M")
        type_label = "in-person" if consultation_type == "presentiel" else "online"

        await NotificationService.create_and_send(
            db=db,
            user_id=patient_user_id,
            notification_type=NotificationType.REMINDER_24H,
            title="⏰ Appointment Tomorrow",
            body=f"Reminder: You have a {type_label} appointment with Dr. {doctor_name} tomorrow at {date_str}",
            data={
                "appointment_id": str(appointment_id),
                "doctor_name": doctor_name,
                "appointment_date": appointment_date.isoformat(),
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_reminder_1h(
        db: AsyncSession,
        patient_user_id: UUID,
        doctor_name: str,
        appointment_date: datetime,
        consultation_type: str,
        appointment_id: UUID,
    ):
        """Send 1-hour reminder to patient."""
        type_label = "in-person" if consultation_type == "presentiel" else "online"
        time_str = appointment_date.strftime("%H:%M")

        await NotificationService.create_and_send(
            db=db,
            user_id=patient_user_id,
            notification_type=NotificationType.REMINDER_1H,
            title="⏰ Appointment in 1 Hour",
            body=f"Your {type_label} appointment with Dr. {doctor_name} starts at {time_str}. Get ready!",
            data={
                "appointment_id": str(appointment_id),
                "doctor_name": doctor_name,
                "appointment_date": appointment_date.isoformat(),
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_doctor_reminder_30min(
        db: AsyncSession,
        doctor_user_id: UUID,
        patient_name: str,
        appointment_date: datetime,
        consultation_type: str,
        appointment_id: UUID,
    ):
        """Send 30-minute reminder to doctor."""
        type_label = "in-person" if consultation_type == "presentiel" else "online"
        time_str = appointment_date.strftime("%H:%M")

        await NotificationService.create_and_send(
            db=db,
            user_id=doctor_user_id,
            notification_type=NotificationType.REMINDER_30MIN,
            title="⏰ Appointment in 30 min",
            body=f"You have a {type_label} appointment with {patient_name} at {time_str}",
            data={
                "appointment_id": str(appointment_id),
                "patient_name": patient_name,
                "appointment_date": appointment_date.isoformat(),
                "screen": "appointment_detail",
            },
        )

    @staticmethod
    async def notify_doctor_daily_summary(
        db: AsyncSession,
        doctor_user_id: UUID,
        appointment_count: int,
        first_time: str,
        last_time: str,
        date_str: str,
    ):
        """Send daily summary to doctor about tomorrow's appointments."""
        if appointment_count == 1:
            body = f"You have 1 appointment tomorrow ({date_str}) at {first_time}"
        else:
            body = f"You have {appointment_count} appointments tomorrow ({date_str}), from {first_time} to {last_time}"

        await NotificationService.create_and_send(
            db=db,
            user_id=doctor_user_id,
            notification_type=NotificationType.DAILY_SUMMARY,
            title="📋 Tomorrow's Schedule",
            body=body,
            data={
                "appointment_count": appointment_count,
                "date": date_str,
                "screen": "schedule",
            },
        )

    @staticmethod
    async def notify_payment_received(
        db: AsyncSession,
        doctor_user_id: UUID,
        patient_name: str,
        amount: float,
        currency: str,
        appointment_id: UUID,
    ):
        """Notify doctor about payment received."""
        await NotificationService.create_and_send(
            db=db,
            user_id=doctor_user_id,
            notification_type=NotificationType.PAYMENT_RECEIVED,
            title="💳 Payment Received",
            body=f"Payment of {amount} {currency} received from {patient_name}",
            data={
                "appointment_id": str(appointment_id),
                "patient_name": patient_name,
                "amount": amount,
                "currency": currency,
                "screen": "appointment_detail",
            },
        )

    # ==================== Query & Management ====================

    @staticmethod
    async def get_notifications(
        db: AsyncSession,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Notification], int, int]:
        """
        Get paginated notifications for a user.
        
        Returns: (notifications, total_count, unread_count)
        """
        query = select(Notification).where(Notification.user_id == user_id)
        count_query = select(func.count(Notification.id)).where(Notification.user_id == user_id)
        
        if unread_only:
            query = query.where(Notification.is_read == False)
            count_query = count_query.where(Notification.is_read == False)

        # Get total
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Get unread count
        unread_result = await db.execute(
            select(func.count(Notification.id)).where(
                and_(Notification.user_id == user_id, Notification.is_read == False)
            )
        )
        unread_count = unread_result.scalar() or 0

        # Get paginated results
        query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        notifications = result.scalars().all()

        return notifications, total, unread_count

    @staticmethod
    async def get_unread_count(db: AsyncSession, user_id: UUID) -> int:
        """Get unread notification count for badge."""
        result = await db.execute(
            select(func.count(Notification.id)).where(
                and_(Notification.user_id == user_id, Notification.is_read == False)
            )
        )
        return result.scalar() or 0

    @staticmethod
    async def mark_as_read(
        db: AsyncSession,
        user_id: UUID,
        notification_ids: Optional[List[UUID]] = None,
    ) -> int:
        """
        Mark notifications as read.
        
        If notification_ids is None, marks ALL as read.
        Returns count of updated notifications.
        """
        now = datetime.utcnow()

        if notification_ids:
            stmt = (
                update(Notification)
                .where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.id.in_(notification_ids),
                        Notification.is_read == False,
                    )
                )
                .values(is_read=True, read_at=now)
            )
        else:
            stmt = (
                update(Notification)
                .where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False,
                    )
                )
                .values(is_read=True, read_at=now)
            )

        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount

    # ==================== Device Token Management ====================

    @staticmethod
    async def register_device_token(
        db: AsyncSession,
        user_id: UUID,
        token: str,
        device_type: Optional[str] = None,
    ) -> DeviceToken:
        """Register or reactivate an Expo push token."""
        logger.info(f"[TOKEN] Registering token for user {user_id}: {token[:40]}... (device: {device_type})")
        
        # Check if token exists
        result = await db.execute(
            select(DeviceToken).where(DeviceToken.token == token)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update ownership and reactivate
            existing.user_id = user_id
            existing.device_type = device_type
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
            logger.info(f"[TOKEN] ✅ Reactivated existing token for user {user_id}")
            return existing
        
        # Create new
        device_token = DeviceToken(
            user_id=user_id,
            token=token,
            device_type=device_type,
            is_active=True,
        )
        db.add(device_token)
        await db.commit()
        await db.refresh(device_token)
        logger.info(f"[TOKEN] ✅ Registered NEW token for user {user_id}")
        return device_token

    @staticmethod
    async def remove_device_token(
        db: AsyncSession,
        user_id: UUID,
        token: str,
    ) -> bool:
        """Deactivate a push token (on logout)."""
        result = await db.execute(
            select(DeviceToken).where(
                and_(DeviceToken.user_id == user_id, DeviceToken.token == token)
            )
        )
        device_token = result.scalar_one_or_none()

        if device_token:
            device_token.is_active = False
            await db.commit()
            return True
        return False

    @staticmethod
    async def get_user_push_tokens(db: AsyncSession, user_id: UUID) -> List[str]:
        """Get all active push tokens for a user."""
        result = await db.execute(
            select(DeviceToken.token).where(
                and_(DeviceToken.user_id == user_id, DeviceToken.is_active == True)
            )
        )
        tokens = [row[0] for row in result.all()]
        logger.debug(f"[TOKEN] Found {len(tokens)} active token(s) for user {user_id}")
        return tokens

    @staticmethod
    async def _maybe_deactivate_token(db: AsyncSession, token: str):
        """Deactivate a token that Expo reported as invalid."""
        result = await db.execute(
            select(DeviceToken).where(DeviceToken.token == token)
        )
        device_token = result.scalar_one_or_none()
        if device_token:
            device_token.is_active = False
            await db.commit()
            logger.info(f"Deactivated invalid token: {token[:30]}...")
