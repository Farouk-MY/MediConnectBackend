from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User, UserRole
from app.schemas.patient import (
    PatientResponse,
    PatientUpdateRequest,
    AddEmergencyContactRequest,
    UpdateEmergencyContactRequest
)
from app.services.patient_service import PatientService
from app.core.websocket import profile_manager

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/me", response_model=PatientResponse)
async def get_my_profile(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get current patient's profile.

    Requires patient role.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )

    patient = await PatientService.get_patient_by_user_id(db, current_user.id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )

    return patient


@router.put("/me", response_model=PatientResponse)
async def update_my_profile(
        data: PatientUpdateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Update current patient's profile.

    Can update:
    - Basic info (name, DOB, gender, blood type)
    - Contact info (phone, address, city, country)
    - Medical info (history, allergies, medications)
    - Emergency contacts
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )

    patient = await PatientService.update_patient_profile(db, current_user.id, data)
    
    # Broadcast real-time update via WebSocket
    await profile_manager.broadcast_to_user(
        str(current_user.id),
        {
            "type": "profile_update",
            "data": PatientResponse.model_validate(patient).model_dump(mode='json')
        }
    )
    
    return patient


@router.post("/me/emergency-contacts", response_model=PatientResponse)
async def add_emergency_contact(
        contact: AddEmergencyContactRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Add an emergency contact.

    Emergency contacts will be notified in case of medical emergencies.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )

    patient = await PatientService.add_emergency_contact(db, current_user.id, contact)
    return patient


@router.put("/me/emergency-contacts/{contact_index}", response_model=PatientResponse)
async def update_emergency_contact(
        contact_index: int,
        contact: UpdateEmergencyContactRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Update an emergency contact by index.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )

    patient = await PatientService.update_emergency_contact(
        db, current_user.id, contact_index, contact
    )
    return patient


@router.delete("/me/emergency-contacts/{contact_index}", response_model=PatientResponse)
async def delete_emergency_contact(
        contact_index: int,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Delete an emergency contact by index.
    """
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )

    patient = await PatientService.delete_emergency_contact(
        db, current_user.id, contact_index
    )
    return patient