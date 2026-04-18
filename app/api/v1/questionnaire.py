"""
Questionnaire API Routes — Pre-Diagnosis Smart Questionnaire

7 endpoints for managing the AI-powered pre-consultation questionnaire.
All endpoints require JWT authentication.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.schemas.questionnaire import (
    QuestionnaireStartRequest,
    QuestionnaireStartResponse,
    AnswerSubmitRequest,
    NextQuestionResponse,
    SkipQuestionnaireRequest,
    InactivityUpdateRequest,
    QuestionnaireSessionResponse,
    DoctorSummaryResponse,
    CompletionResponse,
    InactivityResponse,
)
from app.services.questionnaire_service import questionnaire_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questionnaire", tags=["Questionnaire"])


# ═══════════════════════════════════════════
#  1. POST /questionnaire/start
# ═══════════════════════════════════════════

@router.post(
    "/start",
    response_model=QuestionnaireStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new questionnaire session",
    description="Starts the AI-powered pre-consultation questionnaire. "
    "Detects language, retrieves medical context, and generates the first question.",
)
async def start_questionnaire(
    request: QuestionnaireStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a new questionnaire session for an appointment."""
    try:
        # Resolve patient_id from the current user via DB query
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == current_user.id)
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only patients can start a questionnaire",
            )
        patient_id = patient.id

        result = await questionnaire_service.start_session(
            db=db,
            appointment_id=request.appointment_id,
            initial_symptoms=request.initial_symptoms,
            patient_id=patient_id,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting questionnaire: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start questionnaire. Please try again.",
        )


# ═══════════════════════════════════════════
#  2. POST /questionnaire/{session_id}/answer
# ═══════════════════════════════════════════

@router.post(
    "/{session_id}/answer",
    summary="Submit an answer to the current question",
    description="Submits the patient's answer, checks for urgency, "
    "and returns the next adaptive question or completion.",
)
async def submit_answer(
    session_id: UUID,
    request: AnswerSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an answer and get the next question or completion status."""
    try:
        result = await questionnaire_service.submit_answer(
            db=db,
            session_id=session_id,
            question_text=request.question_text,
            answer_text=request.answer_text,
            answer_selections=request.answer_selections,
            other_text=request.other_text,
        )

        # Return the appropriate response type
        if isinstance(result, CompletionResponse):
            return result.model_dump()
        return result.model_dump()

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting answer: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process answer. Please try again.",
        )


# ═══════════════════════════════════════════
#  3. POST /questionnaire/{session_id}/skip
# ═══════════════════════════════════════════

@router.post(
    "/{session_id}/skip",
    response_model=CompletionResponse,
    summary="Skip the entire questionnaire",
    description="Skips the questionnaire. A partial summary is generated "
    "from any answers that were already provided.",
)
async def skip_questionnaire(
    session_id: UUID,
    request: SkipQuestionnaireRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Skip the questionnaire with an optional reason."""
    try:
        result = await questionnaire_service.skip_questionnaire(
            db=db,
            session_id=session_id,
            reason=request.reason,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error skipping questionnaire: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip questionnaire.",
        )


# ═══════════════════════════════════════════
#  4. POST /questionnaire/{session_id}/inactivity
# ═══════════════════════════════════════════

@router.post(
    "/{session_id}/inactivity",
    response_model=InactivityResponse,
    summary="Report an inactivity event",
    description="Called by the client when the patient is inactive. "
    "'reminder' shows a message, 'timeout' auto-saves.",
)
async def report_inactivity(
    session_id: UUID,
    request: InactivityUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Handle inactivity reminder or timeout."""
    try:
        result = await questionnaire_service.handle_inactivity(
            db=db,
            session_id=session_id,
            event_type=request.event_type,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error handling inactivity: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process inactivity event.",
        )


# ═══════════════════════════════════════════
#  5. GET /questionnaire/appointment/{appointment_id}
#     (MUST come before /{session_id} to avoid path collision)
# ═══════════════════════════════════════════

@router.get(
    "/appointment/{appointment_id}",
    response_model=QuestionnaireSessionResponse,
    summary="Get session by appointment ID",
    description="Returns the questionnaire session associated with an appointment.",
)
async def get_by_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the questionnaire session for a specific appointment."""
    try:
        result = await questionnaire_service.get_session_by_appointment(
            db=db, appointment_id=appointment_id
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No questionnaire found for this appointment.",
            )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session by appointment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve questionnaire.",
        )


# ═══════════════════════════════════════════
#  6. GET /questionnaire/{session_id}
# ═══════════════════════════════════════════

@router.get(
    "/{session_id}",
    response_model=QuestionnaireSessionResponse,
    summary="Get session state",
    description="Returns the full session state for resuming or inspection.",
)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the questionnaire session state."""
    try:
        result = await questionnaire_service.get_session(db=db, session_id=session_id)
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session.",
        )


# ═══════════════════════════════════════════
#  7. GET /questionnaire/{session_id}/summary
# ═══════════════════════════════════════════

@router.get(
    "/{session_id}/summary",
    response_model=DoctorSummaryResponse,
    summary="Get doctor's pre-consultation summary",
    description="Returns the structured summary for the doctor to review "
    "before the consultation.",
)
async def get_summary(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the doctor-facing summary for a completed questionnaire."""
    try:
        result = await questionnaire_service.get_doctor_summary(
            db=db, session_id=session_id
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No summary available for this session.",
            )
        return result

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve summary.",
        )


# ═══════════════════════════════════════════
#  8. GET /questionnaire/health — AI Health Check
# ═══════════════════════════════════════════

@router.get("/health")
async def ai_health_check():
    """
    Check if the AI system is healthy and ready.
    Returns Ollama status, model availability, and RAG knowledge base state.
    No authentication required — useful for monitoring.
    """
    from app.services.ai_service import ai_service
    from app.services.rag_service import rag_service

    # Run AI health check (multi-provider)
    ai_health = await ai_service.health_check()

    # RAG status
    rag_status = {
        "ready": rag_service.is_ready,
        "chunks_loaded": rag_service.chunk_count,
    }

    # Overall status
    overall = "healthy"
    ai_status = ai_health.get("status", "unknown")
    if ai_status == "error":
        overall = "unhealthy"
    elif not rag_status["ready"]:
        overall = "degraded"

    return {
        "status": overall,
        "ai": ai_health,
        "rag": rag_status,
    }

