import aiosmtplib
import random
import string
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending OTP verification emails via Gmail SMTP."""

    @staticmethod
    def generate_otp() -> str:
        """Generate a secure numeric OTP code."""
        return ''.join(random.choices(string.digits, k=settings.OTP_LENGTH))

    @staticmethod
    def get_otp_expiry() -> datetime:
        """Get the expiry datetime for an OTP."""
        return datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    @staticmethod
    def _build_otp_html(otp_code: str) -> str:
        """Build a professional HTML email template for OTP verification."""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f4f8;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f0f4f8; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 520px; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
                            
                            <!-- Header with gradient -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #2563EB 0%, #3B82F6 50%, #14B8A6 100%); padding: 40px 32px; text-align: center;">
                                    <!-- Medical Cross Logo -->
                                    <div style="display: inline-block; width: 64px; height: 64px; background: rgba(255,255,255,0.95); border-radius: 50%; margin-bottom: 16px; line-height: 64px; text-align: center;">
                                        <span style="color: #2563EB; font-size: 32px; font-weight: bold;">+</span>
                                    </div>
                                    <h1 style="color: #ffffff; font-size: 28px; margin: 0 0 8px 0; font-weight: 700; letter-spacing: 1px;">MediConnect</h1>
                                    <p style="color: rgba(255,255,255,0.9); font-size: 14px; margin: 0; letter-spacing: 0.5px;">Professional Healthcare Platform</p>
                                </td>
                            </tr>

                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px 32px 32px;">
                                    <h2 style="color: #1e293b; font-size: 22px; margin: 0 0 8px 0; text-align: center; font-weight: 600;">Verify Your Email</h2>
                                    <p style="color: #64748b; font-size: 15px; line-height: 1.6; text-align: center; margin: 0 0 32px 0;">
                                        Use the verification code below to complete your account setup. This code is valid for <strong>{settings.OTP_EXPIRE_MINUTES} minutes</strong>.
                                    </p>

                                    <!-- OTP Code Box -->
                                    <div style="text-align: center; margin-bottom: 32px;">
                                        <div style="display: inline-block; background: linear-gradient(135deg, #eff6ff 0%, #f0fdfa 100%); border: 2px solid #bfdbfe; border-radius: 12px; padding: 20px 40px;">
                                            <span style="font-family: 'Courier New', monospace; font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #1d4ed8;">{otp_code}</span>
                                        </div>
                                    </div>

                                    <!-- Security Notice -->
                                    <div style="background: #fefce8; border: 1px solid #fde68a; border-radius: 8px; padding: 14px 16px; margin-bottom: 24px;">
                                        <p style="color: #854d0e; font-size: 13px; margin: 0; line-height: 1.5;">
                                            🔒 <strong>Security Notice:</strong> Never share this code with anyone. MediConnect staff will never ask for your verification code.
                                        </p>
                                    </div>

                                    <p style="color: #94a3b8; font-size: 13px; text-align: center; margin: 0; line-height: 1.5;">
                                        If you didn't create a MediConnect account, you can safely ignore this email.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background: #f8fafc; padding: 24px 32px; border-top: 1px solid #e2e8f0; text-align: center;">
                                    <p style="color: #94a3b8; font-size: 12px; margin: 0 0 4px 0;">
                                        &copy; {datetime.utcnow().year} MediConnect — HIPAA Compliant & Secure
                                    </p>
                                    <p style="color: #cbd5e1; font-size: 11px; margin: 0;">
                                        This is an automated message. Please do not reply.
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    @staticmethod
    async def send_otp_email(to_email: str, otp_code: str) -> bool:
        """
        Send an OTP verification email.
        Returns True if sent successfully, False otherwise.
        """
        try:
            # Build the email
            message = MIMEMultipart("alternative")
            message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
            message["To"] = to_email
            message["Subject"] = f"🔐 MediConnect — Your Verification Code: {otp_code}"

            # Plain text fallback
            plain_text = (
                f"MediConnect Email Verification\n\n"
                f"Your verification code is: {otp_code}\n\n"
                f"This code expires in {settings.OTP_EXPIRE_MINUTES} minutes.\n"
                f"If you didn't create a MediConnect account, ignore this email.\n"
            )

            # Attach both plain and HTML versions
            message.attach(MIMEText(plain_text, "plain"))
            message.attach(MIMEText(EmailService._build_otp_html(otp_code), "html"))

            # Send via Gmail SMTP
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                start_tls=True,
            )

            logger.info(f"✅ OTP email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send OTP email to {to_email}: {e}")
            return False

    @staticmethod
    def _build_reset_html(otp_code: str) -> str:
        """Build a professional HTML email template for password reset."""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f4f8;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f0f4f8; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 520px; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
                            
                            <!-- Header with gradient -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #1e293b 0%, #334155 50%, #475569 100%); padding: 40px 32px; text-align: center;">
                                    <div style="display: inline-block; width: 64px; height: 64px; background: rgba(255,255,255,0.1); border-radius: 50%; margin-bottom: 16px; line-height: 64px; text-align: center;">
                                        <span style="color: #ffffff; font-size: 28px;">🔐</span>
                                    </div>
                                    <h1 style="color: #ffffff; font-size: 24px; margin: 0 0 8px 0; font-weight: 700; letter-spacing: 1px;">Password Reset</h1>
                                </td>
                            </tr>

                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px 32px 32px;">
                                    <h2 style="color: #1e293b; font-size: 22px; margin: 0 0 8px 0; text-align: center; font-weight: 600;">Reset Your Password</h2>
                                    <p style="color: #64748b; font-size: 15px; line-height: 1.6; text-align: center; margin: 0 0 32px 0;">
                                        We received a request to reset the password for your MediConnect account. Use the code below to securely reset your password. This code expires in <strong>{settings.OTP_EXPIRE_MINUTES} minutes</strong>.
                                    </p>

                                    <!-- OTP Code Box -->
                                    <div style="text-align: center; margin-bottom: 32px;">
                                        <div style="display: inline-block; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border: 2px solid #cbd5e1; border-radius: 12px; padding: 20px 40px;">
                                            <span style="font-family: 'Courier New', monospace; font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #334155;">{otp_code}</span>
                                        </div>
                                    </div>

                                    <!-- Security Notice -->
                                    <div style="background: #fefce8; border: 1px solid #fde68a; border-radius: 8px; padding: 14px 16px; margin-bottom: 24px;">
                                        <p style="color: #854d0e; font-size: 13px; margin: 0; line-height: 1.5;">
                                            🚨 <strong>Security Alert:</strong> If you did not request a password reset, someone may be trying to access your account. Do not share this code.
                                        </p>
                                    </div>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background: #f8fafc; padding: 24px 32px; border-top: 1px solid #e2e8f0; text-align: center;">
                                    <p style="color: #94a3b8; font-size: 12px; margin: 0 0 4px 0;">
                                        &copy; {datetime.utcnow().year} MediConnect — HIPAA Compliant & Secure
                                    </p>
                                    <p style="color: #cbd5e1; font-size: 11px; margin: 0;">
                                        This is an automated message. Please do not reply.
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    @staticmethod
    async def send_password_reset_email(to_email: str, otp_code: str) -> bool:
        """
        Send a password reset OTP email.
        Returns True if sent successfully, False otherwise.
        """
        try:
            # Build the email
            message = MIMEMultipart("alternative")
            message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
            message["To"] = to_email
            message["Subject"] = f"🔐 Password Reset Code: {otp_code} — MediConnect"

            # Plain text fallback
            plain_text = (
                f"MediConnect Password Reset\n\n"
                f"We received a request to reset your password.\n"
                f"Your password reset code is: {otp_code}\n\n"
                f"This code expires in {settings.OTP_EXPIRE_MINUTES} minutes.\n"
                f"If you did not request this, please ignore this email and your password will remain unchanged.\n"
            )

            # Attach both plain and HTML versions
            message.attach(MIMEText(plain_text, "plain"))
            message.attach(MIMEText(EmailService._build_reset_html(otp_code), "html"))

            # Send via Gmail SMTP
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                start_tls=True,
            )

            logger.info(f"✅ Password reset email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send password reset email to {to_email}: {e}")
            return False


# Singleton instance
email_service = EmailService()
