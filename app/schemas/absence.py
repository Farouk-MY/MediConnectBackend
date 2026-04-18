"""
Absence Schemas

Pydantic schemas for doctor absence management including
vacations, sick leave, training, and recurring unavailability.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID
from enum import Enum


# ========== Enums ==========

class AbsenceType(str, Enum):
    """Types of doctor absences."""
    VACATION = "vacation"
    SICK = "sick"
    TRAINING = "training"
    CONFERENCE = "conference"
    PERSONAL = "personal"
    OTHER = "other"


class RecurrencePattern(str, Enum):
    """Recurrence patterns for repeating absences."""
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


# ========== Request Schemas ==========

class AbsenceCreateRequest(BaseModel):
    """Request to create a doctor absence."""
    start_date: date
    end_date: date
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Null for full day")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Null for full day")
    absence_type: AbsenceType = AbsenceType.OTHER
    title: Optional[str] = Field(None, max_length=100)
    reason: Optional[str] = Field(None, max_length=500)
    is_recurring: bool = False
    recurrence_pattern: RecurrencePattern = RecurrencePattern.NONE
    recurrence_end_date: Optional[date] = None
    notify_patients: bool = True
    
    @field_validator('end_date')
    @classmethod
    def validate_end_after_start(cls, v, info):
        start = info.data.get('start_date')
        if start and v < start:
            raise ValueError('End date must be on or after start date')
        return v
    
    @field_validator('recurrence_end_date')
    @classmethod
    def validate_recurrence_end(cls, v, info):
        if v:
            end_date = info.data.get('end_date')
            if end_date and v < end_date:
                raise ValueError('Recurrence end date must be after absence end date')
        return v


class AbsenceUpdateRequest(BaseModel):
    """Request to update an existing absence."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    absence_type: Optional[AbsenceType] = None
    title: Optional[str] = Field(None, max_length=100)
    reason: Optional[str] = Field(None, max_length=500)
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[RecurrencePattern] = None
    recurrence_end_date: Optional[date] = None
    notify_patients: Optional[bool] = None
    is_active: Optional[bool] = None


class ConflictCheckRequest(BaseModel):
    """Request to check for appointment conflicts."""
    start_date: date
    end_date: date
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")


# ========== Response Schemas ==========

class AffectedAppointment(BaseModel):
    """Brief info about an appointment affected by an absence."""
    id: UUID
    appointment_date: datetime
    patient_name: str
    patient_phone: Optional[str] = None
    consultation_type: str
    status: str


class AbsenceResponse(BaseModel):
    """Full absence response."""
    id: UUID
    doctor_id: UUID
    start_date: date
    end_date: date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    absence_type: AbsenceType
    title: Optional[str] = None
    reason: Optional[str] = None
    is_recurring: bool
    recurrence_pattern: RecurrencePattern
    recurrence_end_date: Optional[date] = None
    notify_patients: bool
    patients_notified_at: Optional[datetime] = None
    affected_appointments_count: int
    is_active: bool
    is_full_day: bool
    duration_days: int
    is_past: bool
    is_current: bool
    is_future: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AbsenceListResponse(BaseModel):
    """Paginated list of absences."""
    absences: List[AbsenceResponse]
    total: int
    upcoming_count: int
    past_count: int


class ConflictCheckResponse(BaseModel):
    """Response for conflict check."""
    has_conflicts: bool
    affected_count: int
    affected_appointments: List[AffectedAppointment]
    recommendation: str  # e.g., "3 confirmed appointments need attention"


class AbsenceCreateResponse(BaseModel):
    """Response after creating an absence."""
    absence: AbsenceResponse
    conflicts: ConflictCheckResponse
    message: str


# ========== WebSocket Events ==========

class AbsenceEvent(BaseModel):
    """Real-time absence event for WebSocket."""
    event_type: str  # 'created', 'updated', 'cancelled'
    absence_id: UUID
    doctor_id: UUID
    data: dict
