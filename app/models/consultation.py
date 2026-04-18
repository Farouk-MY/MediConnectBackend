from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Float, JSON, Date
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.core.database import Base


class Consultation(Base):
    """Post-appointment consultation record with medical notes."""
    __tablename__ = "consultations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationships
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)

    # Clinical Notes
    chief_complaint = Column(Text, nullable=True)          # Main reason for visit
    diagnosis = Column(Text, nullable=True)                 # Doctor's diagnosis
    notes = Column(Text, nullable=True)                     # Detailed clinical notes
    treatment_plan = Column(Text, nullable=True)            # Recommended treatment

    # Prescriptions (JSON array of {medication, dosage, frequency, duration, notes})
    prescriptions = Column(JSON, default=list)

    # Vitals (JSON: {blood_pressure, heart_rate, temperature, weight, height, spo2})
    vitals = Column(JSON, default=dict)

    # Follow-up
    follow_up_date = Column(Date, nullable=True)
    follow_up_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Consultation {self.id} for appointment {self.appointment_id}>"
