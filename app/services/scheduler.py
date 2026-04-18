"""
Notification Scheduler

Background jobs for timed notifications using APScheduler.
Runs in the FastAPI process and checks for upcoming appointment reminders.

Jobs:
- 24h patient reminder (every 5 min)
- 1h patient reminder (every 2 min)
- 30min doctor reminder (every 2 min)
- Daily summary for doctors (every day at 20:00)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, and_

from app.core.database import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def check_24h_reminders():
    """
    Send 24-hour reminders to patients.
    
    Finds confirmed appointments between 23-24 hours from now
    where reminder_24h_sent is False.
    """
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            window_start = now + timedelta(hours=23)
            window_end = now + timedelta(hours=24)

            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.appointment_date >= window_start,
                        Appointment.appointment_date <= window_end,
                        Appointment.reminder_24h_sent == False,
                    )
                )
            )
            appointments = result.scalars().all()

            for appt in appointments:
                try:
                    # Get patient and doctor info
                    patient = await db.execute(
                        select(Patient).where(Patient.id == appt.patient_id)
                    )
                    patient = patient.scalar_one_or_none()

                    doctor = await db.execute(
                        select(Doctor).where(Doctor.id == appt.doctor_id)
                    )
                    doctor = doctor.scalar_one_or_none()

                    if patient and doctor:
                        await NotificationService.notify_reminder_24h(
                            db=db,
                            patient_user_id=patient.user_id,
                            doctor_name=f"{doctor.first_name} {doctor.last_name}",
                            appointment_date=appt.appointment_date,
                            consultation_type=appt.consultation_type.value,
                            appointment_id=appt.id,
                        )

                        # Mark as sent
                        appt.reminder_24h_sent = True
                        await db.commit()
                        logger.info(f"24h reminder sent for appointment {appt.id}")

                except Exception as e:
                    logger.error(f"Error sending 24h reminder for {appt.id}: {e}")

    except Exception as e:
        logger.error(f"check_24h_reminders job error: {e}")


async def check_1h_reminders():
    """
    Send 1-hour reminders to patients.
    
    Finds confirmed appointments between 55-60 minutes from now
    where reminder_1h_sent is False.
    """
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            window_start = now + timedelta(minutes=55)
            window_end = now + timedelta(minutes=60)

            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.appointment_date >= window_start,
                        Appointment.appointment_date <= window_end,
                        Appointment.reminder_1h_sent == False,
                    )
                )
            )
            appointments = result.scalars().all()

            for appt in appointments:
                try:
                    patient = await db.execute(
                        select(Patient).where(Patient.id == appt.patient_id)
                    )
                    patient = patient.scalar_one_or_none()

                    doctor = await db.execute(
                        select(Doctor).where(Doctor.id == appt.doctor_id)
                    )
                    doctor = doctor.scalar_one_or_none()

                    if patient and doctor:
                        await NotificationService.notify_reminder_1h(
                            db=db,
                            patient_user_id=patient.user_id,
                            doctor_name=f"{doctor.first_name} {doctor.last_name}",
                            appointment_date=appt.appointment_date,
                            consultation_type=appt.consultation_type.value,
                            appointment_id=appt.id,
                        )

                        appt.reminder_1h_sent = True
                        await db.commit()
                        logger.info(f"1h reminder sent for appointment {appt.id}")

                except Exception as e:
                    logger.error(f"Error sending 1h reminder for {appt.id}: {e}")

    except Exception as e:
        logger.error(f"check_1h_reminders job error: {e}")


async def check_30min_doctor_reminders():
    """
    Send 30-minute reminders to doctors.
    
    Finds confirmed appointments between 25-30 minutes from now
    where reminder_sent is False.
    """
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            window_start = now + timedelta(minutes=25)
            window_end = now + timedelta(minutes=30)

            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.appointment_date >= window_start,
                        Appointment.appointment_date <= window_end,
                        Appointment.reminder_sent == False,
                    )
                )
            )
            appointments = result.scalars().all()

            for appt in appointments:
                try:
                    patient = await db.execute(
                        select(Patient).where(Patient.id == appt.patient_id)
                    )
                    patient = patient.scalar_one_or_none()

                    doctor = await db.execute(
                        select(Doctor).where(Doctor.id == appt.doctor_id)
                    )
                    doctor = doctor.scalar_one_or_none()

                    if patient and doctor:
                        await NotificationService.notify_doctor_reminder_30min(
                            db=db,
                            doctor_user_id=doctor.user_id,
                            patient_name=f"{patient.first_name} {patient.last_name}",
                            appointment_date=appt.appointment_date,
                            consultation_type=appt.consultation_type.value,
                            appointment_id=appt.id,
                        )

                        appt.reminder_sent = True
                        await db.commit()
                        logger.info(f"30min doctor reminder sent for appointment {appt.id}")

                except Exception as e:
                    logger.error(f"Error sending 30min reminder for {appt.id}: {e}")

    except Exception as e:
        logger.error(f"check_30min_doctor_reminders job error: {e}")


async def send_daily_summary():
    """
    Send daily summary to each doctor about tomorrow's appointments.
    
    Runs at 20:00 daily. Finds all doctors with confirmed appointments 
    for tomorrow and sends them a summary notification.
    """
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            tomorrow_start = datetime(now.year, now.month, now.day) + timedelta(days=1)
            tomorrow_end = tomorrow_start + timedelta(days=1)

            # Find all confirmed appointments for tomorrow
            result = await db.execute(
                select(Appointment).where(
                    and_(
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.appointment_date >= tomorrow_start,
                        Appointment.appointment_date < tomorrow_end,
                    )
                ).order_by(Appointment.appointment_date)
            )
            appointments = result.scalars().all()

            # Group by doctor
            doctor_appointments = {}
            for appt in appointments:
                doctor_id = appt.doctor_id
                if doctor_id not in doctor_appointments:
                    doctor_appointments[doctor_id] = []
                doctor_appointments[doctor_id].append(appt)

            # Send summary to each doctor
            for doctor_id, appts in doctor_appointments.items():
                try:
                    doctor_result = await db.execute(
                        select(Doctor).where(Doctor.id == doctor_id)
                    )
                    doctor = doctor_result.scalar_one_or_none()

                    if doctor:
                        first_time = appts[0].appointment_date.strftime("%H:%M")
                        last_time = appts[-1].appointment_date.strftime("%H:%M")
                        date_str = tomorrow_start.strftime("%B %d, %Y")

                        await NotificationService.notify_doctor_daily_summary(
                            db=db,
                            doctor_user_id=doctor.user_id,
                            appointment_count=len(appts),
                            first_time=first_time,
                            last_time=last_time,
                            date_str=date_str,
                        )
                        logger.info(f"Daily summary sent to Dr. {doctor.last_name}: {len(appts)} appointments")

                except Exception as e:
                    logger.error(f"Error sending daily summary to doctor {doctor_id}: {e}")

    except Exception as e:
        logger.error(f"send_daily_summary job error: {e}")


def start_scheduler():
    """Start the notification scheduler with all jobs."""
    # Patient 24h reminder — check every 5 minutes
    scheduler.add_job(
        check_24h_reminders,
        trigger=IntervalTrigger(minutes=5),
        id="check_24h_reminders",
        name="24h Patient Reminders",
        replace_existing=True,
    )

    # Patient 1h reminder — check every 2 minutes
    scheduler.add_job(
        check_1h_reminders,
        trigger=IntervalTrigger(minutes=2),
        id="check_1h_reminders",
        name="1h Patient Reminders",
        replace_existing=True,
    )

    # Doctor 30min reminder — check every 2 minutes
    scheduler.add_job(
        check_30min_doctor_reminders,
        trigger=IntervalTrigger(minutes=2),
        id="check_30min_doctor_reminders",
        name="30min Doctor Reminders",
        replace_existing=True,
    )

    # Daily summary — every day at 20:00 UTC
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(hour=20, minute=0),
        id="send_daily_summary",
        name="Daily Doctor Summary",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✅ Notification scheduler started with 4 jobs")


def stop_scheduler():
    """Stop the notification scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Notification scheduler stopped")
