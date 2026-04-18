"""
AI Pre-Diagnosis Smart Questionnaire — Pydantic Schemas

Request/response models for the questionnaire API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Any, Dict
from datetime import datetime
from uuid import UUID


# ═══════════════════════════════════════════════
#  Request Schemas
# ═══════════════════════════════════════════════

class QuestionnaireStartRequest(BaseModel):
    """Start a new questionnaire session."""
    appointment_id: UUID
    initial_symptoms: str = Field(
        ...,
        min_length=2,
        max_length=2000,
        description="Patient's free-text symptom description",
        examples=["I have a headache since yesterday", "عندي وجع في راسي", "J'ai mal à la tête"],
    )


class AnswerSubmitRequest(BaseModel):
    """Submit an answer to the current question."""
    question_text: Optional[str] = Field(
        None,
        max_length=1000,
        description="The question text that was displayed to the patient",
    )
    answer_text: Optional[str] = Field(
        None,
        max_length=1000,
        description="Free-text answer (for text questions or 'Other' option)",
    )
    answer_selections: Optional[List[str]] = Field(
        None,
        description="Selected option values (for radio/checkbox questions)",
    )
    other_text: Optional[str] = Field(
        None,
        max_length=500,
        description="Text entered in 'Other' option field",
    )


class SkipQuestionnaireRequest(BaseModel):
    """Skip the entire questionnaire."""
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional reason for skipping",
    )


class InactivityUpdateRequest(BaseModel):
    """Report an inactivity event."""
    event_type: Literal["reminder", "timeout"] = Field(
        ...,
        description="'reminder' for first/second reminder, 'timeout' for auto-save",
    )


# ═══════════════════════════════════════════════
#  Response Schemas
# ═══════════════════════════════════════════════

class QuestionOption(BaseModel):
    """A single option within a question."""
    label: str
    value: str
    is_other: bool = False


class NextQuestionResponse(BaseModel):
    """Response containing the next AI-generated question."""
    session_id: UUID
    question_index: int
    question_text: str
    question_type: str = Field(
        ...,
        description="UI control type: radio, checkbox, text, radio_with_other, checkbox_with_other",
    )
    options: List[QuestionOption] = []
    progress: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Progress from 0.0 to 1.0",
    )
    is_complete: bool = Field(
        False,
        description="True when questionnaire is done",
    )
    urgency_flag: Optional[str] = Field(
        None,
        description="Urgency level if flagged: none, low, medium, high, critical",
    )
    urgency_message: Optional[str] = Field(
        None,
        description="Gentle urgency message in patient's language",
    )
    disclaimer: str = ""
    max_questions: Optional[int] = Field(
        None,
        description="Total number of questions in this session (set by AI)",
    )


class QuestionnaireStartResponse(BaseModel):
    """Response after starting a new questionnaire session."""
    session_id: UUID
    detected_language: str
    first_question: NextQuestionResponse
    disclaimer: str
    ui_strings: Dict[str, str] = {}
    max_questions: int = Field(
        8,
        description="Total questions determined by AI for this session",
    )


class CompletionResponse(BaseModel):
    """Response when the questionnaire is completed or skipped."""
    session_id: UUID
    appointment_id: UUID
    status: str
    message: str
    is_teleconsultation: bool = False
    consultation_room_url: Optional[str] = None
    urgency_level: str = "none"
    urgency_message: Optional[str] = None


class DoctorSummaryResponse(BaseModel):
    """Structured pre-consultation summary for the doctor."""
    session_id: UUID
    appointment_id: UUID
    patient_name: Optional[str] = None
    status: str
    language: str
    urgency_level: str
    summary: Dict[str, Any] = {}
    # summary keys:
    #   main_complaint, duration, location, intensity,
    #   associated_symptoms, triggers, relieving_factors,
    #   relevant_history, medications, urgency_level,
    #   missing_information, recommended_specialty,
    #   narrative_summary, conversation_log
    conversation_log: List[Dict[str, str]] = []
    created_at: datetime
    completed_at: Optional[datetime] = None


class AnswerRecord(BaseModel):
    """A single Q&A record for session retrieval."""
    question_index: int
    question_text: str
    question_type: str
    question_options: List[QuestionOption] = []
    answer_text: Optional[str] = None
    answer_selections: List[str] = []
    created_at: datetime


class QuestionnaireSessionResponse(BaseModel):
    """Full session state for resuming or inspection."""
    id: UUID
    appointment_id: UUID
    patient_id: UUID
    doctor_id: UUID
    status: str
    detected_language: str
    initial_symptoms: str
    current_question_index: int
    max_questions: int
    urgency_level: str
    has_summary: bool = False
    created_at: datetime
    completed_at: Optional[datetime] = None
    answers: List[AnswerRecord] = []
    ui_strings: Dict[str, str] = {}


class InactivityResponse(BaseModel):
    """Response to an inactivity event."""
    session_id: UUID
    event_type: str
    message: str
    status: str
    auto_saved: bool = False
