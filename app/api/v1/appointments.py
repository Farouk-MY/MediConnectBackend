from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, timedelta
from uuid import UUID

from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User, UserRole
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.schemas.appointment import (
    AppointmentCreateRequest,
    AppointmentUpdateRequest,
    AppointmentCancelRequest,
    AppointmentResponse,
    AppointmentDetailResponse,
    AppointmentListResponse,
    DoctorAvailabilityResponse,
    BookingConfirmation,
    AppointmentStatus
)
from app.services.appointment_service import AppointmentService
from app.services.notification_service import NotificationService
from app.core.websocket import profile_manager
from sqlalchemy import select

router = APIRouter(prefix="/appointments", tags=["Appointments"])


# ========== Helper Functions ==========

async def get_patient_from_user(db: AsyncSession, user: User) -> Patient:
    """Get patient profile from user."""
    result = await db.execute(
        select(Patient).where(Patient.user_id == user.id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )
    return patient


async def get_doctor_from_user(db: AsyncSession, user: User) -> Doctor:
    """Get doctor profile from user."""
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
    return doctor


async def enrich_appointment(db: AsyncSession, appointment) -> dict:
    """Add doctor and patient details to appointment."""
    # Get doctor
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.id == appointment.doctor_id)
    )
    doctor = doctor_result.scalar_one_or_none()
    
    # Get patient
    patient_result = await db.execute(
        select(Patient).where(Patient.id == appointment.patient_id)
    )
    patient = patient_result.scalar_one_or_none()
    
    response = AppointmentDetailResponse(
        id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        appointment_date=appointment.appointment_date,
        duration_minutes=appointment.duration_minutes,
        consultation_type=appointment.consultation_type,
        status=appointment.status,
        confirmation_code=appointment.confirmation_code,
        consultation_fee=appointment.consultation_fee,
        currency=appointment.currency,
        is_paid=appointment.is_paid,
        notes=appointment.notes,
        video_call_link=appointment.video_call_link,
        cancelled_at=appointment.cancelled_at,
        cancelled_by=appointment.cancelled_by,
        cancellation_reason=appointment.cancellation_reason,
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
        confirmed_at=appointment.confirmed_at,
        is_cancellable=appointment.is_cancellable,
        is_modifiable=appointment.is_modifiable,
        can_join_video=appointment.can_join_video,
        doctor={
            "id": doctor.id,
            "first_name": doctor.first_name,
            "last_name": doctor.last_name,
            "specialty": doctor.specialty,
            "avatar_url": doctor.avatar_url,
            "cabinet_address": doctor.cabinet_address,
            "cabinet_city": doctor.cabinet_city
        } if doctor else None,
        patient={
            "id": patient.id,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "date_of_birth": patient.date_of_birth,
            "phone": patient.phone
        } if patient else None
    )
    
    return response


# ========== Patient Endpoints ==========

@router.post("", response_model=BookingConfirmation, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    data: AppointmentCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Book a new appointment with a doctor.
    
    Patient endpoint - creates a pending appointment.
    Doctor must confirm before it's active.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can book appointments"
        )
    
    patient = await get_patient_from_user(db, current_user)
    
    appointment = await AppointmentService.create_appointment(
        db=db,
        patient_id=patient.id,
        data=data
    )
    
    # Get doctor name for response
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.id == data.doctor_id)
    )
    doctor = doctor_result.scalar_one()
    
    # Send real-time WebSocket notification to doctor
    await profile_manager.broadcast_to_user(
        str(doctor.user_id),
        {
            "type": "new_appointment",
            "data": {
                "appointment_id": str(appointment.id),
                "patient_name": f"{patient.first_name} {patient.last_name}",
                "appointment_date": appointment.appointment_date.isoformat(),
                "consultation_type": appointment.consultation_type.value
            }
        }
    )
    
    # Send push notification to doctor
    await NotificationService.notify_doctor_new_appointment(
        db=db,
        doctor_user_id=doctor.user_id,
        patient_name=f"{patient.first_name} {patient.last_name}",
        appointment_date=appointment.appointment_date,
        consultation_type=appointment.consultation_type.value,
        appointment_id=appointment.id,
    )
    
    return BookingConfirmation(
        appointment_id=appointment.id,
        confirmation_code=appointment.confirmation_code,
        appointment_date=appointment.appointment_date,
        consultation_type=appointment.consultation_type,
        doctor_name=f"Dr. {doctor.first_name} {doctor.last_name}",
        consultation_fee=appointment.consultation_fee,
        currency=appointment.currency
    )


@router.get("/me", response_model=AppointmentListResponse)
async def get_my_appointments(
    status_filter: Optional[str] = Query(None, description="Filter by status: pending,confirmed,cancelled,completed"),
    upcoming_only: bool = Query(False, description="Only show future appointments"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user's appointments.
    
    Works for both patients and doctors.
    """
    # Parse status filter
    statuses = None
    if status_filter:
        statuses = [AppointmentStatus(s.strip()) for s in status_filter.split(",")]
    
    offset = (page - 1) * page_size
    
    if current_user.role == UserRole.PATIENT:
        patient = await get_patient_from_user(db, current_user)
        appointments, total = await AppointmentService.get_patient_appointments(
            db=db,
            patient_id=patient.id,
            status_filter=statuses,
            upcoming_only=upcoming_only,
            limit=page_size,
            offset=offset
        )
    elif current_user.role == UserRole.DOCTOR:
        doctor = await get_doctor_from_user(db, current_user)
        appointments, total = await AppointmentService.get_doctor_appointments(
            db=db,
            doctor_id=doctor.id,
            status_filter=statuses,
            limit=page_size,
            offset=offset
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role"
        )
    
    # Enrich with doctor/patient details
    enriched = []
    for appt in appointments:
        enriched.append(await enrich_appointment(db, appt))
    
    return AppointmentListResponse(
        appointments=enriched,
        total=total,
        page=page,
        page_size=page_size,
        has_next=offset + page_size < total
    )


@router.get("/{appointment_id}", response_model=AppointmentDetailResponse)
async def get_appointment(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get appointment details by ID."""
    
    appointment = await AppointmentService.get_appointment_by_id(db, appointment_id)
    
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )
    
    # Verify access
    if current_user.role == UserRole.PATIENT:
        patient = await get_patient_from_user(db, current_user)
        if appointment.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this appointment"
            )
    elif current_user.role == UserRole.DOCTOR:
        doctor = await get_doctor_from_user(db, current_user)
        if appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this appointment"
            )
    
    return await enrich_appointment(db, appointment)


@router.put("/{appointment_id}/reschedule", response_model=AppointmentDetailResponse)
async def reschedule_appointment(
    appointment_id: UUID,
    data: AppointmentUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Reschedule an appointment to a new time.
    
    Patient endpoint - must be at least 24h before current appointment.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can reschedule appointments"
        )
    
    patient = await get_patient_from_user(db, current_user)
    
    appointment = await AppointmentService.reschedule_appointment(
        db=db,
        appointment_id=appointment_id,
        patient_id=patient.id,
        new_date=data.new_date
    )
    
    # Notify doctor via WebSocket
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.id == appointment.doctor_id)
    )
    doctor = doctor_result.scalar_one()
    
    await profile_manager.broadcast_to_user(
        str(doctor.user_id),
        {
            "type": "appointment_rescheduled",
            "data": {
                "appointment_id": str(appointment.id),
                "new_date": appointment.appointment_date.isoformat()
            }
        }
    )
    
    # Push notification to doctor
    await NotificationService.notify_doctor_rescheduled(
        db=db,
        doctor_user_id=doctor.user_id,
        patient_name=f"{patient.first_name} {patient.last_name}",
        new_date=appointment.appointment_date,
        appointment_id=appointment.id,
    )
    
    return await enrich_appointment(db, appointment)


@router.delete("/{appointment_id}", response_model=AppointmentDetailResponse)
async def cancel_appointment(
    appointment_id: UUID,
    data: Optional[AppointmentCancelRequest] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an appointment.
    
    Patients: Must cancel at least 24h before.
    Doctors: Can cancel anytime.
    """
    is_doctor = current_user.role == UserRole.DOCTOR
    reason = data.reason if data else None
    
    appointment = await AppointmentService.cancel_appointment(
        db=db,
        appointment_id=appointment_id,
        user_id=current_user.id,
        is_doctor=is_doctor,
        reason=reason
    )
    
    # Notify the other party
    patient_result = await db.execute(
        select(Patient).where(Patient.id == appointment.patient_id)
    )
    patient = patient_result.scalar_one()
    
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.id == appointment.doctor_id)
    )
    doctor = doctor_result.scalar_one()
    
    if is_doctor:
        target_user_id = str(patient.user_id)
        other_party_name = f"{doctor.first_name} {doctor.last_name}"
    else:
        target_user_id = str(doctor.user_id)
        other_party_name = f"{patient.first_name} {patient.last_name}"
    
    # WebSocket notification
    await profile_manager.broadcast_to_user(
        target_user_id,
        {
            "type": "appointment_cancelled",
            "data": {
                "appointment_id": str(appointment.id),
                "cancelled_by": appointment.cancelled_by,
                "reason": reason
            }
        }
    )
    
    # Push notification
    from uuid import UUID as UUIDType
    await NotificationService.notify_appointment_cancelled(
        db=db,
        target_user_id=UUIDType(target_user_id),
        cancelled_by_role=appointment.cancelled_by,
        other_party_name=other_party_name,
        appointment_date=appointment.appointment_date,
        reason=reason,
        appointment_id=appointment.id,
    )
    
    return await enrich_appointment(db, appointment)


# ========== Doctor Endpoints ==========

@router.post("/{appointment_id}/confirm", response_model=AppointmentDetailResponse)
async def confirm_appointment(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Doctor confirms a pending appointment.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can confirm appointments"
        )
    
    appointment = await AppointmentService.confirm_appointment(
        db=db,
        appointment_id=appointment_id,
        doctor_user_id=current_user.id
    )
    
    # Notify patient via WebSocket
    patient_result = await db.execute(
        select(Patient).where(Patient.id == appointment.patient_id)
    )
    patient = patient_result.scalar_one()
    
    doctor = await get_doctor_from_user(db, current_user)
    
    await profile_manager.broadcast_to_user(
        str(patient.user_id),
        {
            "type": "appointment_confirmed",
            "data": {
                "appointment_id": str(appointment.id),
                "confirmation_code": appointment.confirmation_code,
                "appointment_date": appointment.appointment_date.isoformat()
            }
        }
    )
    
    # Send push notification to patient
    await NotificationService.notify_patient_confirmed(
        db=db,
        patient_user_id=patient.user_id,
        doctor_name=f"{doctor.first_name} {doctor.last_name}",
        appointment_date=appointment.appointment_date,
        confirmation_code=appointment.confirmation_code,
        appointment_id=appointment.id,
    )
    
    return await enrich_appointment(db, appointment)


@router.post("/{appointment_id}/complete", response_model=AppointmentDetailResponse)
async def complete_appointment(
    appointment_id: UUID,
    doctor_notes: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Doctor marks an appointment as completed.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can complete appointments"
        )
    
    appointment = await AppointmentService.mark_completed(
        db=db,
        appointment_id=appointment_id,
        doctor_user_id=current_user.id,
        doctor_notes=doctor_notes
    )
    
    # Notify patient appointment is completed
    patient_result = await db.execute(
        select(Patient).where(Patient.id == appointment.patient_id)
    )
    patient = patient_result.scalar_one()
    doctor = await get_doctor_from_user(db, current_user)
    
    await NotificationService.notify_patient_completed(
        db=db,
        patient_user_id=patient.user_id,
        doctor_name=f"{doctor.first_name} {doctor.last_name}",
        appointment_id=appointment.id,
    )
    
    return await enrich_appointment(db, appointment)


@router.post("/{appointment_id}/no-show", response_model=AppointmentDetailResponse)
async def mark_no_show(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Doctor marks patient as no-show.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can mark no-shows"
        )
    
    appointment = await AppointmentService.mark_no_show(
        db=db,
        appointment_id=appointment_id,
        doctor_user_id=current_user.id
    )
    
    return await enrich_appointment(db, appointment)


# ========== Availability Endpoints ==========

@router.get("/doctors/{doctor_id}/availability", response_model=DoctorAvailabilityResponse)
async def get_doctor_availability(
    doctor_id: UUID,
    start_date: date = Query(..., description="Start date for availability check"),
    end_date: Optional[date] = Query(None, description="End date (defaults to start_date + 14 days)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get available time slots for a doctor.
    
    Public endpoint - anyone can check availability.
    Returns slots for up to 14 days.
    """
    if end_date is None:
        end_date = start_date + timedelta(days=14)
    
    # Cap at 30 days
    if (end_date - start_date).days > 30:
        end_date = start_date + timedelta(days=30)
    
    availability = await AppointmentService.get_doctor_availability(
        db=db,
        doctor_id=doctor_id,
        start_date=start_date,
        end_date=end_date
    )
    
    return DoctorAvailabilityResponse(
        doctor_id=doctor_id,
        availability=availability
    )
