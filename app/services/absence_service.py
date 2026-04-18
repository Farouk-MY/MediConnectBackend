"""
Absence Service

Service layer for managing doctor absences including
vacations, sick leave, training, and recurring unavailability.
Includes conflict detection and patient notification logic.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status
from typing import Optional, List
from uuid import UUID
from datetime import datetime, date, time, timedelta

from app.models.absence import DoctorAbsence, AbsenceType, RecurrencePattern
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.appointment import Appointment, AppointmentStatus
from app.schemas.absence import (
    AbsenceCreateRequest,
    AbsenceUpdateRequest,
    AbsenceResponse,
    AbsenceListResponse,
    ConflictCheckRequest,
    ConflictCheckResponse,
    AbsenceCreateResponse,
    AffectedAppointment,
    AbsenceType as SchemaAbsenceType,
    RecurrencePattern as SchemaRecurrencePattern
)


def parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.split(':')
    return time(int(parts[0]), int(parts[1]))


def format_time(t: time) -> str:
    """Format time object to HH:MM string."""
    return t.strftime("%H:%M")


class AbsenceService:
    """Service for managing doctor absences."""
    
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
    def _build_absence_response(absence: DoctorAbsence) -> AbsenceResponse:
        """Build AbsenceResponse from model."""
        return AbsenceResponse(
            id=absence.id,
            doctor_id=absence.doctor_id,
            start_date=absence.start_date,
            end_date=absence.end_date,
            start_time=format_time(absence.start_time) if absence.start_time else None,
            end_time=format_time(absence.end_time) if absence.end_time else None,
            absence_type=SchemaAbsenceType(absence.absence_type.value),
            title=absence.title,
            reason=absence.reason,
            is_recurring=absence.is_recurring,
            recurrence_pattern=SchemaRecurrencePattern(absence.recurrence_pattern.value),
            recurrence_end_date=absence.recurrence_end_date,
            notify_patients=absence.notify_patients,
            patients_notified_at=absence.patients_notified_at,
            affected_appointments_count=absence.affected_appointments_count,
            is_active=absence.is_active,
            is_full_day=absence.is_full_day,
            duration_days=absence.duration_days,
            is_past=absence.is_past,
            is_current=absence.is_current,
            is_future=absence.is_future,
            created_at=absence.created_at,
            updated_at=absence.updated_at
        )
    
    # ==================== Conflict Detection ====================
    
    @staticmethod
    async def check_conflicts(
        db: AsyncSession,
        doctor_id: UUID,
        start_date: date,
        end_date: date,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None,
        exclude_absence_id: Optional[UUID] = None
    ) -> ConflictCheckResponse:
        """
        Check for appointment conflicts within a date range.
        
        Returns affected appointments that fall within the absence period.
        """
        # Build query for overlapping appointments
        query = select(Appointment).join(
            Patient, Appointment.patient_id == Patient.id
        ).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]),
            Appointment.appointment_date >= datetime.combine(start_date, time.min),
            Appointment.appointment_date <= datetime.combine(end_date, time.max)
        )
        
        result = await db.execute(query)
        appointments = result.scalars().all()
        
        affected = []
        for appt in appointments:
            appt_time = appt.appointment_date.time()
            
            # If partial day absence, check time overlap
            if start_time and end_time:
                appt_end_time = (appt.appointment_date + timedelta(minutes=appt.duration_minutes)).time()
                if appt_end_time <= start_time or appt_time >= end_time:
                    continue  # No overlap
            
            # Get patient name
            patient_result = await db.execute(
                select(Patient).where(Patient.id == appt.patient_id)
            )
            patient = patient_result.scalar_one_or_none()
            patient_name = f"{patient.first_name} {patient.last_name}" if patient else "Unknown"
            patient_phone = patient.phone if patient else None
            
            affected.append(AffectedAppointment(
                id=appt.id,
                appointment_date=appt.appointment_date,
                patient_name=patient_name,
                patient_phone=patient_phone,
                consultation_type=appt.consultation_type.value,
                status=appt.status.value
            ))
        
        # Build recommendation message
        if len(affected) == 0:
            recommendation = "No conflicts. You can proceed with creating this absence."
        elif len(affected) == 1:
            recommendation = "1 appointment needs attention. Consider rescheduling before confirming."
        else:
            confirmed = sum(1 for a in affected if a.status == "confirmed")
            recommendation = f"{len(affected)} appointments affected ({confirmed} confirmed). Please reschedule or notify patients."
        
        return ConflictCheckResponse(
            has_conflicts=len(affected) > 0,
            affected_count=len(affected),
            affected_appointments=affected,
            recommendation=recommendation
        )
    
    # ==================== CRUD Operations ====================
    
    @staticmethod
    async def create_absence(
        db: AsyncSession,
        doctor_id: UUID,
        data: AbsenceCreateRequest
    ) -> AbsenceCreateResponse:
        """Create a new absence with conflict checking."""
        # Parse optional times
        start_time = parse_time(data.start_time) if data.start_time else None
        end_time = parse_time(data.end_time) if data.end_time else None
        
        # Check for conflicts
        conflicts = await AbsenceService.check_conflicts(
            db, doctor_id, data.start_date, data.end_date, start_time, end_time
        )
        
        # Create absence
        absence = DoctorAbsence(
            doctor_id=doctor_id,
            start_date=data.start_date,
            end_date=data.end_date,
            start_time=start_time,
            end_time=end_time,
            absence_type=AbsenceType(data.absence_type.value),
            title=data.title,
            reason=data.reason,
            is_recurring=data.is_recurring,
            recurrence_pattern=RecurrencePattern(data.recurrence_pattern.value),
            recurrence_end_date=data.recurrence_end_date,
            notify_patients=data.notify_patients,
            affected_appointments_count=conflicts.affected_count,
            is_active=True
        )
        
        db.add(absence)
        await db.commit()
        await db.refresh(absence)
        
        # If notify_patients is True and there are conflicts, trigger notifications
        if data.notify_patients and conflicts.has_conflicts:
            absence.patients_notified_at = datetime.utcnow()
            await db.commit()
            
            # Send push notifications to affected patients
            from app.services.notification_service import NotificationService
            
            # Get doctor info
            doctor_result = await db.execute(
                select(Doctor).where(Doctor.id == doctor_id)
            )
            doctor = doctor_result.scalar_one_or_none()
            doctor_name = f"{doctor.first_name} {doctor.last_name}" if doctor else "Your doctor"
            
            # Notify each affected patient
            for affected_appt in conflicts.affected_appointments:
                # Get the appointment to find patient user_id
                appt_result = await db.execute(
                    select(Appointment).where(Appointment.id == affected_appt.id)
                )
                appt = appt_result.scalar_one_or_none()
                if appt:
                    patient_result = await db.execute(
                        select(Patient).where(Patient.id == appt.patient_id)
                    )
                    patient = patient_result.scalar_one_or_none()
                    if patient:
                        await NotificationService.notify_patient_absence(
                            db=db,
                            patient_user_id=patient.user_id,
                            doctor_name=doctor_name,
                            absence_start=str(data.start_date),
                            absence_end=str(data.end_date),
                            absence_type=data.absence_type.value,
                            appointment_id=appt.id,
                        )
        
        return AbsenceCreateResponse(
            absence=AbsenceService._build_absence_response(absence),
            conflicts=conflicts,
            message=f"Absence created successfully. {conflicts.recommendation}"
        )
    
    @staticmethod
    async def get_absences(
        db: AsyncSession,
        doctor_id: UUID,
        include_past: bool = False,
        include_cancelled: bool = False
    ) -> AbsenceListResponse:
        """Get list of doctor's absences."""
        query = select(DoctorAbsence).where(DoctorAbsence.doctor_id == doctor_id)
        
        if not include_cancelled:
            query = query.where(DoctorAbsence.is_active == True)
        
        if not include_past:
            query = query.where(DoctorAbsence.end_date >= date.today())
        
        query = query.order_by(DoctorAbsence.start_date)
        
        result = await db.execute(query)
        absences = result.scalars().all()
        
        # Count upcoming vs past
        today = date.today()
        upcoming_count = sum(1 for a in absences if a.start_date >= today)
        past_count = sum(1 for a in absences if a.end_date < today)
        
        return AbsenceListResponse(
            absences=[AbsenceService._build_absence_response(a) for a in absences],
            total=len(absences),
            upcoming_count=upcoming_count,
            past_count=past_count
        )
    
    @staticmethod
    async def get_absence_by_id(
        db: AsyncSession,
        doctor_id: UUID,
        absence_id: UUID
    ) -> AbsenceResponse:
        """Get a single absence by ID."""
        result = await db.execute(
            select(DoctorAbsence)
            .where(DoctorAbsence.id == absence_id)
            .where(DoctorAbsence.doctor_id == doctor_id)
        )
        absence = result.scalar_one_or_none()
        
        if not absence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Absence not found"
            )
        
        return AbsenceService._build_absence_response(absence)
    
    @staticmethod
    async def update_absence(
        db: AsyncSession,
        doctor_id: UUID,
        absence_id: UUID,
        data: AbsenceUpdateRequest
    ) -> AbsenceResponse:
        """Update an existing absence."""
        result = await db.execute(
            select(DoctorAbsence)
            .where(DoctorAbsence.id == absence_id)
            .where(DoctorAbsence.doctor_id == doctor_id)
        )
        absence = result.scalar_one_or_none()
        
        if not absence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Absence not found"
            )
        
        # Update fields
        if data.start_date is not None:
            absence.start_date = data.start_date
        if data.end_date is not None:
            absence.end_date = data.end_date
        if data.start_time is not None:
            absence.start_time = parse_time(data.start_time) if data.start_time else None
        if data.end_time is not None:
            absence.end_time = parse_time(data.end_time) if data.end_time else None
        if data.absence_type is not None:
            absence.absence_type = AbsenceType(data.absence_type.value)
        if data.title is not None:
            absence.title = data.title
        if data.reason is not None:
            absence.reason = data.reason
        if data.is_recurring is not None:
            absence.is_recurring = data.is_recurring
        if data.recurrence_pattern is not None:
            absence.recurrence_pattern = RecurrencePattern(data.recurrence_pattern.value)
        if data.recurrence_end_date is not None:
            absence.recurrence_end_date = data.recurrence_end_date
        if data.notify_patients is not None:
            absence.notify_patients = data.notify_patients
        if data.is_active is not None:
            absence.is_active = data.is_active
            if not data.is_active:
                absence.cancelled_at = datetime.utcnow()
        
        # Recheck conflicts if dates changed
        if data.start_date or data.end_date or data.start_time or data.end_time:
            conflicts = await AbsenceService.check_conflicts(
                db, doctor_id,
                absence.start_date, absence.end_date,
                absence.start_time, absence.end_time,
                exclude_absence_id=absence_id
            )
            absence.affected_appointments_count = conflicts.affected_count
        
        await db.commit()
        await db.refresh(absence)
        
        return AbsenceService._build_absence_response(absence)
    
    @staticmethod
    async def delete_absence(
        db: AsyncSession,
        doctor_id: UUID,
        absence_id: UUID
    ) -> dict:
        """Delete (deactivate) an absence."""
        result = await db.execute(
            select(DoctorAbsence)
            .where(DoctorAbsence.id == absence_id)
            .where(DoctorAbsence.doctor_id == doctor_id)
        )
        absence = result.scalar_one_or_none()
        
        if not absence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Absence not found"
            )
        
        # Soft delete
        absence.is_active = False
        absence.cancelled_at = datetime.utcnow()
        
        await db.commit()
        
        return {"message": "Absence cancelled successfully"}
    
    # ==================== Utility Methods ====================
    
    @staticmethod
    async def get_absences_for_date_range(
        db: AsyncSession,
        doctor_id: UUID,
        start_date: date,
        end_date: date
    ) -> List[DoctorAbsence]:
        """Get active absences that overlap with date range."""
        result = await db.execute(
            select(DoctorAbsence)
            .where(DoctorAbsence.doctor_id == doctor_id)
            .where(DoctorAbsence.is_active == True)
            .where(DoctorAbsence.start_date <= end_date)
            .where(DoctorAbsence.end_date >= start_date)
            .order_by(DoctorAbsence.start_date)
        )
        return result.scalars().all()
    
    @staticmethod
    async def is_date_blocked(
        db: AsyncSession,
        doctor_id: UUID,
        check_date: date,
        check_time: Optional[time] = None
    ) -> bool:
        """Check if a specific date/time is blocked by an absence."""
        absences = await AbsenceService.get_absences_for_date_range(
            db, doctor_id, check_date, check_date
        )
        
        for absence in absences:
            if absence.is_full_day:
                return True
            
            if check_time and absence.start_time and absence.end_time:
                if absence.start_time <= check_time < absence.end_time:
                    return True
        
        return False
