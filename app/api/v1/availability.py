from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import date
from uuid import UUID

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.availability_service import AvailabilityService
from app.schemas.availability import (
    AvailabilitySlotCreate,
    AvailabilitySlotUpdate,
    AvailabilitySlotResponse,
    WeeklyScheduleResponse,
    WorkingHoursRequest,
    ExceptionCreateRequest,
    ExceptionResponse,
    ComputedAvailabilityResponse
)


router = APIRouter(prefix="/doctors/me/schedule", tags=["Doctor Availability"])


# ==================== Weekly Schedule Endpoints ====================

@router.get("", response_model=WeeklyScheduleResponse)
async def get_my_schedule(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get my weekly availability schedule.
    
    Returns the full weekly schedule with all time slots,
    grouped by day of week.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.get_weekly_schedule(db, doctor.id)


@router.post("", response_model=AvailabilitySlotResponse)
async def create_availability_slot(
    data: AvailabilitySlotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new availability slot.
    
    Adds a time slot to your weekly schedule.
    Will throw 409 error if it overlaps with existing slots.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.create_availability_slot(db, doctor.id, data)


# ==================== Bulk Operations ====================
# NOTE: This must be defined BEFORE /{slot_id} routes to avoid path conflicts

@router.put("/working-hours", response_model=WeeklyScheduleResponse)
async def set_working_hours(
    data: WorkingHoursRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Set working hours for multiple days (bulk operation).
    
    This replaces existing slots for the specified days
    with the new schedule.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.set_working_hours(db, doctor.id, data)


# ==================== Individual Slot Operations ====================

@router.put("/{slot_id}", response_model=AvailabilitySlotResponse)
async def update_availability_slot(
    slot_id: UUID,
    data: AvailabilitySlotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an availability slot.
    
    Modify times, consultation type, or slot duration.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.update_availability_slot(db, doctor.id, slot_id, data)


@router.delete("/{slot_id}")
async def delete_availability_slot(
    slot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete an availability slot.
    
    Remove a time slot from your weekly schedule.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.delete_availability_slot(db, doctor.id, slot_id)


# ==================== Exceptions ====================

@router.post("/exception", response_model=ExceptionResponse)
async def create_exception(
    data: ExceptionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a one-off availability exception.
    
    Use this to:
    - Block specific dates/times (is_available=False)
    - Add extra availability outside normal hours (is_available=True)
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.create_exception(db, doctor.id, data)


@router.get("/exceptions", response_model=List[ExceptionResponse])
async def get_exceptions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get availability exceptions for a date range.
    
    Returns all one-off schedule changes.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.get_exceptions(db, doctor.id, start_date, end_date)


# ==================== Computed Availability ====================

@router.get("/availability", response_model=ComputedAvailabilityResponse)
async def get_computed_availability(
    start_date: date = Query(..., description="Start date of the range"),
    end_date: date = Query(..., description="End date of the range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get computed availability for a date range.
    
    This combines:
    - Weekly schedule
    - Exceptions
    - Absences
    - Existing appointments
    
    Returns actual available slots with booked status.
    """
    doctor = await AvailabilityService.get_doctor_by_user_id(db, current_user.id)
    return await AvailabilityService.get_computed_availability(db, doctor.id, start_date, end_date)


# ==================== Public Endpoint (for patients) ====================

public_router = APIRouter(prefix="/doctors", tags=["Doctor Availability (Public)"])


@public_router.get("/{doctor_id}/availability", response_model=ComputedAvailabilityResponse)
async def get_doctor_availability_public(
    doctor_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a doctor's availability for booking (public endpoint).
    
    Returns available time slots that patients can book.
    """
    return await AvailabilityService.get_computed_availability(db, doctor_id, start_date, end_date)
