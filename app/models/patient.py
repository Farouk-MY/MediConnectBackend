from sqlalchemy import Column, String, DateTime, Date, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # Basic Info
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)  # 'male', 'female', 'other'
    blood_type = Column(String, nullable=True)  # 'A+', 'B-', etc.

    # Contact Info
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)

    # Profile
    avatar_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    # Medical Information (JSON arrays)
    medical_history = Column(JSON, default=list)  # List of medical conditions
    allergies = Column(JSON, default=list)  # List of allergies
    current_medications = Column(JSON, default=list)  # List of current meds
    emergency_contacts = Column(JSON, default=list)  # List of emergency contacts

    # QR Code (encrypted patient data)
    qr_code_data = Column(Text, nullable=True)  # Encrypted QR payload
    qr_code_updated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Patient {self.first_name} {self.last_name}>"