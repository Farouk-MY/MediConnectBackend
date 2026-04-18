from datetime import datetime
from typing import Optional
import json
from fastapi import HTTPException, status
from app.models.patient import Patient
from app.schemas.qr import QRPatientData, QRCodeResponse, QRCodeScanResponse
from app.core.security import encrypt_data, decrypt_data


class QRService:

    @staticmethod
    def generate_qr_data(patient: Patient) -> QRCodeResponse:
        """
        Generate encrypted QR code data for a patient.

        This creates a JSON payload with patient info, encrypts it,
        and returns the encrypted string that will be encoded in the QR code.
        """

        # Create patient data payload
        qr_payload = QRPatientData(
            patient_id=patient.id,
            first_name=patient.first_name,
            last_name=patient.last_name,
            date_of_birth=patient.date_of_birth,
            gender=patient.gender,
            blood_type=patient.blood_type,
            phone=patient.phone,
            allergies=patient.allergies or [],
            medical_history=patient.medical_history or [],
            current_medications=patient.current_medications or [],
            emergency_contacts=patient.emergency_contacts or [],
            generated_at=datetime.utcnow()
        )

        # Convert to JSON string
        json_data = qr_payload.model_dump_json()

        # Encrypt the JSON data
        encrypted_data = encrypt_data(json_data)

        return QRCodeResponse(
            qr_data=encrypted_data,
            generated_at=datetime.utcnow(),
            patient_id=patient.id
        )

    @staticmethod
    def decrypt_qr_data(encrypted_qr_data: str) -> QRCodeScanResponse:
        """
        Decrypt and validate QR code data scanned by a doctor.

        Takes the encrypted string from QR code, decrypts it,
        and returns the patient information.
        """

        # Decrypt the data
        decrypted_json = decrypt_data(encrypted_qr_data)

        if not decrypted_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or corrupted QR code data"
            )

        try:
            # Parse JSON
            data = json.loads(decrypted_json)

            # Validate and return as response model
            return QRCodeScanResponse(**data)

        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse QR code data: {str(e)}"
            )

    @staticmethod
    def validate_qr_freshness(scan_response: QRCodeScanResponse, max_age_days: int = 30) -> bool:
        """
        Check if QR code is not too old.

        QR codes older than max_age_days should prompt patient to regenerate.
        """
        age = datetime.utcnow() - scan_response.generated_at
        return age.days <= max_age_days