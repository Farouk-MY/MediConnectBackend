from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from typing import Optional
from uuid import UUID
from app.models.patient import Patient
from app.schemas.patient import (
    PatientUpdateRequest,
    AddEmergencyContactRequest,
    UpdateEmergencyContactRequest
)


class PatientService:

    @staticmethod
    async def get_patient_by_user_id(db: AsyncSession, user_id: UUID) -> Optional[Patient]:
        """Get patient by user_id."""
        result = await db.execute(
            select(Patient).where(Patient.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_patient_by_id(db: AsyncSession, patient_id: UUID) -> Optional[Patient]:
        """Get patient by patient_id."""
        result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_patient_profile(
            db: AsyncSession,
            user_id: UUID,
            data: PatientUpdateRequest
    ) -> Patient:
        """Update patient profile."""

        # Get patient
        patient = await PatientService.get_patient_by_user_id(db, user_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found"
            )

        # Update fields
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if value is not None:
                # Convert Pydantic models to dicts for JSON fields
                if field in ['medical_history', 'allergies', 'current_medications', 'emergency_contacts']:
                    if value:
                        value = [item.model_dump() if hasattr(item, 'model_dump') else item for item in value]
                setattr(patient, field, value)

        await db.commit()
        await db.refresh(patient)
        return patient

    @staticmethod
    async def add_emergency_contact(
            db: AsyncSession,
            user_id: UUID,
            contact_data: AddEmergencyContactRequest
    ) -> Patient:
        """Add emergency contact to patient."""

        patient = await PatientService.get_patient_by_user_id(db, user_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found"
            )

        # Get existing contacts - make a COPY to avoid mutation issues
        contacts = list(patient.emergency_contacts) if patient.emergency_contacts else []

        # Add new contact
        new_contact = contact_data.model_dump()
        new_contact['id'] = len(contacts)  # Simple ID
        contacts.append(new_contact)

        # IMPORTANT: Force update by setting to None first, then new value
        patient.emergency_contacts = None
        await db.flush()
        patient.emergency_contacts = contacts

        await db.commit()
        await db.refresh(patient)
        return patient

    @staticmethod
    async def update_emergency_contact(
            db: AsyncSession,
            user_id: UUID,
            contact_index: int,
            contact_data: UpdateEmergencyContactRequest
    ) -> Patient:
        """Update emergency contact."""

        patient = await PatientService.get_patient_by_user_id(db, user_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found"
            )

        # Make a COPY to avoid mutation issues
        contacts = list(patient.emergency_contacts) if patient.emergency_contacts else []

        if contact_index >= len(contacts):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Emergency contact not found"
            )

        # Update contact
        update_data = contact_data.model_dump(exclude_unset=True)
        contacts[contact_index].update(update_data)

        # Force update
        patient.emergency_contacts = None
        await db.flush()
        patient.emergency_contacts = contacts

        await db.commit()
        await db.refresh(patient)
        return patient

    @staticmethod
    async def delete_emergency_contact(
            db: AsyncSession,
            user_id: UUID,
            contact_index: int
    ) -> Patient:
        """Delete emergency contact."""

        patient = await PatientService.get_patient_by_user_id(db, user_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found"
            )

        # Make a COPY to avoid mutation issues
        contacts = list(patient.emergency_contacts) if patient.emergency_contacts else []

        if contact_index >= len(contacts):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Emergency contact not found"
            )

        # Remove contact
        contacts.pop(contact_index)

        # Re-index remaining contacts
        for i, contact in enumerate(contacts):
            contact['id'] = i

        # Force update
        patient.emergency_contacts = None
        await db.flush()
        patient.emergency_contacts = contacts

        await db.commit()
        await db.refresh(patient)
        return patient