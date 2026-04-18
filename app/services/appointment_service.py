from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from typing import Optional, List, Tuple
from uuid import UUID, uuid4
from datetime import datetime, timedelta, date, time
import secrets
import string

from app.config import settings

from app.models.appointment import Appointment, AppointmentStatus, ConsultationType
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.schemas.appointment import (
    AppointmentCreateRequest,
    AppointmentUpdateRequest,
    TimeSlot,
    DayAvailability
)


class AppointmentService:
    """Service for managing appointments."""
    
    # Default working hours (can be overridden by doctor's working_hours)
    DEFAULT_START_HOUR = 9   # 9 AM
    DEFAULT_END_HOUR = 17    # 5 PM
    DEFAULT_SLOT_DURATION = 30  # minutes
    
    @staticmethod
    def generate_confirmation_code() -> str:
        """Generate unique confirmation code like MC-A7B3X2."""
        chars = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(chars) for _ in range(6))
        return f"MC-{code}"
    
    @staticmethod
    async def create_appointment(
        db: AsyncSession,
        patient_id: UUID,
        data: AppointmentCreateRequest
    ) -> Appointment:
        """
        Create a new appointment booking.
        
        Validates:
        - Doctor exists and accepts the consultation type
        - Time slot is available
        - Creates confirmation code
        """
        
        # Get doctor
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.id == data.doctor_id)
        )
        doctor = doctor_result.scalar_one_or_none()
        
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        
        if not doctor.is_accepting_patients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doctor is not accepting new patients"
            )
        
        # Validate consultation type
        if data.consultation_type == ConsultationType.PRESENTIEL and not doctor.offers_presentiel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doctor does not offer in-person consultations"
            )
        
        if data.consultation_type == ConsultationType.ONLINE and not doctor.offers_online:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doctor does not offer online consultations"
            )
        
        # Check slot availability
        is_available = await AppointmentService.check_slot_availability(
            db, data.doctor_id, data.appointment_date
        )
        
        if not is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This time slot is not available. Please choose another time."
            )
        
        # Get consultation fee
        consultation_fee = (
            doctor.consultation_fee_online 
            if data.consultation_type == ConsultationType.ONLINE 
            else doctor.consultation_fee_presentiel
        )
        
        # Generate confirmation code
        confirmation_code = AppointmentService.generate_confirmation_code()
        
        # Generate video room ID for online consultations
        video_room_id = None
        video_call_link = None
        if data.consultation_type == ConsultationType.ONLINE:
            video_room_id = f"mc-{uuid4().hex[:12]}"
            video_call_link = f"https://{settings.JITSI_DOMAIN}/mediconnect-{video_room_id}"
        
        # Create appointment
        appointment = Appointment(
            patient_id=patient_id,
            doctor_id=data.doctor_id,
            appointment_date=data.appointment_date,
            duration_minutes=AppointmentService.DEFAULT_SLOT_DURATION,
            consultation_type=data.consultation_type,
            status=AppointmentStatus.PENDING,
            consultation_fee=consultation_fee,
            currency=doctor.currency,
            notes=data.notes,
            confirmation_code=confirmation_code,
            video_call_room_id=video_room_id,
            video_call_link=video_call_link
        )
        
        db.add(appointment)
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
    
    @staticmethod
    async def check_slot_availability(
        db: AsyncSession,
        doctor_id: UUID,
        appointment_date: datetime,
        exclude_appointment_id: Optional[UUID] = None
    ) -> bool:
        """Check if a time slot is available for a doctor."""
        
        slot_end = appointment_date + timedelta(minutes=AppointmentService.DEFAULT_SLOT_DURATION)
        
        # Build query for conflicting appointments
        query = select(Appointment).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_([
                    AppointmentStatus.PENDING,
                    AppointmentStatus.CONFIRMED
                ]),
                # Check for overlap
                or_(
                    # New slot starts during existing
                    and_(
                        Appointment.appointment_date <= appointment_date,
                        Appointment.appointment_date + timedelta(minutes=30) > appointment_date
                    ),
                    # New slot ends during existing
                    and_(
                        Appointment.appointment_date < slot_end,
                        Appointment.appointment_date + timedelta(minutes=30) >= slot_end
                    ),
                    # New slot contains existing
                    and_(
                        Appointment.appointment_date >= appointment_date,
                        Appointment.appointment_date < slot_end
                    )
                )
            )
        )
        
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        
        result = await db.execute(query)
        conflicts = result.scalars().all()
        
        return len(conflicts) == 0
    
    @staticmethod
    async def get_appointment_by_id(
        db: AsyncSession,
        appointment_id: UUID
    ) -> Optional[Appointment]:
        """Get appointment by ID."""
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_patient_appointments(
        db: AsyncSession,
        patient_id: UUID,
        status_filter: Optional[List[AppointmentStatus]] = None,
        upcoming_only: bool = False,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Appointment], int]:
        """Get appointments for a patient."""
        
        query = select(Appointment).where(Appointment.patient_id == patient_id)
        count_query = select(func.count(Appointment.id)).where(Appointment.patient_id == patient_id)
        
        if status_filter:
            query = query.where(Appointment.status.in_(status_filter))
            count_query = count_query.where(Appointment.status.in_(status_filter))
        
        if upcoming_only:
            query = query.where(Appointment.appointment_date > datetime.utcnow())
            count_query = count_query.where(Appointment.appointment_date > datetime.utcnow())
        
        # Order by date
        query = query.order_by(Appointment.appointment_date.desc())
        
        # Get total count
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        result = await db.execute(query)
        appointments = result.scalars().all()
        
        return appointments, total
    
    @staticmethod
    async def get_doctor_appointments(
        db: AsyncSession,
        doctor_id: UUID,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        status_filter: Optional[List[AppointmentStatus]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Appointment], int]:
        """Get appointments for a doctor."""
        
        query = select(Appointment).where(Appointment.doctor_id == doctor_id)
        count_query = select(func.count(Appointment.id)).where(Appointment.doctor_id == doctor_id)
        
        if date_from:
            start_datetime = datetime.combine(date_from, time.min)
            query = query.where(Appointment.appointment_date >= start_datetime)
            count_query = count_query.where(Appointment.appointment_date >= start_datetime)
        
        if date_to:
            end_datetime = datetime.combine(date_to, time.max)
            query = query.where(Appointment.appointment_date <= end_datetime)
            count_query = count_query.where(Appointment.appointment_date <= end_datetime)
        
        if status_filter:
            query = query.where(Appointment.status.in_(status_filter))
            count_query = count_query.where(Appointment.status.in_(status_filter))
        
        query = query.order_by(Appointment.appointment_date.asc())
        
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        
        query = query.limit(limit).offset(offset)
        
        result = await db.execute(query)
        appointments = result.scalars().all()
        
        return appointments, total
    
    @staticmethod
    async def confirm_appointment(
        db: AsyncSession,
        appointment_id: UUID,
        doctor_user_id: UUID
    ) -> Appointment:
        """Doctor confirms an appointment."""
        
        appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        # Verify doctor owns this appointment
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == doctor_user_id)
        )
        doctor = doctor_result.scalar_one_or_none()
        
        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to confirm this appointment"
            )
        
        if appointment.status != AppointmentStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot confirm appointment with status: {appointment.status.value}"
            )
        
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.confirmed_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
    
    @staticmethod
    async def cancel_appointment(
        db: AsyncSession,
        appointment_id: UUID,
        user_id: UUID,
        is_doctor: bool,
        reason: Optional[str] = None
    ) -> Appointment:
        """Cancel an appointment with 24h rule enforcement."""
        
        appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        # Verify user owns this appointment
        if is_doctor:
            doctor_result = await db.execute(
                select(Doctor).where(Doctor.user_id == user_id)
            )
            doctor = doctor_result.scalar_one_or_none()
            if not doctor or appointment.doctor_id != doctor.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to cancel this appointment"
                )
            cancelled_by = "doctor"
        else:
            patient_result = await db.execute(
                select(Patient).where(Patient.user_id == user_id)
            )
            patient = patient_result.scalar_one_or_none()
            if not patient or appointment.patient_id != patient.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to cancel this appointment"
                )
            cancelled_by = "patient"
        
        # Check cancellation status
        if appointment.status in [AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel appointment with status: {appointment.status.value}"
            )
        
        # Enforce 24h rule for patients (doctors can cancel anytime)
        if not is_doctor and not appointment.is_cancellable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Appointments can only be cancelled at least 24 hours in advance"
            )
        
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = datetime.utcnow()
        appointment.cancelled_by = cancelled_by
        appointment.cancellation_reason = reason
        
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
    
    @staticmethod
    async def reschedule_appointment(
        db: AsyncSession,
        appointment_id: UUID,
        patient_id: UUID,
        new_date: datetime
    ) -> Appointment:
        """Reschedule an appointment to a new time."""
        
        appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        if appointment.patient_id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to reschedule this appointment"
            )
        
        if not appointment.is_modifiable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Appointments can only be rescheduled at least 24 hours in advance"
            )
        
        # Check new slot availability
        is_available = await AppointmentService.check_slot_availability(
            db, appointment.doctor_id, new_date, exclude_appointment_id=appointment_id
        )
        
        if not is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The new time slot is not available"
            )
        
        # Update appointment
        old_date = appointment.appointment_date
        appointment.appointment_date = new_date
        appointment.status = AppointmentStatus.PENDING  # Reset to pending
        appointment.confirmed_at = None
        
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
    
    @staticmethod
    async def get_doctor_availability(
        db: AsyncSession,
        doctor_id: UUID,
        start_date: date,
        end_date: date
    ) -> List[DayAvailability]:
        """Get available time slots for a doctor within a date range."""
        
        # Get doctor
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.id == doctor_id)
        )
        doctor = doctor_result.scalar_one_or_none()
        
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        
        # Get all appointments in range
        start_datetime = datetime.combine(start_date, time.min)
        end_datetime = datetime.combine(end_date, time.max)
        
        result = await db.execute(
            select(Appointment).where(
                and_(
                    Appointment.doctor_id == doctor_id,
                    Appointment.status.in_([
                        AppointmentStatus.PENDING,
                        AppointmentStatus.CONFIRMED
                    ]),
                    Appointment.appointment_date >= start_datetime,
                    Appointment.appointment_date <= end_datetime
                )
            )
        )
        booked_appointments = result.scalars().all()
        
        # Build set of booked slots
        booked_slots = set()
        for appt in booked_appointments:
            booked_slots.add(appt.appointment_date)
        
        # Generate availability for each day
        availability = []
        current_date = start_date
        
        while current_date <= end_date:
            # Skip past dates
            if current_date < date.today():
                current_date += timedelta(days=1)
                continue
            
            # Skip weekends (optional - could be configurable)
            if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                current_date += timedelta(days=1)
                continue
            
            # Get working hours (use defaults or doctor's settings)
            working_hours = doctor.working_hours or {}
            day_name = current_date.strftime('%A').lower()
            day_hours = working_hours.get(day_name, {
                'start': f"{AppointmentService.DEFAULT_START_HOUR:02d}:00",
                'end': f"{AppointmentService.DEFAULT_END_HOUR:02d}:00"
            })
            
            if not day_hours:  # Day off
                current_date += timedelta(days=1)
                continue
            
            start_hour = int(day_hours['start'].split(':')[0])
            end_hour = int(day_hours['end'].split(':')[0])
            
            slots = []
            current_time = datetime.combine(current_date, time(start_hour, 0))
            end_time = datetime.combine(current_date, time(end_hour, 0))
            
            while current_time < end_time:
                slot_end = current_time + timedelta(minutes=AppointmentService.DEFAULT_SLOT_DURATION)
                
                # Check if slot is in the past
                is_past = current_time <= datetime.utcnow()
                
                # Check if slot is booked
                is_booked = current_time in booked_slots
                
                slots.append(TimeSlot(
                    start_time=current_time,
                    end_time=slot_end,
                    is_available=not is_past and not is_booked
                ))
                
                current_time = slot_end
            
            availability.append(DayAvailability(
                date=current_date,
                slots=slots
            ))
            
            current_date += timedelta(days=1)
        
        return availability
    
    @staticmethod
    async def mark_completed(
        db: AsyncSession,
        appointment_id: UUID,
        doctor_user_id: UUID,
        doctor_notes: Optional[str] = None
    ) -> Appointment:
        """Mark appointment as completed."""
        
        appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == doctor_user_id)
        )
        doctor = doctor_result.scalar_one_or_none()
        
        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized"
            )
        
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only confirmed appointments can be marked as completed"
            )
        
        appointment.status = AppointmentStatus.COMPLETED
        if doctor_notes:
            appointment.doctor_notes = doctor_notes
        
        # Update doctor's stats
        doctor.total_consultations += 1
        
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
    
    @staticmethod
    async def mark_no_show(
        db: AsyncSession,
        appointment_id: UUID,
        doctor_user_id: UUID
    ) -> Appointment:
        """Mark appointment as no-show."""
        
        appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        doctor_result = await db.execute(
            select(Doctor).where(Doctor.user_id == doctor_user_id)
        )
        doctor = doctor_result.scalar_one_or_none()
        
        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized"
            )
        
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only confirmed appointments can be marked as no-show"
            )
        
        appointment.status = AppointmentStatus.NO_SHOW
        
        await db.commit()
        await db.refresh(appointment)
        
        return appointment
