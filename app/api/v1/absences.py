"""
Absence API Endpoints

REST API for managing doctor absences including
vacations, sick leave, training, and recurring unavailability.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import date
from uuid import UUID

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.absence_service import AbsenceService
from app.schemas.absence import (
    AbsenceCreateRequest,
    AbsenceUpdateRequest,
    AbsenceResponse,
    AbsenceListResponse,
    AbsenceCreateResponse,
    ConflictCheckRequest,
    ConflictCheckResponse
)


router = APIRouter(prefix="/doctors/me/absences", tags=["Doctor Absences"])


# ==================== CRUD Endpoints ====================

@router.get("", response_model=AbsenceListResponse)
async def get_my_absences(
    include_past: bool = Query(False, description="Include past absences"),
    include_cancelled: bool = Query(False, description="Include cancelled absences"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of my absences.
    
    By default, returns only upcoming active absences.
    """
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    return await AbsenceService.get_absences(db, doctor.id, include_past, include_cancelled)


@router.post("", response_model=AbsenceCreateResponse)
async def create_absence(
    data: AbsenceCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new absence.
    
    Checks for appointment conflicts and optionally
    notifies affected patients.
    
    Returns the created absence along with conflict information.
    """
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    return await AbsenceService.create_absence(db, doctor.id, data)


@router.get("/{absence_id}", response_model=AbsenceResponse)
async def get_absence(
    absence_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single absence by ID."""
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    return await AbsenceService.get_absence_by_id(db, doctor.id, absence_id)


@router.put("/{absence_id}", response_model=AbsenceResponse)
async def update_absence(
    absence_id: UUID,
    data: AbsenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing absence.
    
    If dates are modified, conflicts are rechecked.
    """
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    return await AbsenceService.update_absence(db, doctor.id, absence_id, data)


@router.delete("/{absence_id}")
async def delete_absence(
    absence_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete (cancel) an absence.
    
    This is a soft delete - the absence is marked as inactive.
    """
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    return await AbsenceService.delete_absence(db, doctor.id, absence_id)


# ==================== Conflict Check ====================

@router.post("/check-conflicts", response_model=ConflictCheckResponse)
async def check_conflicts(
    data: ConflictCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check for appointment conflicts before creating an absence.
    
    Use this to preview which appointments will be affected
    by a potential absence.
    """
    doctor = await AbsenceService.get_doctor_by_user_id(db, current_user.id)
    
    start_time = None
    end_time = None
    if data.start_time:
        parts = data.start_time.split(':')
        from datetime import time
        start_time = time(int(parts[0]), int(parts[1]))
    if data.end_time:
        parts = data.end_time.split(':')
        from datetime import time
        end_time = time(int(parts[0]), int(parts[1]))
    
    return await AbsenceService.check_conflicts(
        db, doctor.id,
        data.start_date, data.end_date,
        start_time, end_time
    )
