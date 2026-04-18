from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
from uuid import UUID


# QR Code Data Structure (what goes inside the QR)
class QRPatientData(BaseModel):
    """Data structure that will be encrypted in QR code."""
    patient_id: UUID
    first_name: str
    last_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None

    # Critical medical info
    allergies: List[dict] = []
    medical_history: List[dict] = []
    current_medications: List[dict] = []
    emergency_contacts: List[dict] = []

    # Metadata
    generated_at: datetime


# QR Code Generation Response
class QRCodeResponse(BaseModel):
    """Response when generating QR code."""
    qr_data: str  # Encrypted data for QR code
    generated_at: datetime
    patient_id: UUID


# QR Code Scan Request (from doctor)
class QRCodeScanRequest(BaseModel):
    """Request to decrypt scanned QR code."""
    qr_data: str  # The encrypted data from scanned QR


# QR Code Scan Response (decrypted patient data)
class QRCodeScanResponse(BaseModel):
    """Decrypted patient data from QR code scan."""
    patient_id: UUID
    first_name: str
    last_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None
    allergies: List[dict] = []
    medical_history: List[dict] = []
    current_medications: List[dict] = []
    emergency_contacts: List[dict] = []
    generated_at: datetime