from pydantic import BaseModel, EmailStr, Field, validator
from app.models.user import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole

    # Role-specific fields
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)

    # Doctor-specific (optional)
    specialty: str | None = None
    license_number: str | None = None

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if len(v) > 128:
            raise ValueError('Password cannot be longer than 128 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v

    @validator('specialty')
    def validate_doctor_fields(cls, v, values):
        if values.get('role') == UserRole.DOCTOR and not v:
            raise ValueError('Specialty is required for doctors')
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    role: UserRole

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════
#  OTP Verification Schemas
# ═══════════════════════════════════════════

class RegisterResponse(BaseModel):
    """Response after registration — triggers OTP verification flow."""
    message: str
    email: str
    requires_verification: bool = True


class OTPVerifyRequest(BaseModel):
    """Request to verify an OTP code."""
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)


class OTPResendRequest(BaseModel):
    """Request to resend an OTP code."""
    email: EmailStr


class OTPVerifyResponse(BaseModel):
    """Response after successful OTP verification — includes auth tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    message: str = "Email verified successfully"

# ═══════════════════════════════════════════
#  Password Reset Schemas
# ═══════════════════════════════════════════

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)

class VerifyResetOTPResponse(BaseModel):
    reset_token: str
    message: str = "OTP verified. Proceed to reset password."

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if len(v) > 128:
            raise ValueError('Password cannot be longer than 128 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v