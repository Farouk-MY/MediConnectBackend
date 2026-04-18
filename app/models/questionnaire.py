"""
AI Pre-Diagnosis Smart Questionnaire — Database Models

Two tables:
- questionnaire_sessions: One per appointment, stores the entire questionnaire flow state
- questionnaire_answers: Individual Q&A pairs within a session
"""

from sqlalchemy import (
    Column, String, DateTime, Integer, Float,
    ForeignKey, Text, Enum as SQLEnum, JSON, Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


# ──────────────────────────────────────────────
#  Enums
# ──────────────────────────────────────────────

class QuestionnaireStatus(str, enum.Enum):
    """Questionnaire session lifecycle."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    SKIPPED = "skipped"
    INACTIVE_TIMEOUT = "inactive_timeout"
    URGENT_ESCALATION = "urgent_escalation"


class UrgencyLevel(str, enum.Enum):
    """Patient urgency classification."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QuestionType(str, enum.Enum):
    """Types of question UI controls."""
    RADIO = "radio"
    CHECKBOX = "checkbox"
    TEXT = "text"
    RADIO_WITH_OTHER = "radio_with_other"
    CHECKBOX_WITH_OTHER = "checkbox_with_other"


class DetectedLanguage(str, enum.Enum):
    """Supported languages."""
    ENGLISH = "en"
    FRENCH = "fr"
    ARABIC = "ar"
    TUNISIAN_ARABIC = "ar_tn"


# ──────────────────────────────────────────────
#  QuestionnaireSession
# ──────────────────────────────────────────────

class QuestionnaireSession(Base):
    """
    One questionnaire session per appointment.
    Tracks the entire AI-guided intake flow from start to completion.
    """
    __tablename__ = "questionnaire_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Relationships ──
    appointment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One session per appointment
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Language & Flow ──
    detected_language = Column(String(10), default="en")
    status = Column(
        SQLEnum(QuestionnaireStatus),
        default=QuestionnaireStatus.IN_PROGRESS,
        index=True,
    )
    current_question_index = Column(Integer, default=0)
    max_questions = Column(Integer, default=8)

    # ── Patient Input ──
    initial_symptoms = Column(Text, nullable=False)

    # ── Pre-Generated Questions (batch mode — all questions in 1 LLM call) ──
    pre_generated_questions = Column(JSON, nullable=True, default=None)
    # Structure: [{"question_text": "...", "question_type": "radio_with_other",
    #              "options": [...], "clinical_area": "onset"}, ...]

    # ── Urgency Assessment ──
    urgency_level = Column(
        SQLEnum(UrgencyLevel),
        default=UrgencyLevel.NONE,
    )
    urgency_note = Column(Text, nullable=True)

    # ── Doctor Summary (generated at completion) ──
    doctor_summary = Column(JSON, nullable=True)
    # Structure:
    # {
    #   "main_complaint": str,
    #   "duration": str,
    #   "location": str,
    #   "intensity": str,
    #   "associated_symptoms": [str],
    #   "triggers": str,
    #   "relieving_factors": str,
    #   "relevant_history": str,
    #   "medications": str,
    #   "urgency_level": str,
    #   "missing_information": [str],
    #   "recommended_specialty": str,
    #   "narrative_summary": str,
    # }

    # ── Inactivity Tracking ──
    last_activity_at = Column(DateTime, default=datetime.utcnow)
    reminder_count = Column(Integer, default=0)

    # ── Skip Reason ──
    skip_reason = Column(Text, nullable=True)

    # ── Timestamps ──
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # ── Relationships ──
    answers = relationship(
        "QuestionnaireAnswer",
        back_populates="session",
        order_by="QuestionnaireAnswer.question_index",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        return (
            f"<QuestionnaireSession {self.id} "
            f"appointment={self.appointment_id} "
            f"status={self.status.value}>"
        )


# ──────────────────────────────────────────────
#  QuestionnaireAnswer
# ──────────────────────────────────────────────

class QuestionnaireAnswer(Base):
    """
    Individual question-answer pair within a questionnaire session.
    Stores both the AI-generated question and the patient's response.
    """
    __tablename__ = "questionnaire_answers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Session Reference ──
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_index = Column(Integer, nullable=False)

    # ── Question (AI-generated) ──
    question_text = Column(Text, nullable=False)
    question_type = Column(String(30), default="radio")  # radio, checkbox, text, radio_with_other
    question_options = Column(JSON, default=list)
    # Structure: [{"label": "...", "value": "...", "is_other": false}, ...]

    # ── Patient Answer ──
    answer_text = Column(Text, nullable=True)  # Normalized text of the answer
    answer_selections = Column(JSON, default=list)  # Selected option values

    # ── Metadata ──
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── Relationship ──
    session = relationship("QuestionnaireSession", back_populates="answers")

    def __repr__(self):
        return (
            f"<QuestionnaireAnswer Q{self.question_index} "
            f"session={self.session_id}>"
        )
