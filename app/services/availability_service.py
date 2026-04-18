"""
Availability Service

Service layer for managing doctor availability schedules,
including weekly recurring slots and one-off exceptions.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from typing import Optional, List
from uuid import UUID
from datetime import datetime, time, date, timedelta

from app.models.availability import DoctorAvailability, AvailabilityException, ConsultationTypeAvailability
from app.models.absence import DoctorAbsence
from app.models.doctor import Doctor
from app.models.appointment import Appointment, AppointmentStatus
from app.schemas.availability import (
    AvailabilitySlotCreate,
    AvailabilitySlotUpdate,
    ExceptionCreateRequest,
    WorkingHoursRequest,
    DayScheduleRequest,
    AvailabilitySlotResponse,
    DayScheduleResponse,
    WeeklyScheduleResponse,
    ExceptionResponse,
    ComputedTimeSlot,
    ComputedDayAvailability,
    ComputedAvailabilityResponse,
    ConsultationTypeAvailability as SchemaConsultationType
)


DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.split(':')
    return time(int(parts[0]), int(parts[1]))


def format_time(t: time) -> str:
    """Format time object to HH:MM string."""
    return t.strftime("%H:%M")


class AvailabilityService:
    """Service for managing doctor availability."""
    
    # ==================== Weekly Schedule Management ====================
    
    @staticmethod
    async def get_doctor_by_user_id(db: AsyncSession, user_id: UUID) -> Doctor:
        """Get doctor by user ID."""
        result = await db.execute(
            select(Doctor).where(Doctor.user_id == user_id)
        )
        doctor = result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found"
            )
        return doctor
    
    @staticmethod
    async def get_weekly_schedule(
        db: AsyncSession,
        doctor_id: UUID
    ) -> WeeklyScheduleResponse:
        """Get doctor's full weekly schedule."""
        result = await db.execute(
            select(DoctorAvailability)
            .where(DoctorAvailability.doctor_id == doctor_id)
            .where(DoctorAvailability.is_active == True)
            .order_by(DoctorAvailability.day_of_week, DoctorAvailability.start_time)
        )
        slots = result.scalars().all()
        
        # Group by day of week
        days_data = {i: [] for i in range(7)}
        for slot in slots:
            days_data[slot.day_of_week].append(slot)
        
        # Build response
        schedule = []
        default_duration = 30
        default_type = SchemaConsultationType.BOTH
        
        for day in range(7):
            day_slots = days_data[day]
            slot_responses = []
            total_minutes = 0
            total_slots = 0
            
            for slot in day_slots:
                slot_responses.append(AvailabilitySlotResponse(
                    id=slot.id,
                    doctor_id=slot.doctor_id,
                    day_of_week=slot.day_of_week,
                    start_time=format_time(slot.start_time),
                    end_time=format_time(slot.end_time),
                    consultation_type=SchemaConsultationType(slot.consultation_type.value),
                    slot_duration_minutes=slot.slot_duration_minutes,
                    break_start=format_time(slot.break_start) if slot.break_start else None,
                    break_end=format_time(slot.break_end) if slot.break_end else None,
                    is_active=slot.is_active,
                    slot_count=slot.slot_count,
                    created_at=slot.created_at.isoformat()
                ))
                total_minutes += slot.total_minutes
                total_slots += slot.slot_count
                default_duration = slot.slot_duration_minutes
                default_type = SchemaConsultationType(slot.consultation_type.value)
            
            schedule.append(DayScheduleResponse(
                day_of_week=day,
                day_name=DAY_NAMES[day],
                is_working_day=len(day_slots) > 0,
                slots=slot_responses,
                total_hours=total_minutes / 60,
                total_slots=total_slots
            ))
        
        return WeeklyScheduleResponse(
            doctor_id=doctor_id,
            schedule=schedule,
            default_slot_duration=default_duration,
            default_consultation_type=default_type
        )
    
    @staticmethod
    async def create_availability_slot(
        db: AsyncSession,
        doctor_id: UUID,
        data: AvailabilitySlotCreate
    ) -> AvailabilitySlotResponse:
        """Create a new availability slot."""
        # Check for overlapping slots
        existing = await db.execute(
            select(DoctorAvailability)
            .where(DoctorAvailability.doctor_id == doctor_id)
            .where(DoctorAvailability.day_of_week == data.day_of_week)
            .where(DoctorAvailability.is_active == True)
        )
        existing_slots = existing.scalars().all()
        
        new_start = parse_time(data.start_time)
        new_end = parse_time(data.end_time)
        
        for slot in existing_slots:
            # Check overlap
            if not (new_end <= slot.start_time or new_start >= slot.end_time):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Overlaps with existing slot {format_time(slot.start_time)}-{format_time(slot.end_time)}"
                )
        
        # Create new slot
        new_slot = DoctorAvailability(
            doctor_id=doctor_id,
            day_of_week=data.day_of_week,
            start_time=new_start,
            end_time=new_end,
            consultation_type=ConsultationTypeAvailability(data.consultation_type.value),
            slot_duration_minutes=data.slot_duration_minutes,
            break_start=parse_time(data.break_start) if data.break_start else None,
            break_end=parse_time(data.break_end) if data.break_end else None,
            is_active=True
        )
        
        db.add(new_slot)
        await db.commit()
        await db.refresh(new_slot)
        
        return AvailabilitySlotResponse(
            id=new_slot.id,
            doctor_id=new_slot.doctor_id,
            day_of_week=new_slot.day_of_week,
            start_time=format_time(new_slot.start_time),
            end_time=format_time(new_slot.end_time),
            consultation_type=SchemaConsultationType(new_slot.consultation_type.value),
            slot_duration_minutes=new_slot.slot_duration_minutes,
            break_start=format_time(new_slot.break_start) if new_slot.break_start else None,
            break_end=format_time(new_slot.break_end) if new_slot.break_end else None,
            is_active=new_slot.is_active,
            slot_count=new_slot.slot_count,
            created_at=new_slot.created_at.isoformat()
        )
    
    @staticmethod
    async def update_availability_slot(
        db: AsyncSession,
        doctor_id: UUID,
        slot_id: UUID,
        data: AvailabilitySlotUpdate
    ) -> AvailabilitySlotResponse:
        """Update an existing availability slot."""
        result = await db.execute(
            select(DoctorAvailability)
            .where(DoctorAvailability.id == slot_id)
            .where(DoctorAvailability.doctor_id == doctor_id)
        )
        slot = result.scalar_one_or_none()
        
        if not slot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Availability slot not found"
            )
        
        # Update fields
        if data.start_time:
            slot.start_time = parse_time(data.start_time)
        if data.end_time:
            slot.end_time = parse_time(data.end_time)
        if data.consultation_type:
            slot.consultation_type = ConsultationTypeAvailability(data.consultation_type.value)
        if data.slot_duration_minutes:
            slot.slot_duration_minutes = data.slot_duration_minutes
        if data.break_start is not None:
            slot.break_start = parse_time(data.break_start) if data.break_start else None
        if data.break_end is not None:
            slot.break_end = parse_time(data.break_end) if data.break_end else None
        if data.is_active is not None:
            slot.is_active = data.is_active
        
        await db.commit()
        await db.refresh(slot)
        
        return AvailabilitySlotResponse(
            id=slot.id,
            doctor_id=slot.doctor_id,
            day_of_week=slot.day_of_week,
            start_time=format_time(slot.start_time),
            end_time=format_time(slot.end_time),
            consultation_type=SchemaConsultationType(slot.consultation_type.value),
            slot_duration_minutes=slot.slot_duration_minutes,
            break_start=format_time(slot.break_start) if slot.break_start else None,
            break_end=format_time(slot.break_end) if slot.break_end else None,
            is_active=slot.is_active,
            slot_count=slot.slot_count,
            created_at=slot.created_at.isoformat()
        )
    
    @staticmethod
    async def delete_availability_slot(
        db: AsyncSession,
        doctor_id: UUID,
        slot_id: UUID
    ) -> dict:
        """Delete an availability slot."""
        result = await db.execute(
            select(DoctorAvailability)
            .where(DoctorAvailability.id == slot_id)
            .where(DoctorAvailability.doctor_id == doctor_id)
        )
        slot = result.scalar_one_or_none()
        
        if not slot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Availability slot not found"
            )
        
        await db.delete(slot)
        await db.commit()
        
        return {"message": "Availability slot deleted successfully"}
    
    @staticmethod
    async def set_working_hours(
        db: AsyncSession,
        doctor_id: UUID,
        data: WorkingHoursRequest
    ) -> WeeklyScheduleResponse:
        """Set working hours for multiple days (bulk operation)."""
        for day_schedule in data.schedule:
            # Delete existing slots for this day
            await db.execute(
                delete(DoctorAvailability)
                .where(DoctorAvailability.doctor_id == doctor_id)
                .where(DoctorAvailability.day_of_week == day_schedule.day_of_week)
            )
            
            # Create new slots if working day
            if day_schedule.is_working_day:
                for slot_data in day_schedule.slots:
                    new_slot = DoctorAvailability(
                        doctor_id=doctor_id,
                        day_of_week=slot_data.day_of_week,
                        start_time=parse_time(slot_data.start_time),
                        end_time=parse_time(slot_data.end_time),
                        consultation_type=ConsultationTypeAvailability(slot_data.consultation_type.value),
                        slot_duration_minutes=slot_data.slot_duration_minutes or data.default_slot_duration,
                        break_start=parse_time(slot_data.break_start) if slot_data.break_start else None,
                        break_end=parse_time(slot_data.break_end) if slot_data.break_end else None,
                        is_active=True
                    )
                    db.add(new_slot)
        
        await db.commit()
        
        return await AvailabilityService.get_weekly_schedule(db, doctor_id)
    
    # ==================== Exceptions Management ====================
    
    @staticmethod
    async def create_exception(
        db: AsyncSession,
        doctor_id: UUID,
        data: ExceptionCreateRequest
    ) -> ExceptionResponse:
        """Create a one-off availability exception."""
        exception = AvailabilityException(
            doctor_id=doctor_id,
            exception_date=data.exception_date,
            start_time=parse_time(data.start_time) if data.start_time else None,
            end_time=parse_time(data.end_time) if data.end_time else None,
            is_available=data.is_available,
            consultation_type=ConsultationTypeAvailability(data.consultation_type.value) if data.consultation_type else None,
            reason=data.reason
        )
        
        db.add(exception)
        await db.commit()
        await db.refresh(exception)
        
        return ExceptionResponse(
            id=exception.id,
            doctor_id=exception.doctor_id,
            exception_date=exception.exception_date,
            start_time=format_time(exception.start_time) if exception.start_time else None,
            end_time=format_time(exception.end_time) if exception.end_time else None,
            is_available=exception.is_available,
            is_full_day=exception.is_full_day,
            consultation_type=SchemaConsultationType(exception.consultation_type.value) if exception.consultation_type else None,
            reason=exception.reason,
            created_at=exception.created_at.isoformat()
        )
    
    @staticmethod
    async def get_exceptions(
        db: AsyncSession,
        doctor_id: UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[ExceptionResponse]:
        """Get availability exceptions for a date range."""
        query = select(AvailabilityException).where(
            AvailabilityException.doctor_id == doctor_id
        )
        
        if start_date:
            query = query.where(AvailabilityException.exception_date >= start_date)
        if end_date:
            query = query.where(AvailabilityException.exception_date <= end_date)
        
        query = query.order_by(AvailabilityException.exception_date)
        
        result = await db.execute(query)
        exceptions = result.scalars().all()
        
        return [
            ExceptionResponse(
                id=exc.id,
                doctor_id=exc.doctor_id,
                exception_date=exc.exception_date,
                start_time=format_time(exc.start_time) if exc.start_time else None,
                end_time=format_time(exc.end_time) if exc.end_time else None,
                is_available=exc.is_available,
                is_full_day=exc.is_full_day,
                consultation_type=SchemaConsultationType(exc.consultation_type.value) if exc.consultation_type else None,
                reason=exc.reason,
                created_at=exc.created_at.isoformat()
            )
            for exc in exceptions
        ]
    
    # ==================== Computed Availability ====================
    
    @staticmethod
    async def get_computed_availability(
        db: AsyncSession,
        doctor_id: UUID,
        start_date: date,
        end_date: date
    ) -> ComputedAvailabilityResponse:
        """
        Get computed availability for a date range.
        
        This combines:
        - Weekly schedule
        - Exceptions
        - Absences
        - Existing appointments
        """
        # Get weekly schedule
        schedule = await AvailabilityService.get_weekly_schedule(db, doctor_id)
        
        # Get exceptions for date range
        exceptions = await AvailabilityService.get_exceptions(db, doctor_id, start_date, end_date)
        exceptions_by_date = {exc.exception_date: exc for exc in exceptions}
        
        # Get absences for date range
        absences_result = await db.execute(
            select(DoctorAbsence)
            .where(DoctorAbsence.doctor_id == doctor_id)
            .where(DoctorAbsence.is_active == True)
            .where(DoctorAbsence.start_date <= end_date)
            .where(DoctorAbsence.end_date >= start_date)
        )
        absences = absences_result.scalars().all()
        
        # Get appointments for date range
        appointments_result = await db.execute(
            select(Appointment)
            .where(Appointment.doctor_id == doctor_id)
            .where(Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]))
            .where(Appointment.appointment_date >= datetime.combine(start_date, time.min))
            .where(Appointment.appointment_date <= datetime.combine(end_date, time.max))
        )
        appointments = appointments_result.scalars().all()
        
        # Build day-by-day availability
        days = []
        current_date = start_date
        
        while current_date <= end_date:
            day_of_week = current_date.weekday()
            day_schedule = schedule.schedule[day_of_week]
            
            # Check if day is blocked by absence
            is_blocked = False
            block_reason = None
            for absence in absences:
                if absence.start_date <= current_date <= absence.end_date:
                    if absence.is_full_day:
                        is_blocked = True
                        block_reason = absence.title or absence.absence_type.value
                        break
            
            # Check for exceptions
            exception = exceptions_by_date.get(current_date)
            if exception and not exception.is_available and exception.is_full_day:
                is_blocked = True
                block_reason = exception.reason or "Blocked"
            
            # Generate time slots
            slots = []
            if not is_blocked and day_schedule.is_working_day:
                for slot_info in day_schedule.slots:
                    slot_start = parse_time(slot_info.start_time)
                    slot_end = parse_time(slot_info.end_time)
                    duration = slot_info.slot_duration_minutes
                    
                    # Generate individual time slots
                    current_time = datetime.combine(current_date, slot_start)
                    end_time = datetime.combine(current_date, slot_end)
                    
                    while current_time + timedelta(minutes=duration) <= end_time:
                        slot_end_time = current_time + timedelta(minutes=duration)
                        
                        # Check if in break
                        in_break = False
                        if slot_info.break_start and slot_info.break_end:
                            break_start = parse_time(slot_info.break_start)
                            break_end = parse_time(slot_info.break_end)
                            if not (current_time.time() >= break_end or slot_end_time.time() <= break_start):
                                in_break = True
                        
                        if not in_break:
                            # Check if booked
                            is_booked = False
                            appointment_id = None
                            for appt in appointments:
                                appt_start = appt.appointment_date
                                appt_end = appt_start + timedelta(minutes=appt.duration_minutes)
                                if not (slot_end_time <= appt_start or current_time >= appt_end):
                                    is_booked = True
                                    appointment_id = appt.id
                                    break
                            
                            slots.append(ComputedTimeSlot(
                                start_time=current_time.strftime("%H:%M"),
                                end_time=slot_end_time.strftime("%H:%M"),
                                is_available=not is_booked,
                                is_booked=is_booked,
                                appointment_id=appointment_id,
                                consultation_type=slot_info.consultation_type
                            ))
                        
                        current_time = slot_end_time
            
            available_count = sum(1 for s in slots if s.is_available)
            booked_count = sum(1 for s in slots if s.is_booked)
            
            days.append(ComputedDayAvailability(
                date=current_date,
                day_of_week=day_of_week,
                day_name=DAY_NAMES[day_of_week],
                is_working_day=day_schedule.is_working_day and not is_blocked,
                is_blocked=is_blocked,
                block_reason=block_reason,
                slots=slots,
                available_slot_count=available_count,
                booked_slot_count=booked_count
            ))
            
            current_date += timedelta(days=1)
        
        return ComputedAvailabilityResponse(
            doctor_id=doctor_id,
            start_date=start_date,
            end_date=end_date,
            days=days
        )
