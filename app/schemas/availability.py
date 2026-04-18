"""
Availability Schemas

Pydantic schemas for doctor availability management including
weekly schedules, time slots, and availability exceptions.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import time, date
from uuid import UUID
from enum import Enum


# ========== Enums ==========

class DayOfWeek(int, Enum):
    """Days of the week (0 = Monday, 6 = Sunday)."""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class ConsultationTypeAvailability(str, Enum):
    """Types of consultations available for a time slot."""
    PRESENTIEL = "presentiel"
    ONLINE = "online"
    BOTH = "both"


# ========== Request Schemas ==========

class AvailabilitySlotCreate(BaseModel):
    """Request to create a weekly availability slot."""
    day_of_week: int = Field(..., ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Start time in HH:MM format")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="End time in HH:MM format")
    consultation_type: ConsultationTypeAvailability = ConsultationTypeAvailability.BOTH
    slot_duration_minutes: int = Field(default=30, ge=10, le=120, description="Duration per slot in minutes")
    break_start: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Break start time")
    break_end: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Break end time")
    
    @field_validator('end_time')
    @classmethod
    def validate_end_after_start(cls, v, info):
        start = info.data.get('start_time')
        if start and v <= start:
            raise ValueError('End time must be after start time')
        return v


class AvailabilitySlotUpdate(BaseModel):
    """Request to update an availability slot."""
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    consultation_type: Optional[ConsultationTypeAvailability] = None
    slot_duration_minutes: Optional[int] = Field(None, ge=10, le=120)
    break_start: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    break_end: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    is_active: Optional[bool] = None


class DayScheduleRequest(BaseModel):
    """Request to set a day's full schedule."""
    day_of_week: int = Field(..., ge=0, le=6)
    is_working_day: bool = True
    slots: List[AvailabilitySlotCreate] = Field(default_factory=list)


class WorkingHoursRequest(BaseModel):
    """Bulk request to set working hours for multiple days."""
    schedule: List[DayScheduleRequest]
    default_slot_duration: int = Field(default=30, ge=10, le=120)
    default_consultation_type: ConsultationTypeAvailability = ConsultationTypeAvailability.BOTH


class ExceptionCreateRequest(BaseModel):
    """Request to create a one-off availability exception."""
    exception_date: date
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Null for full day")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Null for full day")
    is_available: bool = Field(default=False, description="True=extra availability, False=blocked")
    consultation_type: Optional[ConsultationTypeAvailability] = None
    reason: Optional[str] = Field(None, max_length=255)


# ========== Response Schemas ==========

class AvailabilitySlotResponse(BaseModel):
    """Response for a single availability slot."""
    id: UUID
    doctor_id: UUID
    day_of_week: int
    start_time: str
    end_time: str
    consultation_type: ConsultationTypeAvailability
    slot_duration_minutes: int
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    is_active: bool
    slot_count: int
    created_at: str
    
    class Config:
        from_attributes = True


class DayScheduleResponse(BaseModel):
    """Response for a single day's schedule."""
    day_of_week: int
    day_name: str
    is_working_day: bool
    slots: List[AvailabilitySlotResponse]
    total_hours: float
    total_slots: int


class WeeklyScheduleResponse(BaseModel):
    """Response with full weekly schedule."""
    doctor_id: UUID
    schedule: List[DayScheduleResponse]
    default_slot_duration: int
    default_consultation_type: ConsultationTypeAvailability


class ExceptionResponse(BaseModel):
    """Response for an availability exception."""
    id: UUID
    doctor_id: UUID
    exception_date: date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: bool
    is_full_day: bool
    consultation_type: Optional[ConsultationTypeAvailability] = None
    reason: Optional[str] = None
    created_at: str
    
    class Config:
        from_attributes = True


# ========== Computed Availability ==========

class ComputedTimeSlot(BaseModel):
    """A computed available time slot for a specific date."""
    start_time: str
    end_time: str
    is_available: bool
    is_booked: bool = False
    appointment_id: Optional[UUID] = None
    consultation_type: ConsultationTypeAvailability


class ComputedDayAvailability(BaseModel):
    """Computed availability for a specific date."""
    date: date
    day_of_week: int
    day_name: str
    is_working_day: bool
    is_blocked: bool = False  # Due to absence
    block_reason: Optional[str] = None
    slots: List[ComputedTimeSlot]
    available_slot_count: int
    booked_slot_count: int


class ComputedAvailabilityResponse(BaseModel):
    """Computed availability for a date range."""
    doctor_id: UUID
    start_date: date
    end_date: date
    days: List[ComputedDayAvailability]
