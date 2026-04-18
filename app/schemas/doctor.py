from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


# Education/Certification Item
class EducationItem(BaseModel):
    degree: str
    institution: str
    year: int
    country: Optional[str] = None


# Doctor Update Request (US006, US007, US008 combined)
class DoctorUpdateRequest(BaseModel):
    # Basic Professional Info (US006)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    specialty: Optional[str] = None
    years_experience: Optional[int] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    education: Optional[List[EducationItem]] = None
    languages: Optional[List[str]] = None

    # Cabinet Information (US007)
    cabinet_address: Optional[str] = None
    cabinet_city: Optional[str] = None
    cabinet_country: Optional[str] = None
    cabinet_postal_code: Optional[str] = None
    cabinet_phone: Optional[str] = None
    cabinet_email: Optional[str] = None

    # Location Coordinates (for map)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Pricing (US007)
    consultation_fee_presentiel: Optional[float] = None
    consultation_fee_online: Optional[float] = None
    currency: Optional[str] = None
    payment_methods: Optional[List[str]] = None

    # Consultation Types (US008)
    offers_presentiel: Optional[bool] = None
    offers_online: Optional[bool] = None

    # Availability
    is_accepting_patients: Optional[bool] = None

    @validator('consultation_fee_presentiel', 'consultation_fee_online')
    def validate_fees(cls, v):
        if v is not None and v < 0:
            raise ValueError('Consultation fee cannot be negative')
        return v

    @validator('years_experience')
    def validate_experience(cls, v):
        if v is not None and (v < 0 or v > 70):
            raise ValueError('Years of experience must be between 0 and 70')
        return v

    @validator('latitude')
    def validate_latitude(cls, v):
        if v is not None and (v < -90 or v > 90):
            raise ValueError('Latitude must be between -90 and 90')
        return v

    @validator('longitude')
    def validate_longitude(cls, v):
        if v is not None and (v < -180 or v > 180):
            raise ValueError('Longitude must be between -180 and 180')
        return v

    @validator('payment_methods')
    def validate_payment_methods(cls, v):
        valid_methods = ['cash', 'card', 'insurance', 'mobile_payment', 'bank_transfer']
        if v:
            for method in v:
                if method not in valid_methods:
                    raise ValueError(f'Invalid payment method: {method}. Must be one of {valid_methods}')
        return v


# Doctor Response
class DoctorResponse(BaseModel):
    id: UUID
    user_id: UUID

    # Professional Info
    first_name: str
    last_name: str
    specialty: str
    license_number: str
    years_experience: int
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    education: List[dict] = []
    languages: List[str] = []

    # Cabinet Info
    cabinet_address: Optional[str] = None
    cabinet_city: Optional[str] = None
    cabinet_country: Optional[str] = None
    cabinet_postal_code: Optional[str] = None
    cabinet_phone: Optional[str] = None
    cabinet_email: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Pricing
    consultation_fee_presentiel: float
    consultation_fee_online: float
    currency: str
    payment_methods: List[str] = []

    # Consultation Types
    offers_presentiel: bool
    offers_online: bool

    # Statistics
    total_patients: int
    total_consultations: int
    average_rating: float

    # Availability
    is_accepting_patients: bool

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Public Doctor Profile (for patient search - less detailed)
class DoctorPublicProfile(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    specialty: str
    years_experience: int
    bio: Optional[str] = None
    avatar_url: Optional[str] = None

    # Location
    cabinet_city: Optional[str] = None
    cabinet_country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Pricing
    consultation_fee_presentiel: float
    consultation_fee_online: float
    currency: str

    # Consultation Types
    offers_presentiel: bool
    offers_online: bool

    # Statistics
    average_rating: float
    total_consultations: int

    # Availability
    is_accepting_patients: bool

    class Config:
        from_attributes = True


# Consultation Type Configuration Request (US008)
class ConsultationTypeConfigRequest(BaseModel):
    offers_presentiel: bool
    offers_online: bool
    consultation_fee_presentiel: Optional[float] = None
    consultation_fee_online: Optional[float] = None

    @validator('offers_presentiel', 'offers_online')
    def at_least_one_type(cls, v, values):
        # Ensure at least one consultation type is offered
        if 'offers_presentiel' in values:
            if not v and not values.get('offers_presentiel'):
                raise ValueError('At least one consultation type must be offered')
        return v