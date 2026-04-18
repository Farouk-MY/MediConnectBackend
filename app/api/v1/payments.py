"""
Payment API Endpoints

Handles Stripe payment flow for online consultations.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from pydantic import BaseModel

from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User
from app.services.payment_service import PaymentService


router = APIRouter(prefix="/payments", tags=["Payments"])


# ========== Schemas ==========

class PaymentIntentResponse(BaseModel):
    client_secret: str
    publishable_key: str
    amount: float
    currency: str
    payment_intent_id: str


class PaymentConfirmRequest(BaseModel):
    payment_intent_id: str


class PaymentConfirmResponse(BaseModel):
    status: str
    appointment_id: str
    is_paid: bool


# ========== Endpoints ==========

@router.post(
    "/create-intent/{appointment_id}",
    response_model=PaymentIntentResponse
)
async def create_payment_intent(
    appointment_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe PaymentIntent for an appointment.
    
    Returns client_secret for the mobile PaymentSheet.
    Only works for confirmed online consultations.
    """
    return await PaymentService.create_payment_intent(
        db=db,
        appointment_id=appointment_id,
        patient_user_id=current_user.id
    )


@router.post(
    "/confirm/{appointment_id}",
    response_model=PaymentConfirmResponse
)
async def confirm_payment(
    appointment_id: UUID,
    data: PaymentConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Confirm payment after PaymentSheet success.
    
    Verifies with Stripe and marks appointment as paid.
    """
    appointment = await PaymentService.confirm_payment(
        db=db,
        appointment_id=appointment_id,
        patient_user_id=current_user.id,
        payment_intent_id=data.payment_intent_id
    )

    return PaymentConfirmResponse(
        status="paid",
        appointment_id=str(appointment.id),
        is_paid=appointment.is_paid
    )


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handle Stripe webhook events.
    
    Processes payment_intent.succeeded to auto-mark appointments as paid.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    result = await PaymentService.handle_webhook(
        db=db,
        payload=payload,
        signature=signature
    )

    return result
