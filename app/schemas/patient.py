from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID


# Emergency Contact Schema
class EmergencyContact(BaseModel):
    name: str
    relationship: str  # 'spouse', 'parent', 'sibling', 'friend', etc.
    phone: str
    email: Optional[str] = None


# Medical History Item
class MedicalHistoryItem(BaseModel):
    condition: str
    diagnosed_date: Optional[str] = None
    notes: Optional[str] = None


# Allergy Item
class AllergyItem(BaseModel):
    allergen: str
    severity: str  # 'mild', 'moderate', 'severe'
    reaction: Optional[str] = None


# Current Medication Item
class MedicationItem(BaseModel):
    name: str
    dosage: str
    frequency: str
    prescribed_by: Optional[str] = None


# Patient Update Request
class PatientUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None

    medical_history: Optional[List[MedicalHistoryItem]] = None
    allergies: Optional[List[AllergyItem]] = None
    current_medications: Optional[List[MedicationItem]] = None
    emergency_contacts: Optional[List[EmergencyContact]] = None

    @validator('gender')
    def validate_gender(cls, v):
        if v and v not in ['male', 'female', 'other']:
            raise ValueError('Gender must be male, female, or other')
        return v

    @validator('blood_type')
    def validate_blood_type(cls, v):
        valid_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
        if v and v not in valid_types:
            raise ValueError(f'Blood type must be one of {valid_types}')
        return v


# Patient Response
class PatientResponse(BaseModel):
    id: UUID
    user_id: UUID
    first_name: str
    last_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None

    medical_history: List[dict] = []
    allergies: List[dict] = []
    current_medications: List[dict] = []
    emergency_contacts: List[dict] = []

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Emergency Contact Management
class AddEmergencyContactRequest(BaseModel):
    name: str = Field(..., min_length=1)
    relationship: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    email: Optional[str] = None


class UpdateEmergencyContactRequest(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None