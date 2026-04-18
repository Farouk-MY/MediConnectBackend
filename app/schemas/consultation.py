from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from uuid import UUID


# ========== Vitals Schema ==========
class VitalsSchema(BaseModel):
    blood_pressure: Optional[str] = None        # e.g. "120/80"
    heart_rate: Optional[int] = None            # bpm
    temperature: Optional[float] = None         # Celsius
    weight: Optional[float] = None              # kg
    height: Optional[float] = None              # cm
    spo2: Optional[int] = None                  # SpO2 %


# ========== Prescription Schema ==========
class PrescriptionItem(BaseModel):
    medication: str
    dosage: str = ""                            # e.g. "500mg"
    frequency: str = ""                         # e.g. "2x/day"
    duration: str = ""                          # e.g. "7 days"
    notes: Optional[str] = None


# ========== Create / Update ==========
class ConsultationCreateRequest(BaseModel):
    appointment_id: UUID
    chief_complaint: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    treatment_plan: Optional[str] = None
    prescriptions: Optional[List[PrescriptionItem]] = []
    vitals: Optional[VitalsSchema] = None
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None


class ConsultationUpdateRequest(BaseModel):
    chief_complaint: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    treatment_plan: Optional[str] = None
    prescriptions: Optional[List[PrescriptionItem]] = None
    vitals: Optional[VitalsSchema] = None
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None


# ========== Response ==========
class ConsultationResponse(BaseModel):
    id: UUID
    appointment_id: UUID
    doctor_id: UUID
    patient_id: UUID
    chief_complaint: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    treatment_plan: Optional[str] = None
    prescriptions: List[Dict[str, Any]] = []
    vitals: Dict[str, Any] = {}
    follow_up_date: Optional[date] = None
    follow_up_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Enriched fields (populated by API)
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None
    appointment_date: Optional[datetime] = None
    consultation_type: Optional[str] = None

    model_config = {"from_attributes": True}


class ConsultationListResponse(BaseModel):
    consultations: List[ConsultationResponse]
    total: int
