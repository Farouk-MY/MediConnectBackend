"""
Doctor Availability Models

This module defines the database models for managing doctor availability,
including weekly recurring schedules and one-off exceptions.
"""

from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey, Text, Enum, Boolean, Time, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, time
import uuid
import enum
from app.core.database import Base


class DayOfWeek(int, enum.Enum):
    """Days of the week (0 = Monday, 6 = Sunday)."""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class ConsultationTypeAvailability(str, enum.Enum):
    """Types of consultations available for a time slot."""
    PRESENTIEL = "presentiel"      # In-person only
    ONLINE = "online"              # Online only
    BOTH = "both"                  # Both types available


class DoctorAvailability(Base):
    """
    Weekly recurring availability schedule for a doctor.
    
    Each record represents a time slot on a specific day of the week
    when the doctor is available for consultations.
    """
    __tablename__ = "doctor_availabilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Day and time configuration
    day_of_week = Column(Integer, nullable=False, index=True)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)  # e.g., 09:00
    end_time = Column(Time, nullable=False)    # e.g., 17:00
    
    # Consultation settings
    consultation_type = Column(Enum(ConsultationTypeAvailability), default=ConsultationTypeAvailability.BOTH)
    slot_duration_minutes = Column(Integer, default=30)  # Duration per appointment slot
    
    # Break configuration (optional)
    break_start = Column(Time, nullable=True)  # e.g., 12:00
    break_end = Column(Time, nullable=True)    # e.g., 13:00
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        day_name = days[self.day_of_week] if 0 <= self.day_of_week <= 6 else '?'
        return f"<Availability {day_name} {self.start_time}-{self.end_time}>"
    
    @property
    def total_minutes(self) -> int:
        """Calculate total available minutes, excluding break."""
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        total = end - start
        
        if self.break_start and self.break_end:
            break_start = self.break_start.hour * 60 + self.break_start.minute
            break_end = self.break_end.hour * 60 + self.break_end.minute
            total -= (break_end - break_start)
        
        return max(0, total)
    
    @property
    def slot_count(self) -> int:
        """Calculate number of available appointment slots."""
        if self.slot_duration_minutes <= 0:
            return 0
        return self.total_minutes // self.slot_duration_minutes


class AvailabilityException(Base):
    """
    One-off exceptions to the regular weekly schedule.
    
    Can be used to:
    - Block specific dates/times (is_available=False)
    - Add extra availability outside normal hours (is_available=True)
    """
    __tablename__ = "availability_exceptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Date configuration
    exception_date = Column(Date, nullable=False, index=True)
    
    # Time window (null = entire day)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    
    # Exception type
    is_available = Column(Boolean, default=False)  # False=blocked, True=extra availability
    
    # Consultation type (for extra availability)
    consultation_type = Column(Enum(ConsultationTypeAvailability), nullable=True)
    
    # Reason/notes
    reason = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        status = "Available" if self.is_available else "Blocked"
        return f"<Exception {self.exception_date} {status}>"
    
    @property
    def is_full_day(self) -> bool:
        """Check if this exception covers the entire day."""
        return self.start_time is None and self.end_time is None
