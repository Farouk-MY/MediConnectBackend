from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    RegisterResponse,
    OTPVerifyRequest,
    OTPResendRequest,
    OTPVerifyResponse,
    ForgotPasswordRequest,
    VerifyResetOTPRequest,
    VerifyResetOTPResponse,
    ResetPasswordRequest
)
from app.services.auth_service import AuthService
from app.api.deps import get_current_active_user
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
        data: RegisterRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Register a new user (patient or doctor).

    After registration, an OTP verification code will be sent to the 
    provided email. The user must verify their email before they can log in.

    - **email**: Valid email address
    - **password**: Minimum 8 characters with uppercase, lowercase, and digit
    - **role**: Either 'patient' or 'doctor'
    - **first_name**: User's first name
    - **last_name**: User's last name
    - **specialty**: Required for doctors
    - **license_number**: Required for doctors
    """
    result = await AuthService.register_user(db, data)

    return RegisterResponse(
        message=result["message"],
        email=result["email"],
        requires_verification=result["requires_verification"]
    )


@router.post("/login", response_model=TokenResponse)
async def login(
        data: LoginRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password.

    If the account is not verified, returns 403 with a new OTP sent to email.
    Returns access token and refresh token for authenticated requests.
    """
    result = await AuthService.login_user(db, data)

    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"]
    )


@router.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(
        data: OTPVerifyRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Verify email with OTP code.

    After successful verification, returns access and refresh tokens.
    The user can then proceed to their dashboard.
    """
    result = await AuthService.verify_otp(db, data.email, data.otp_code)

    return OTPVerifyResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        message=result["message"]
    )


@router.post("/resend-otp")
async def resend_otp(
        data: OTPResendRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Resend OTP verification code to user's email.

    Generates a new OTP (invalidates the previous one) and sends it.
    Frontend should enforce a 30-second cooldown between resend requests.
    """
    result = await AuthService.resend_otp(db, data.email)
    return result


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
        current_user: User = Depends(get_current_active_user)
):
    """
    Get current authenticated user information.

    Requires valid JWT token in Authorization header.
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role
    )


@router.post("/logout")
async def logout(
        current_user: User = Depends(get_current_active_user)
):
    """
    Logout current user.

    Client should delete stored tokens.
    """
    return {"message": "Successfully logged out"}

# ═══════════════════════════════════════════
#  Password Reset Routes
# ═══════════════════════════════════════════

@router.post("/forgot-password")
async def forgot_password(
        data: ForgotPasswordRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset email.
    Sends a 6-digit OTP to the registered email address.
    """
    result = await AuthService.forgot_password(db, data.email)
    return result

@router.post("/verify-reset-otp", response_model=VerifyResetOTPResponse)
async def verify_reset_otp(
        data: VerifyResetOTPRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Verify the OTP code sent for password reset.
    Returns a short-lived reset token if valid.
    """
    result = await AuthService.verify_reset_otp(db, data.email, data.otp_code)
    return VerifyResetOTPResponse(
        reset_token=result["reset_token"],
        message=result["message"]
    )

@router.post("/reset-password")
async def reset_password(
        data: ResetPasswordRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Reset the user's password using the token obtained from OTP verification.
    """
    result = await AuthService.reset_password(db, data.reset_token, data.new_password)
    return result