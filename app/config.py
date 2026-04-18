from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "MediConnect"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Video Consultation
    JITSI_DOMAIN: str = "meet.jit.si"

    # ═══════════════════════════════════════════
    #  AI Provider Configuration
    # ═══════════════════════════════════════════

    # Provider priority: comma-separated list of providers to try in order
    # Options: ollama, groq, gemini
    AI_PROVIDER_PRIORITY: str = "groq,gemini,ollama"

    # Ollama (Local — primary for development)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # Groq Cloud (Fallback 1 — fast cloud inference)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # Google Gemini (Fallback 2 — smart cloud inference)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash-lite"

    # AI Tuning
    AI_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_RETRIES: int = 2

    # ═══════════════════════════════════════════

    # Questionnaire Config
    QUESTIONNAIRE_MAX_QUESTIONS: int = 8
    QUESTIONNAIRE_INACTIVITY_REMINDER_SECONDS: int = 120   # 2 minutes
    QUESTIONNAIRE_INACTIVITY_TIMEOUT_SECONDS: int = 240    # 4 minutes

    # SMTP Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "MediConnect"

    # OTP Settings
    OTP_EXPIRE_MINUTES: int = 5
    OTP_LENGTH: int = 6
    OTP_RESEND_SECONDS: int = 30

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:8081,exp://localhost:8081,http://localhost:19000,http://localhost:19001,http://192.168.100.22:8081"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"  # ← This allows extra fields in .env
    )

    @property
    def cors_origins(self) -> List[str]:
        """Convert ALLOWED_ORIGINS string to list."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def provider_chain(self) -> List[str]:
        """Parse AI_PROVIDER_PRIORITY into ordered list."""
        return [p.strip().lower() for p in self.AI_PROVIDER_PRIORITY.split(",") if p.strip()]


settings = Settings()