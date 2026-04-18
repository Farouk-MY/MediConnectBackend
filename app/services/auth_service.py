from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from datetime import datetime
from app.models.user import User, UserRole
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.schemas.auth import RegisterRequest, LoginRequest
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token
)
from app.services.email_service import email_service
import logging

logger = logging.getLogger(__name__)


class AuthService:

    @staticmethod
    async def _generate_and_send_otp(db: AsyncSession, user: User) -> None:
        """Generate OTP, save to user, and send email."""
        otp_code = email_service.generate_otp()

        # Store hashed OTP and expiry
        user.otp_code = get_password_hash(otp_code)
        user.otp_expires_at = email_service.get_otp_expiry()
        await db.commit()

        # Send email (non-blocking failure — log but don't crash)
        sent = await email_service.send_otp_email(user.email, otp_code)
        if not sent:
            logger.warning(f"⚠️ OTP email failed for {user.email}, but OTP is stored in DB")

    @staticmethod
    async def register_user(
            db: AsyncSession,
            data: RegisterRequest
    ) -> dict:
        """Register a new user and send OTP for verification."""

        # Check if email already exists
        result = await db.execute(
            select(User).where(User.email == data.email)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        # Create user (unverified)
        user = User(
            email=data.email,
            password_hash=get_password_hash(data.password),
            role=data.role,
            is_verified=False
        )
        db.add(user)
        await db.flush()

        # Create role-specific profile
        if data.role == UserRole.PATIENT:
            patient = Patient(
                user_id=user.id,
                first_name=data.first_name,
                last_name=data.last_name
            )
            db.add(patient)

        elif data.role == UserRole.DOCTOR:
            doctor = Doctor(
                user_id=user.id,
                first_name=data.first_name,
                last_name=data.last_name,
                specialty=data.specialty,
                license_number=data.license_number
            )
            db.add(doctor)

        await db.commit()
        await db.refresh(user)

        # Generate and send OTP
        await AuthService._generate_and_send_otp(db, user)

        return {
            "message": "Registration successful. Please check your email for the verification code.",
            "email": user.email,
            "requires_verification": True,
        }

    @staticmethod
    async def login_user(
            db: AsyncSession,
            data: LoginRequest
    ) -> dict:
        """Authenticate user. If unverified, send OTP and return 403."""

        # Find user by email
        result = await db.execute(
            select(User).where(User.email == data.email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )

        # Verify password
        if not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )

        # Check if email is verified
        if not user.is_verified:
            # Send new OTP for verification
            await AuthService._generate_and_send_otp(db, user)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Account not verified. A new verification code has been sent to your email.",
                    "requires_verification": True,
                    "email": user.email,
                }
            )

        # All good — generate tokens
        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        return {
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token
        }

    @staticmethod
    async def verify_otp(
            db: AsyncSession,
            email: str,
            otp_code: str
    ) -> dict:
        """Verify OTP code, mark user as verified, and return tokens."""

        # Find user
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if already verified
        if user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified"
            )

        # Check OTP exists
        if not user.otp_code or not user.otp_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No verification code found. Please request a new one."
            )

        # Check OTP expiry
        if datetime.utcnow() > user.otp_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code has expired. Please request a new one."
            )

        # Verify OTP (compare with hash)
        if not verify_password(otp_code, user.otp_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code"
            )

        # Mark as verified and clear OTP
        user.is_verified = True
        user.otp_code = None
        user.otp_expires_at = None
        await db.commit()

        logger.info(f"✅ Email verified for {email}")

        # Generate tokens
        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "message": "Email verified successfully"
        }

    @staticmethod
    async def resend_otp(
            db: AsyncSession,
            email: str
    ) -> dict:
        """Resend OTP to user's email."""

        # Find user
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if already verified
        if user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified"
            )

        # Generate and send new OTP (invalidates old one)
        await AuthService._generate_and_send_otp(db, user)

        return {
            "message": "A new verification code has been sent to your email."
        }

    # ═══════════════════════════════════════════
    #  Password Reset Logic
    # ═══════════════════════════════════════════

    @staticmethod
    async def forgot_password(db: AsyncSession, email: str) -> dict:
        """Initiate password reset flow by sending OTP."""
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            # Prevent email enumeration by returning success blindly
            return {"message": "If the email is registered, a password reset code has been sent."}

        # Generate and save OTP
        otp_code = email_service.generate_otp()
        user.otp_code = get_password_hash(otp_code)
        user.otp_expires_at = email_service.get_otp_expiry()
        await db.commit()

        # Send email
        await email_service.send_password_reset_email(to_email=user.email, otp_code=otp_code)

        return {"message": "If the email is registered, a password reset code has been sent."}

    @staticmethod
    async def verify_reset_otp(db: AsyncSession, email: str, otp_code: str) -> dict:
        """Verify OTP for password reset and issue a temporary reset_token."""
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Check OTP exists and is valid
        if not user.otp_code or not user.otp_expires_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No verification code found. Please request a new one.")
        if datetime.utcnow() > user.otp_expires_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code has expired. Please request a new one.")
        if not verify_password(otp_code, user.otp_code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

        # Clear OTP so it can't be reused
        user.otp_code = None
        user.otp_expires_at = None
        await db.commit()

        # Generate short-lived reset token
        reset_token = create_reset_token(subject=str(user.id))

        return {"reset_token": reset_token, "message": "OTP verified. Proceed to reset password."}

    @staticmethod
    async def reset_password(db: AsyncSession, reset_token: str, new_password: str) -> dict:
        """Apply new password using valid reset_token."""
        payload = decode_token(reset_token)
        if not payload or payload.get("purpose") != "password_reset":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired reset token")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid reset token structure")

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update password
        user.password_hash = get_password_hash(new_password)
        await db.commit()

        logger.info(f"✅ Password reset successfully for {user.email}")
        return {"message": "Password has been reset successfully."}