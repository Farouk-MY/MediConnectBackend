from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey, Text, Enum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class AppointmentStatus(str, enum.Enum):
    """Appointment lifecycle statuses."""
    PENDING = "pending"           # Awaiting doctor confirmation
    CONFIRMED = "confirmed"       # Doctor confirmed
    CANCELLED = "cancelled"       # Cancelled by patient or doctor
    COMPLETED = "completed"       # Consultation done
    NO_SHOW = "no_show"           # Patient didn't show up
    RESCHEDULED = "rescheduled"   # Moved to new time (creates new appointment)


class ConsultationType(str, enum.Enum):
    """Type of consultation."""
    PRESENTIEL = "presentiel"     # In-person at cabinet
    ONLINE = "online"             # Video consultation


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Relationships
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Appointment Details
    appointment_date = Column(DateTime, nullable=False, index=True)  # Start datetime
    duration_minutes = Column(Integer, default=30)  # Default 30 min slot
    consultation_type = Column(Enum(ConsultationType), nullable=False)
    
    # Status & Lifecycle
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.PENDING, index=True)
    
    # Cancellation Info
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(String, nullable=True)  # 'patient' or 'doctor'
    cancellation_reason = Column(Text, nullable=True)
    
    # Rescheduling
    rescheduled_from_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True)
    rescheduled_to_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Consultation Details
    notes = Column(Text, nullable=True)  # Patient notes for doctor
    doctor_notes = Column(Text, nullable=True)  # Doctor's private notes
    
    # For Online Consultations
    video_call_link = Column(String, nullable=True)
    video_call_room_id = Column(String, nullable=True)
    
    # Pricing (snapshot at booking time)
    consultation_fee = Column(Float, nullable=False)
    currency = Column(String, default="TND")
    
    # Payment Status
    is_paid = Column(Boolean, default=False)
    payment_method = Column(String, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    
    # Reminders
    reminder_sent = Column(Boolean, default=False)
    reminder_24h_sent = Column(Boolean, default=False)
    reminder_1h_sent = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Confirmation
    confirmation_code = Column(String(12), unique=True, nullable=True)  # e.g., "MC-A7B3X2"
    confirmed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Appointment {self.id} - {self.status.value} - {self.appointment_date}>"
    
    @property
    def is_cancellable(self) -> bool:
        """Check if appointment can be cancelled (24h before)."""
        if self.status in [AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW]:
            return False
        from datetime import timedelta
        return datetime.utcnow() + timedelta(hours=24) < self.appointment_date
    
    @property
    def is_modifiable(self) -> bool:
        """Check if appointment can be rescheduled (24h before)."""
        return self.is_cancellable
    
    @property
    def can_join_video(self) -> bool:
        """Check if video call can be joined (15 min before to 1h after start)."""
        if self.consultation_type != ConsultationType.ONLINE:
            return False
        if self.status != AppointmentStatus.CONFIRMED:
            return False
        from datetime import timedelta
        now = datetime.utcnow()
        start_window = self.appointment_date - timedelta(minutes=15)
        end_window = self.appointment_date + timedelta(hours=1)
        return start_window <= now <= end_window
