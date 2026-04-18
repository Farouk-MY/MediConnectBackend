from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
import io

from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User, UserRole
from app.schemas.consultation import (
    ConsultationCreateRequest,
    ConsultationUpdateRequest,
    ConsultationResponse,
    ConsultationListResponse,
)
from app.services.consultation_service import ConsultationService
from app.services.pdf_service import generate_consultation_pdf
from app.services.doctor_service import DoctorService
from app.services.patient_service import PatientService
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.patient import Patient

router = APIRouter(prefix="/consultations", tags=["Consultations"])


# ========== Helper ==========

async def _get_doctor_id(db: AsyncSession, user: User) -> UUID:
    if user.role != UserRole.DOCTOR:
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")
    doctor = await DoctorService.get_doctor_by_user_id(db, user.id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    return doctor.id


async def _get_patient_id(db: AsyncSession, user: User) -> UUID:
    if user.role != UserRole.PATIENT:
        raise HTTPException(status_code=403, detail="Only patients can access this endpoint")
    patient = await PatientService.get_patient_by_user_id(db, user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return patient.id


# ========== PDF Export ==========

@router.get("/appointment/{appointment_id}/pdf")
async def export_consultation_pdf(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a PDF report for an appointment's consultation notes."""
    # Get appointment
    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Access check
    if current_user.role == UserRole.DOCTOR:
        doctor = await DoctorService.get_doctor_by_user_id(db, current_user.id)
        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role == UserRole.PATIENT:
        patient = await PatientService.get_patient_by_user_id(db, current_user.id)
        if not patient or appointment.patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get related data
    doctor = await db.get(Doctor, appointment.doctor_id)
    patient = await db.get(Patient, appointment.patient_id)
    if not doctor or not patient:
        raise HTTPException(status_code=404, detail="Doctor or patient not found")

    consultations = await ConsultationService.get_by_appointment(db, appointment_id)

    # Generate PDF
    try:
        pdf_bytes = generate_consultation_pdf(appointment, doctor, patient, consultations)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    filename = f"rapport_consultation_{appointment_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ========== Doctor Endpoints ==========

@router.post("/", response_model=ConsultationResponse, status_code=201)
async def create_consultation(
    data: ConsultationCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a consultation record for a completed appointment.

    Only the doctor who completed the appointment can create the consultation.
    """
    doctor_id = await _get_doctor_id(db, current_user)
    consultation = await ConsultationService.create_consultation(db, doctor_id, data)
    return await ConsultationService.enrich_consultation(db, consultation)


@router.get("/by-appointment/{appointment_id}", response_model=ConsultationListResponse)
async def get_consultation_by_appointment(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all consultation notes for a specific appointment."""
    consultations = await ConsultationService.get_by_appointment(db, appointment_id)
    if not consultations:
        return ConsultationListResponse(consultations=[], total=0)

    # Access check on the first one (all share same doctor/patient)
    first = consultations[0]
    if current_user.role == UserRole.DOCTOR:
        doctor_id = await _get_doctor_id(db, current_user)
        if first.doctor_id != doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role == UserRole.PATIENT:
        patient_id = await _get_patient_id(db, current_user)
        if first.patient_id != patient_id:
            raise HTTPException(status_code=403, detail="Access denied")

    enriched = [await ConsultationService.enrich_consultation(db, c) for c in consultations]
    return ConsultationListResponse(consultations=enriched, total=len(enriched))


@router.get("/my-consultations", response_model=ConsultationListResponse)
async def get_my_consultations(
    patient_id: Optional[UUID] = Query(None, description="Filter by patient (doctor only)"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get consultation records for the current user.

    Doctors see consultations they created (optionally filtered by patient).
    Patients see their own consultation history.
    """
    if current_user.role == UserRole.DOCTOR:
        doctor_id = await _get_doctor_id(db, current_user)
        consultations, total = await ConsultationService.get_doctor_consultations(
            db, doctor_id, patient_id=patient_id, limit=limit, offset=offset
        )
    else:
        pid = await _get_patient_id(db, current_user)
        consultations, total = await ConsultationService.get_patient_consultations(
            db, pid, limit=limit, offset=offset
        )

    enriched = [await ConsultationService.enrich_consultation(db, c) for c in consultations]
    return ConsultationListResponse(consultations=enriched, total=total)


@router.get("/patient/{patient_id}/history", response_model=ConsultationListResponse)
async def get_patient_history(
    patient_id: UUID,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get consultation history for a specific patient.

    Doctor only — used when viewing a patient's full medical history.
    """
    doctor_id = await _get_doctor_id(db, current_user)
    consultations, total = await ConsultationService.get_doctor_consultations(
        db, doctor_id, patient_id=patient_id, limit=limit, offset=offset
    )
    enriched = [await ConsultationService.enrich_consultation(db, c) for c in consultations]
    return ConsultationListResponse(consultations=enriched, total=total)


@router.put("/{consultation_id}", response_model=ConsultationResponse)
async def update_consultation(
    consultation_id: UUID,
    data: ConsultationUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a consultation record. Doctor only."""
    doctor_id = await _get_doctor_id(db, current_user)
    consultation = await ConsultationService.update_consultation(db, consultation_id, doctor_id, data)
    return await ConsultationService.enrich_consultation(db, consultation)


@router.delete("/{consultation_id}", status_code=204)
async def delete_consultation(
    consultation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a consultation record. Doctor only."""
    doctor_id = await _get_doctor_id(db, current_user)
    await ConsultationService.delete_consultation(db, consultation_id, doctor_id)
    return None


@router.get("/{consultation_id}", response_model=ConsultationResponse)
async def get_consultation(
    consultation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single consultation by ID."""
    consultation = await ConsultationService.get_consultation(db, consultation_id)
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")

    # Access check
    if current_user.role == UserRole.DOCTOR:
        doctor_id = await _get_doctor_id(db, current_user)
        if consultation.doctor_id != doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif current_user.role == UserRole.PATIENT:
        patient_id = await _get_patient_id(db, current_user)
        if consultation.patient_id != patient_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return await ConsultationService.enrich_consultation(db, consultation)
