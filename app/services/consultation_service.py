from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import Optional, List

from app.models.consultation import Consultation
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.schemas.consultation import (
    ConsultationCreateRequest,
    ConsultationUpdateRequest,
    ConsultationResponse,
)
from fastapi import HTTPException, status


class ConsultationService:

    @staticmethod
    async def create_consultation(
        db: AsyncSession, doctor_id: UUID, data: ConsultationCreateRequest
    ) -> Consultation:
        """Create a consultation record for a completed appointment."""
        # Verify appointment exists and belongs to this doctor
        apt = await db.get(Appointment, data.appointment_id)
        if not apt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        if apt.doctor_id != doctor_id:
            raise HTTPException(status_code=403, detail="Not your appointment")
        if apt.status != AppointmentStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail="Consultation notes can only be added to completed appointments",
            )

        consultation = Consultation(
            appointment_id=data.appointment_id,
            doctor_id=doctor_id,
            patient_id=apt.patient_id,
            chief_complaint=data.chief_complaint,
            diagnosis=data.diagnosis,
            notes=data.notes,
            treatment_plan=data.treatment_plan,
            prescriptions=[p.model_dump() for p in (data.prescriptions or [])],
            vitals=data.vitals.model_dump() if data.vitals else {},
            follow_up_date=data.follow_up_date,
            follow_up_notes=data.follow_up_notes,
        )
        db.add(consultation)
        await db.commit()
        await db.refresh(consultation)
        return consultation

    @staticmethod
    async def update_consultation(
        db: AsyncSession, consultation_id: UUID, doctor_id: UUID, data: ConsultationUpdateRequest
    ) -> Consultation:
        """Update an existing consultation record."""
        consultation = await db.get(Consultation, consultation_id)
        if not consultation:
            raise HTTPException(status_code=404, detail="Consultation not found")
        if consultation.doctor_id != doctor_id:
            raise HTTPException(status_code=403, detail="Not your consultation")

        update_data = data.model_dump(exclude_unset=True)
        if "prescriptions" in update_data and update_data["prescriptions"] is not None:
            update_data["prescriptions"] = [p.model_dump() if hasattr(p, "model_dump") else p for p in update_data["prescriptions"]]
        if "vitals" in update_data and update_data["vitals"] is not None:
            update_data["vitals"] = update_data["vitals"].model_dump() if hasattr(update_data["vitals"], "model_dump") else update_data["vitals"]

        for field, value in update_data.items():
            setattr(consultation, field, value)

        await db.commit()
        await db.refresh(consultation)
        return consultation

    @staticmethod
    async def get_consultation(db: AsyncSession, consultation_id: UUID) -> Optional[Consultation]:
        return await db.get(Consultation, consultation_id)

    @staticmethod
    async def get_by_appointment(db: AsyncSession, appointment_id: UUID) -> List[Consultation]:
        result = await db.execute(
            select(Consultation).where(Consultation.appointment_id == appointment_id).order_by(desc(Consultation.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_patient_consultations(
        db: AsyncSession, patient_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[List[Consultation], int]:
        """Get all consultations for a patient, newest first."""
        count_q = select(func.count()).select_from(Consultation).where(Consultation.patient_id == patient_id)
        total = (await db.execute(count_q)).scalar() or 0

        result = await db.execute(
            select(Consultation)
            .where(Consultation.patient_id == patient_id)
            .order_by(desc(Consultation.created_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    @staticmethod
    async def get_doctor_consultations(
        db: AsyncSession, doctor_id: UUID, patient_id: Optional[UUID] = None, limit: int = 50, offset: int = 0
    ) -> tuple[List[Consultation], int]:
        """Get all consultations by a doctor, optionally filtered by patient."""
        q = select(Consultation).where(Consultation.doctor_id == doctor_id)
        count_q = select(func.count()).select_from(Consultation).where(Consultation.doctor_id == doctor_id)

        if patient_id:
            q = q.where(Consultation.patient_id == patient_id)
            count_q = count_q.where(Consultation.patient_id == patient_id)

        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(q.order_by(desc(Consultation.created_at)).limit(limit).offset(offset))
        return result.scalars().all(), total

    @staticmethod
    async def delete_consultation(db: AsyncSession, consultation_id: UUID, doctor_id: UUID) -> bool:
        consultation = await db.get(Consultation, consultation_id)
        if not consultation:
            raise HTTPException(status_code=404, detail="Consultation not found")
        if consultation.doctor_id != doctor_id:
            raise HTTPException(status_code=403, detail="Not your consultation")
        await db.delete(consultation)
        await db.commit()
        return True

    @staticmethod
    async def enrich_consultation(db: AsyncSession, consultation: Consultation) -> ConsultationResponse:
        """Enrich a consultation with doctor/patient names and appointment details."""
        resp = ConsultationResponse.model_validate(consultation)

        doctor = await db.get(Doctor, consultation.doctor_id)
        if doctor:
            resp.doctor_name = f"{doctor.first_name} {doctor.last_name}"

        patient = await db.get(Patient, consultation.patient_id)
        if patient:
            resp.patient_name = f"{patient.first_name} {patient.last_name}"

        apt = await db.get(Appointment, consultation.appointment_id)
        if apt:
            resp.appointment_date = apt.appointment_date
            resp.consultation_type = apt.consultation_type.value if apt.consultation_type else None

        return resp
