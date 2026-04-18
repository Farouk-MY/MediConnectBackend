"""
Payment Service

Handles Stripe payment integration for appointment consultations.
Creates PaymentIntents, processes webhooks, and manages payment state.
"""

import stripe
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus, ConsultationType


# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


class PaymentService:
    """Service for managing Stripe payments."""

    @staticmethod
    async def create_payment_intent(
        db: AsyncSession,
        appointment_id: UUID,
        patient_user_id: UUID
    ) -> dict:
        """
        Create a Stripe PaymentIntent for an appointment.
        
        Returns the client_secret for the mobile app to complete payment.
        """
        from app.models.patient import Patient

        # Get appointment
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )

        # Verify patient owns this appointment
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == patient_user_id)
        )
        patient = patient_result.scalar_one_or_none()

        if not patient or appointment.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized"
            )

        # Must be confirmed by doctor first
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Appointment must be confirmed by doctor before payment"
            )

        # Already paid
        if appointment.is_paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Appointment is already paid"
            )

        # Must be online consultation
        if appointment.consultation_type != ConsultationType.ONLINE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment is only required for online consultations"
            )

        # Convert fee to cents (Stripe uses smallest currency unit)
        amount_cents = int(appointment.consultation_fee * 100)

        # Map unsupported currencies to EUR (Stripe doesn't support TND etc.)
        currency = appointment.currency.lower()
        unsupported_currencies = {"tnd", "lyd", "iqd"}
        if currency in unsupported_currencies:
            currency = "eur"

        try:
            # Create Stripe PaymentIntent
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                metadata={
                    "appointment_id": str(appointment.id),
                    "patient_id": str(patient.id),
                    "doctor_id": str(appointment.doctor_id),
                    "confirmation_code": appointment.confirmation_code or "",
                },
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            )

            # Store payment intent ID on appointment
            appointment.payment_method = f"stripe:{intent.id}"
            await db.commit()

            return {
                "client_secret": intent.client_secret,
                "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
                "amount": appointment.consultation_fee,
                "currency": appointment.currency,
                "payment_intent_id": intent.id,
            }

        except Exception as e:
            print(f"[PAYMENT ERROR] {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Payment service error: {str(e)}"
            )

    @staticmethod
    async def handle_webhook(
        db: AsyncSession,
        payload: bytes,
        signature: str
    ) -> dict:
        """
        Handle Stripe webhook events.
        
        Processes payment_intent.succeeded to mark appointments as paid.
        """
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload"
            )
        except stripe.SignatureVerificationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )

        if event["type"] == "payment_intent.succeeded":
            intent = event["data"]["object"]
            appointment_id = intent["metadata"].get("appointment_id")

            if appointment_id:
                result = await db.execute(
                    select(Appointment).where(
                        Appointment.id == UUID(appointment_id)
                    )
                )
                appointment = result.scalar_one_or_none()

                if appointment:
                    appointment.is_paid = True
                    appointment.paid_at = datetime.utcnow()
                    appointment.payment_method = f"stripe:{intent['id']}"
                    await db.commit()

                    return {"status": "paid", "appointment_id": appointment_id}

        return {"status": "ignored", "event_type": event["type"]}

    @staticmethod
    async def confirm_payment(
        db: AsyncSession,
        appointment_id: UUID,
        patient_user_id: UUID,
        payment_intent_id: str
    ) -> Appointment:
        """
        Confirm payment was successful (called from mobile after PaymentSheet).
        
        Verifies with Stripe that the payment actually succeeded,
        then marks the appointment as paid.
        """
        from app.models.patient import Patient

        # Get appointment
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )

        # Verify patient
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == patient_user_id)
        )
        patient = patient_result.scalar_one_or_none()

        if not patient or appointment.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized"
            )

        if appointment.is_paid:
            return appointment

        # Verify with Stripe
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)

            # If not yet succeeded, try to confirm server-side (test mode)
            if intent.status in ("requires_payment_method", "requires_confirmation"):
                # In test mode, confirm with test card
                if settings.STRIPE_SECRET_KEY.startswith("sk_test_"):
                    # Attach test payment method and confirm
                    intent = stripe.PaymentIntent.confirm(
                        payment_intent_id,
                        payment_method="pm_card_visa",
                        return_url="https://mediconnect.app/payment/complete",
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Payment not completed. Status: {intent.status}"
                    )

            if intent.status == "succeeded":
                appointment.is_paid = True
                appointment.paid_at = datetime.utcnow()
                appointment.payment_method = f"stripe:{payment_intent_id}"
                await db.commit()
                await db.refresh(appointment)
                return appointment
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payment not completed. Status: {intent.status}"
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"[PAYMENT CONFIRM ERROR] {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not verify payment: {str(e)}"
            )
