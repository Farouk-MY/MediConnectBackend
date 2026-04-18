from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User, UserRole
from app.schemas.qr import QRCodeResponse, QRCodeScanRequest, QRCodeScanResponse
from app.services.patient_service import PatientService
from app.services.qr_service import QRService

router = APIRouter(prefix="/qr", tags=["QR Code"])


@router.get("/generate", response_model=QRCodeResponse)
async def generate_my_qr_code(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Generate QR code for current patient.

    This endpoint creates an encrypted QR code containing the patient's
    medical information. The QR code can be scanned by doctors during
    in-person consultations.

    - **Returns**: Encrypted QR data string to be encoded in QR image
    - **Requires**: Patient role
    """

    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can generate QR codes"
        )

    # Get patient profile
    patient = await PatientService.get_patient_by_user_id(db, current_user.id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )

    # Generate encrypted QR data
    qr_response = QRService.generate_qr_data(patient)

    # Store QR data in database for tracking
    patient.qr_code_data = qr_response.qr_data
    patient.qr_code_updated_at = datetime.utcnow()
    await db.commit()

    return qr_response


@router.post("/scan", response_model=QRCodeScanResponse)
async def scan_patient_qr_code(
        scan_request: QRCodeScanRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Scan and decrypt patient QR code.

    This endpoint is used by doctors to scan a patient's QR code
    during in-person consultations. It decrypts the QR data and
    returns the patient's medical information.

    - **Requires**: Doctor role
    - **Input**: Encrypted QR data string (scanned from QR code)
    - **Returns**: Decrypted patient medical information
    """

    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can scan patient QR codes"
        )

    # Decrypt QR data
    scan_response = QRService.decrypt_qr_data(scan_request.qr_data)

    # Check if QR is fresh (optional warning)
    is_fresh = QRService.validate_qr_freshness(scan_response, max_age_days=30)

    if not is_fresh:
        # Could add a warning field in response, but for now just return data
        # In production, you might want to log this or notify
        pass

    return scan_response


@router.get("/my-qr-status")
async def get_my_qr_status(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Get QR code generation status for current patient.

    Returns information about when the QR code was last generated
    and whether it needs to be regenerated.
    """

    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can check QR status"
        )

    patient = await PatientService.get_patient_by_user_id(db, current_user.id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )

    has_qr = patient.qr_code_data is not None
    last_updated = patient.qr_code_updated_at

    needs_regeneration = False
    if has_qr and last_updated:
        age = datetime.utcnow() - last_updated
        needs_regeneration = age.days > 30

    return {
        "has_qr_code": has_qr,
        "last_updated": last_updated,
        "needs_regeneration": needs_regeneration or not has_qr,
        "recommendation": "Please generate a new QR code" if needs_regeneration or not has_qr else "QR code is up to date"
    }