"""
Doctor Absence Models

This module defines the database models for managing doctor absences,
including vacations, sick leave, training, and recurring unavailability.
"""

from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text, Enum, Boolean, Time, Date
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class AbsenceType(str, enum.Enum):
    """Types of doctor absences."""
    VACATION = "vacation"          # Planned vacation/holiday
    SICK = "sick"                  # Sick leave
    TRAINING = "training"          # Training/education
    CONFERENCE = "conference"      # Medical conference
    PERSONAL = "personal"          # Personal leave
    OTHER = "other"                # Other reason


class RecurrencePattern(str, enum.Enum):
    """Recurrence patterns for repeating absences."""
    NONE = "none"                  # One-time absence
    DAILY = "daily"                # Every day
    WEEKLY = "weekly"              # Same day every week
    BIWEEKLY = "biweekly"          # Every two weeks
    MONTHLY = "monthly"            # Same date every month


class DoctorAbsence(Base):
    """
    Doctor absence/unavailability periods.
    
    Represents times when a doctor is not available for appointments,
    such as vacations, training, or sick leave.
    """
    __tablename__ = "doctor_absences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Date range
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    
    # Time range (null = all day)
    start_time = Column(Time, nullable=True)  # e.g., 09:00 (partial day absence)
    end_time = Column(Time, nullable=True)    # e.g., 12:00
    
    # Absence details
    absence_type = Column(Enum(AbsenceType), default=AbsenceType.OTHER)
    title = Column(String(100), nullable=True)  # e.g., "Annual Leave"
    reason = Column(Text, nullable=True)        # Detailed reason (private)
    
    # Recurrence
    is_recurring = Column(Boolean, default=False)
    recurrence_pattern = Column(Enum(RecurrencePattern), default=RecurrencePattern.NONE)
    recurrence_end_date = Column(Date, nullable=True)  # When recurrence stops
    
    # Patient notification
    notify_patients = Column(Boolean, default=True)
    patients_notified_at = Column(DateTime, nullable=True)
    affected_appointments_count = Column(Integer, default=0)
    
    # Status tracking
    is_active = Column(Boolean, default=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Absence {self.absence_type.value} {self.start_date} to {self.end_date}>"
    
    @property
    def is_full_day(self) -> bool:
        """Check if absence covers entire days."""
        return self.start_time is None and self.end_time is None
    
    @property
    def duration_days(self) -> int:
        """Calculate number of days in the absence period."""
        return (self.end_date - self.start_date).days + 1
    
    @property
    def is_past(self) -> bool:
        """Check if absence is in the past."""
        from datetime import date
        return self.end_date < date.today()
    
    @property
    def is_current(self) -> bool:
        """Check if absence is currently active."""
        from datetime import date
        today = date.today()
        return self.start_date <= today <= self.end_date
    
    @property
    def is_future(self) -> bool:
        """Check if absence is in the future."""
        from datetime import date
        return self.start_date > date.today()
