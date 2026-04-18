from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey, Text, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # Basic Professional Info (US006)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    specialty = Column(String, nullable=False)
    license_number = Column(String, unique=True, nullable=False)
    years_experience = Column(Integer, default=0)
    avatar_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    # Additional Professional Info
    education = Column(JSON, default=list)  # List of degrees/certifications
    languages = Column(JSON, default=list)  # Languages spoken

    # Cabinet/Office Information (US007)
    cabinet_address = Column(String, nullable=True)
    cabinet_city = Column(String, nullable=True)
    cabinet_country = Column(String, nullable=True)
    cabinet_postal_code = Column(String, nullable=True)
    cabinet_phone = Column(String, nullable=True)
    cabinet_email = Column(String, nullable=True)

    # Location Coordinates (for map feature)
    latitude = Column(Float, nullable=True)  # e.g., 36.8065 (Tunis)
    longitude = Column(Float, nullable=True)  # e.g., 10.1815 (Tunis)

    # Pricing (US007)
    consultation_fee_presentiel = Column(Float, default=0.0)  # In-person consultation fee
    consultation_fee_online = Column(Float, default=0.0)  # Online consultation fee
    currency = Column(String, default="TND")  # Currency code
    payment_methods = Column(JSON, default=list)  # ['cash', 'card', 'insurance']

    # Consultation Types Configuration (US008)
    offers_presentiel = Column(Boolean, default=True)  # Offers in-person consultations
    offers_online = Column(Boolean, default=False)  # Offers online consultations

    # Working Hours (for future use)
    working_hours = Column(JSON, default=dict)  # {'monday': {'start': '09:00', 'end': '17:00'}}

    # Statistics (auto-calculated)
    total_patients = Column(Integer, default=0)
    total_consultations = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)

    # Availability
    is_accepting_patients = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Doctor {self.first_name} {self.last_name} - {self.specialty}>"