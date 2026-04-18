from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User, UserRole
from app.schemas.doctor import (
    DoctorResponse,
    DoctorPublicProfile,
    DoctorUpdateRequest,
    ConsultationTypeConfigRequest
)
from app.services.doctor_service import DoctorService
from app.core.websocket import profile_manager
from app.models.appointment import Appointment, AppointmentStatus
from app.models.patient import Patient
from sqlalchemy import select, func, desc, and_
from datetime import datetime

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.get("/me", response_model=DoctorResponse)
async def get_my_profile(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get current doctor's profile.

    Requires doctor role.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can access this endpoint"
        )

    doctor = await DoctorService.get_doctor_by_user_id(db, current_user.id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )

    return doctor


@router.put("/me", response_model=DoctorResponse)
async def update_my_profile(
        data: DoctorUpdateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Update current doctor's profile.

    Can update:
    - Professional info (US006): specialty, experience, bio, education
    - Cabinet info (US007): address, phone, pricing, payment methods
    - Consultation types (US008): presentiel, online, fees
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can access this endpoint"
        )

    doctor = await DoctorService.update_doctor_profile(db, current_user.id, data)
    
    # Broadcast real-time update via WebSocket
    await profile_manager.broadcast_to_user(
        str(current_user.id),
        {
            "type": "profile_update",
            "data": DoctorResponse.model_validate(doctor).model_dump(mode='json')
        }
    )
    
    return doctor


@router.put("/me/consultation-types", response_model=DoctorResponse)
async def configure_consultation_types(
        data: ConsultationTypeConfigRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Configure consultation types and pricing (US008).

    Allows doctor to specify:
    - Which consultation types they offer (presentiel/online)
    - Pricing for each type

    At least one consultation type must be enabled.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can access this endpoint"
        )

    doctor = await DoctorService.configure_consultation_types(db, current_user.id, data)
    return doctor


@router.get("/my-patients")
async def get_my_patients(
        search: Optional[str] = Query(None, description="Search by patient name"),
        sort_by: Optional[str] = Query("last_visit", description="Sort: 'last_visit', 'name', 'visits'"),
        limit: int = Query(50, le=100),
        offset: int = Query(0, ge=0),
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Get all patients who have had appointments with the current doctor (US023).

    Returns patient info enriched with visit statistics.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")

    doctor = await DoctorService.get_doctor_by_user_id(db, current_user.id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    # Get all unique patient IDs from appointments
    apt_q = (
        select(
            Appointment.patient_id,
            func.count(Appointment.id).label("visit_count"),
            func.max(Appointment.appointment_date).label("last_visit"),
        )
        .where(Appointment.doctor_id == doctor.id)
        .where(Appointment.status.in_([
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.PENDING,
        ]))
        .group_by(Appointment.patient_id)
    )

    apt_result = await db.execute(apt_q)
    patient_stats = {row.patient_id: {"visit_count": row.visit_count, "last_visit": row.last_visit} for row in apt_result}

    if not patient_stats:
        return {"patients": [], "total": 0}

    # Get patient details
    p_q = select(Patient).where(Patient.id.in_(patient_stats.keys()))
    if search:
        from sqlalchemy import or_
        p_q = p_q.where(
            or_(
                Patient.first_name.ilike(f"%{search}%"),
                Patient.last_name.ilike(f"%{search}%"),
            )
        )

    total_result = await db.execute(select(func.count()).select_from(p_q.subquery()))
    total = total_result.scalar() or 0

    p_q = p_q.limit(limit).offset(offset)
    patients_result = await db.execute(p_q)
    patients = patients_result.scalars().all()

    # Get next upcoming appointment for each patient
    now = datetime.utcnow()
    next_apt_q = (
        select(Appointment.patient_id, func.min(Appointment.appointment_date).label("next_apt"))
        .where(and_(
            Appointment.doctor_id == doctor.id,
            Appointment.patient_id.in_(patient_stats.keys()),
            Appointment.appointment_date > now,
            Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]),
        ))
        .group_by(Appointment.patient_id)
    )
    next_apts = {row.patient_id: row.next_apt for row in (await db.execute(next_apt_q))}

    # Build response
    patient_list = []
    for p in patients:
        stats = patient_stats.get(p.id, {})
        patient_list.append({
            "id": str(p.id),
            "user_id": str(p.user_id) if p.user_id else None,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "phone": p.phone,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "gender": p.gender,
            "blood_type": p.blood_type,
            "city": p.city,
            "avatar_url": p.avatar_url,
            "medical_history": p.medical_history or [],
            "allergies": p.allergies or [],
            "current_medications": p.current_medications or [],
            "visit_count": stats.get("visit_count", 0),
            "last_visit": stats.get("last_visit").isoformat() if stats.get("last_visit") else None,
            "next_appointment": next_apts.get(p.id).isoformat() if next_apts.get(p.id) else None,
        })

    # Sort
    if sort_by == "name":
        patient_list.sort(key=lambda x: f"{x['first_name']} {x['last_name']}")
    elif sort_by == "visits":
        patient_list.sort(key=lambda x: x["visit_count"], reverse=True)
    else:
        patient_list.sort(key=lambda x: x["last_visit"] or "", reverse=True)

    return {"patients": patient_list, "total": total}


@router.get("/search", response_model=List[DoctorPublicProfile])
async def search_doctors(
        specialty: Optional[str] = Query(None, description="Filter by specialty"),
        city: Optional[str] = Query(None, description="Filter by city"),
        doctor_name: Optional[str] = Query(None, description="Search by doctor's first or last name"),
        consultation_type: Optional[str] = Query(None,
                                                 description="Filter by consultation type: 'presentiel' or 'online'"),
        max_fee: Optional[float] = Query(None, description="Maximum consultation fee"),
        min_rating: Optional[float] = Query(None, ge=0, le=5, description="Minimum rating (0-5)"),
        sort_by: Optional[str] = Query(None, description="Sort by: 'rating', 'price_asc', 'price_desc', 'experience'"),
        accepting_patients: bool = Query(True, description="Only show doctors accepting new patients"),
        limit: int = Query(20, le=100),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db)
):
    """
    Search for doctors with filters and sorting.

    Public endpoint - anyone can search for doctors.
    Used by patients to find suitable doctors.

    Filters:
    - specialty: Search by medical specialty (e.g., "Cardiology")
    - city: Filter by city
    - doctor_name: Search by doctor's first or last name
    - consultation_type: "presentiel" or "online"
    - max_fee: Maximum consultation fee willing to pay
    - min_rating: Minimum doctor rating (0-5)
    - sort_by: Sort results by 'rating', 'price_asc', 'price_desc', 'experience'
    - accepting_patients: Only show doctors accepting new patients
    """
    doctors = await DoctorService.search_doctors(
        db=db,
        specialty=specialty,
        city=city,
        doctor_name=doctor_name,
        consultation_type=consultation_type,
        max_fee=max_fee,
        min_rating=min_rating,
        sort_by=sort_by,
        accepting_patients=accepting_patients,
        limit=limit,
        offset=offset
    )
    return doctors


@router.get("/list", response_model=List[DoctorPublicProfile])
async def list_all_doctors(
        limit: int = Query(50, le=100),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db)
):
    """
    Get list of all doctors.

    Public endpoint - returns basic info about all doctors.
    """
    doctors = await DoctorService.get_all_doctors(db, limit=limit, offset=offset)
    return doctors


@router.get("/{doctor_id}", response_model=DoctorPublicProfile)
async def get_doctor_by_id(
        doctor_id: str,
        db: AsyncSession = Depends(get_db)
):
    """
    Get doctor profile by ID.

    Public endpoint - anyone can view a doctor's public profile.
    Used when patients want to see doctor details before booking.
    """
    from uuid import UUID

    try:
        doctor_uuid = UUID(doctor_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid doctor ID format"
        )

    doctor = await DoctorService.get_doctor_by_id(db, doctor_uuid)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    return doctor