from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, date, time, timezone
from uuid import UUID
from enum import Enum


class AppointmentStatus(str, Enum):
    """Appointment lifecycle statuses."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"


class ConsultationType(str, Enum):
    """Type of consultation."""
    PRESENTIEL = "presentiel"
    ONLINE = "online"


# ========== Request Schemas ==========

class AppointmentCreateRequest(BaseModel):
    """Request to create a new appointment."""
    doctor_id: UUID
    appointment_date: datetime
    consultation_type: ConsultationType
    notes: Optional[str] = Field(None, max_length=500)
    
    @validator('appointment_date')
    def validate_future_date(cls, v):
        # Make both datetimes timezone-aware for comparison
        now = datetime.now(timezone.utc)
        
        # If v is naive, assume it's UTC
        if v.tzinfo is None:
            v_aware = v.replace(tzinfo=timezone.utc)
        else:
            v_aware = v
            
        if v_aware <= now:
            raise ValueError('Appointment date must be in the future')
        
        # Return naive datetime for PostgreSQL compatibility
        # Convert to UTC first, then strip tzinfo
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class AppointmentUpdateRequest(BaseModel):
    """Request to reschedule an appointment."""
    new_date: datetime
    notes: Optional[str] = Field(None, max_length=500)
    
    @validator('new_date')
    def validate_future_date(cls, v):
        # Make both datetimes timezone-aware for comparison
        now = datetime.now(timezone.utc)
        
        # If v is naive, assume it's UTC
        if v.tzinfo is None:
            v_aware = v.replace(tzinfo=timezone.utc)
        else:
            v_aware = v
            
        if v_aware <= now:
            raise ValueError('New appointment date must be in the future')
        
        # Return naive datetime for PostgreSQL compatibility
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class AppointmentCancelRequest(BaseModel):
    """Request to cancel an appointment."""
    reason: Optional[str] = Field(None, max_length=500)


# ========== Response Schemas ==========

class DoctorBrief(BaseModel):
    """Brief doctor info for appointment display."""
    id: UUID
    first_name: str
    last_name: str
    specialty: str
    avatar_url: Optional[str] = None
    cabinet_address: Optional[str] = None
    cabinet_city: Optional[str] = None
    
    class Config:
        from_attributes = True


class PatientBrief(BaseModel):
    """Brief patient info for appointment display."""
    id: UUID
    first_name: str
    last_name: str
    date_of_birth: Optional[date] = None
    phone: Optional[str] = None
    
    class Config:
        from_attributes = True


class AppointmentResponse(BaseModel):
    """Full appointment details response."""
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    
    # Core details
    appointment_date: datetime
    duration_minutes: int
    consultation_type: ConsultationType
    status: AppointmentStatus
    confirmation_code: Optional[str] = None
    
    # Pricing
    consultation_fee: float
    currency: str
    is_paid: bool
    
    # Notes
    notes: Optional[str] = None
    
    # Video
    video_call_link: Optional[str] = None
    
    # Cancellation
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None
    cancellation_reason: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    
    # Computed flags
    is_cancellable: bool = False
    is_modifiable: bool = False
    can_join_video: bool = False
    
    class Config:
        from_attributes = True


class AppointmentDetailResponse(AppointmentResponse):
    """Appointment with doctor/patient details."""
    doctor: Optional[DoctorBrief] = None
    patient: Optional[PatientBrief] = None


class AppointmentListResponse(BaseModel):
    """Paginated appointment list."""
    appointments: List[AppointmentDetailResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


# ========== Availability Schemas ==========

class TimeSlot(BaseModel):
    """A single available time slot."""
    start_time: datetime
    end_time: datetime
    is_available: bool = True


class DayAvailability(BaseModel):
    """Available slots for a single day."""
    date: date
    slots: List[TimeSlot]


class DoctorAvailabilityResponse(BaseModel):
    """Doctor's availability for a date range."""
    doctor_id: UUID
    availability: List[DayAvailability]


# ========== Booking Confirmation ==========

class BookingConfirmation(BaseModel):
    """Response after successful booking."""
    appointment_id: UUID
    confirmation_code: str
    appointment_date: datetime
    consultation_type: ConsultationType
    doctor_name: str
    consultation_fee: float
    currency: str
    message: str = "Your appointment has been booked successfully!"


# ========== WebSocket Events ==========

class AppointmentEvent(BaseModel):
    """Real-time appointment event."""
    event_type: str  # 'created', 'confirmed', 'cancelled', 'reminder'
    appointment_id: UUID
    data: dict
