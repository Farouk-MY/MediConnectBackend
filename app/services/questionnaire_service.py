"""
Questionnaire Service — Business Logic Orchestrator (v2 — Batch Mode)

Key optimizations:
- Batch question generation: ALL questions generated in 1 LLM call at session start
- Heuristic language detection: no LLM call needed
- Urgency detection: only at session start (on initial symptoms)
- Per-answer latency: ~0ms (questions pre-generated, served from DB)
- Total LLM calls per session: 2 (batch questions + doctor summary)

Flow:
  Patient submits symptoms
    → Heuristic language detection (~0ms)
    → RAG context retrieval (~200ms)
    → Batch generate ALL questions + urgency check (1 LLM call, ~3-5s)
    → Store pre-generated questions in session
    → Serve Q1 instantly

  Patient answers Q1
    → Store answer (~50ms)
    → Serve Q2 from pre-generated list (~0ms)
    → ... repeat until last question ...

  Last answer submitted
    → Generate doctor summary (1 LLM call, ~3-5s)
    → Return completion
"""

import json
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.questionnaire import (
    QuestionnaireSession,
    QuestionnaireAnswer,
    QuestionnaireStatus,
    UrgencyLevel,
)
from app.models.appointment import Appointment
from app.services.ai_service import ai_service
from app.services.rag_service import rag_service
from app.services.prompt_templates import get_ui_strings
from app.schemas.questionnaire import (
    QuestionnaireStartResponse,
    NextQuestionResponse,
    QuestionOption,
    CompletionResponse,
    DoctorSummaryResponse,
    QuestionnaireSessionResponse,
    AnswerRecord,
    InactivityResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)


class QuestionnaireService:
    """
    Orchestrates the questionnaire lifecycle with batch question generation.
    
    LLM calls: 2 total per session (batch questions at start + summary at end)
    Per-answer latency: ~0ms (served from pre-generated list)
    """

    # ═══════════════════════════════════════════
    #  Start Session
    # ═══════════════════════════════════════════

    async def start_session(
        self,
        db: AsyncSession,
        appointment_id: UUID,
        initial_symptoms: str,
        patient_id: UUID,
    ) -> QuestionnaireStartResponse:
        """
        Start a new questionnaire session with batch question generation.
        
        1. Verify appointment
        2. Check for existing session (resume if exists)
        3. Detect language (heuristic — no LLM call)
        4. Retrieve RAG context
        5. Batch-generate ALL questions + urgency check (1 LLM call)
        6. Store pre-generated questions in session
        7. Serve first question instantly
        """
        # 1. Load appointment
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()
        if not appointment:
            raise ValueError("Appointment not found")
        if not appointment.is_paid:
            raise ValueError("Appointment must be paid before starting the questionnaire")

        # 2. Check for existing session
        existing = await db.execute(
            select(QuestionnaireSession).where(
                QuestionnaireSession.appointment_id == appointment_id
            )
        )
        existing_session = existing.scalar_one_or_none()
        if existing_session:
            if existing_session.status == QuestionnaireStatus.IN_PROGRESS:
                return await self._resume_session(db, existing_session)
            else:
                raise ValueError(f"Questionnaire already {existing_session.status.value}")

        # 3. Detect language — HEURISTIC (no LLM call, ~0ms)
        lang_result = ai_service.detect_language(initial_symptoms)
        language = lang_result["language"]
        logger.info(f"🌐 Language detected (heuristic): {language} (confidence: {lang_result['confidence']:.0%})")

        # 4. Retrieve RAG context
        rag_context = await rag_service.retrieve_context(initial_symptoms, top_k=3)

        # 5. Batch-generate ALL questions + urgency (1 LLM call)
        import time
        start_time = time.time()

        batch_result = await ai_service.generate_all_questions(
            initial_symptoms=initial_symptoms,
            language=language,
            rag_context=rag_context,
            max_questions=settings.QUESTIONNAIRE_MAX_QUESTIONS,
        )

        elapsed = time.time() - start_time
        questions = batch_result["questions"]
        urgency_level = UrgencyLevel(batch_result.get("urgency_level", "none"))

        logger.info(
            f"🧠 Batch generation: {len(questions)} questions in {elapsed:.1f}s "
            f"(urgency={batch_result.get('urgency_level', 'none')}, "
            f"provider={ai_service._active_provider})"
        )

        # If urgency is high/critical, reduce questions
        if urgency_level in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
            questions = questions[:3]
            logger.info(f"⚠️ High urgency — capping at {len(questions)} questions")

        # 6. Create session with pre-generated questions stored
        session = QuestionnaireSession(
            appointment_id=appointment_id,
            patient_id=patient_id,
            doctor_id=appointment.doctor_id,
            detected_language=language,
            status=QuestionnaireStatus.IN_PROGRESS,
            initial_symptoms=initial_symptoms,
            pre_generated_questions=questions,
            urgency_level=urgency_level,
            urgency_note=batch_result.get("urgency_note", ""),
            max_questions=len(questions),
            current_question_index=0,
            last_activity_at=datetime.utcnow(),
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        # 7. Serve first question instantly
        ui_strings = get_ui_strings(language)
        first_q = questions[0]

        first_question = NextQuestionResponse(
            session_id=session.id,
            question_index=0,
            question_text=first_q["question_text"],
            question_type=first_q["question_type"],
            options=[QuestionOption(**opt) for opt in first_q.get("options", [])],
            progress=0.0,
            is_complete=False,
            urgency_flag=batch_result["urgency_level"] if batch_result["urgency_level"] != "none" else None,
            urgency_message=batch_result.get("urgency_note") or None,
            disclaimer=ui_strings["disclaimer"],
            max_questions=len(questions),
        )

        return QuestionnaireStartResponse(
            session_id=session.id,
            detected_language=language,
            first_question=first_question,
            disclaimer=ui_strings["disclaimer"],
            ui_strings=ui_strings,
            max_questions=len(questions),
        )

    # ═══════════════════════════════════════════
    #  Resume Session
    # ═══════════════════════════════════════════

    async def _resume_session(
        self,
        db: AsyncSession,
        session: QuestionnaireSession,
    ) -> QuestionnaireStartResponse:
        """Resume an in-progress session — serve the next pre-generated question."""
        language = session.detected_language
        ui_strings = get_ui_strings(language)

        questions = session.pre_generated_questions or []
        idx = session.current_question_index

        if idx >= len(questions):
            # No more questions — complete
            completion = await self._complete_session(db, session)
            # Wrap completion in start response format
            return QuestionnaireStartResponse(
                session_id=session.id,
                detected_language=language,
                first_question=None,
                disclaimer=ui_strings["disclaimer"],
                ui_strings=ui_strings,
            )

        q = questions[idx]

        # Update last activity
        session.last_activity_at = datetime.utcnow()
        await db.commit()

        actual_total = len(questions)
        progress = idx / actual_total if actual_total > 0 else 0

        first_question = NextQuestionResponse(
            session_id=session.id,
            question_index=idx,
            question_text=q["question_text"],
            question_type=q["question_type"],
            options=[QuestionOption(**opt) for opt in q.get("options", [])],
            progress=progress,
            is_complete=False,
            urgency_flag=session.urgency_level.value if session.urgency_level != UrgencyLevel.NONE else None,
            disclaimer=ui_strings["disclaimer"],
            max_questions=actual_total,
        )

        return QuestionnaireStartResponse(
            session_id=session.id,
            detected_language=language,
            first_question=first_question,
            disclaimer=ui_strings["disclaimer"],
            ui_strings=ui_strings,
            max_questions=actual_total,
        )

    # ═══════════════════════════════════════════
    #  Submit Answer (INSTANT — no LLM call)
    # ═══════════════════════════════════════════

    async def submit_answer(
        self,
        db: AsyncSession,
        session_id: UUID,
        question_text: Optional[str],
        answer_text: Optional[str],
        answer_selections: Optional[list],
        other_text: Optional[str],
    ) -> NextQuestionResponse | CompletionResponse:
        """
        Submit an answer and get the next pre-generated question.
        
        ZERO LLM calls — questions are served from the pre-generated list.
        Latency: ~50ms (just DB read/write)
        """
        # Load session
        session = await self._get_session(db, session_id)
        if session.status != QuestionnaireStatus.IN_PROGRESS:
            raise ValueError(f"Questionnaire is {session.status.value}, cannot submit answers")

        language = session.detected_language
        ui_strings = get_ui_strings(language)

        # Process answer text
        final_answer_text = answer_text or ""
        final_selections = answer_selections or []

        # Handle "Other" option
        if other_text and "other" in [s.lower() for s in final_selections]:
            final_answer_text = other_text
            final_selections = [s for s in final_selections if s.lower() != "other"]
            final_selections.append(f"Other: {other_text}")

        # Quick local normalization (no AI call)
        parts = final_selections + ([final_answer_text] if final_answer_text and final_answer_text not in final_selections else [])
        normalized = ", ".join(parts) if parts else "No answer provided"

        # Get the actual question text from pre-generated list
        questions = session.pre_generated_questions or []
        if session.current_question_index < len(questions):
            stored_question_text = questions[session.current_question_index].get("question_text", question_text or f"Q{session.current_question_index + 1}")
        else:
            stored_question_text = question_text or f"Q{session.current_question_index + 1}"

        # Store the answer
        answer = QuestionnaireAnswer(
            session_id=session_id,
            question_index=session.current_question_index,
            question_text=stored_question_text,
            question_type=questions[session.current_question_index].get("question_type", "radio") if session.current_question_index < len(questions) else "radio",
            question_options=questions[session.current_question_index].get("options", []) if session.current_question_index < len(questions) else [],
            answer_text=normalized,
            answer_selections=final_selections,
        )
        db.add(answer)

        # Increment question index
        session.current_question_index += 1
        session.last_activity_at = datetime.utcnow()

        # Check if we should complete
        should_complete = session.current_question_index >= session.max_questions

        if should_complete:
            completion = await self._complete_session(db, session)
            return completion

        await db.commit()

        # Serve next pre-generated question INSTANTLY
        next_idx = session.current_question_index
        next_q = questions[next_idx] if next_idx < len(questions) else None

        if not next_q:
            # Shouldn't happen, but handle gracefully
            completion = await self._complete_session(db, session)
            return completion

        actual_total = len(questions)
        progress = next_idx / actual_total if actual_total > 0 else 0

        return NextQuestionResponse(
            session_id=session.id,
            question_index=next_idx,
            question_text=next_q["question_text"],
            question_type=next_q["question_type"],
            options=[QuestionOption(**opt) for opt in next_q.get("options", [])],
            progress=progress,
            is_complete=False,
            urgency_flag=session.urgency_level.value if session.urgency_level != UrgencyLevel.NONE else None,
            disclaimer=ui_strings["disclaimer"],
            max_questions=actual_total,
        )

    # ═══════════════════════════════════════════
    #  Skip Questionnaire
    # ═══════════════════════════════════════════

    async def skip_questionnaire(
        self,
        db: AsyncSession,
        session_id: UUID,
        reason: Optional[str] = None,
    ) -> CompletionResponse:
        """Skip the entire questionnaire. Generates a partial summary if answers exist."""
        session = await self._get_session(db, session_id)
        if session.status not in (QuestionnaireStatus.IN_PROGRESS, QuestionnaireStatus.PARTIALLY_COMPLETED):
            raise ValueError(f"Cannot skip questionnaire in {session.status.value} state")

        session.status = QuestionnaireStatus.SKIPPED
        session.skip_reason = reason
        session.completed_at = datetime.utcnow()

        # Generate partial summary if there are any answers
        if session.answers:
            await self._generate_and_store_summary(db, session)

        await db.commit()

        # Check if teleconsultation
        appointment = await self._get_appointment(db, session.appointment_id)
        is_teleconsult = appointment.consultation_type == "online"

        ui_strings = get_ui_strings(session.detected_language)

        return CompletionResponse(
            session_id=session.id,
            appointment_id=session.appointment_id,
            status="skipped",
            message=ui_strings["completion_message"],
            is_teleconsultation=is_teleconsult,
            consultation_room_url=f"https://{settings.JITSI_DOMAIN}/{appointment.video_call_room_id}" if is_teleconsult and appointment.video_call_room_id else None,
            urgency_level=session.urgency_level.value,
        )

    # ═══════════════════════════════════════════
    #  Inactivity Handling
    # ═══════════════════════════════════════════

    async def handle_inactivity(
        self,
        db: AsyncSession,
        session_id: UUID,
        event_type: str,
    ) -> InactivityResponse:
        """Handle inactivity events from the client."""
        session = await self._get_session(db, session_id)
        ui_strings = get_ui_strings(session.detected_language)

        if event_type == "reminder":
            session.reminder_count += 1
            session.last_activity_at = datetime.utcnow()
            await db.commit()

            return InactivityResponse(
                session_id=session.id,
                event_type="reminder",
                message=ui_strings["inactivity_reminder"],
                status=session.status.value,
                auto_saved=False,
            )

        elif event_type == "timeout":
            if session.answers:
                session.status = QuestionnaireStatus.PARTIALLY_COMPLETED
                await self._generate_and_store_summary(db, session)
            else:
                session.status = QuestionnaireStatus.INACTIVE_TIMEOUT

            session.completed_at = datetime.utcnow()
            await db.commit()

            return InactivityResponse(
                session_id=session.id,
                event_type="timeout",
                message=ui_strings["inactivity_timeout"],
                status=session.status.value,
                auto_saved=True,
            )

        raise ValueError(f"Invalid event_type: {event_type}")

    # ═══════════════════════════════════════════
    #  Get Session & Summary
    # ═══════════════════════════════════════════

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> QuestionnaireSessionResponse:
        """Get full session state for resuming or inspection."""
        session = await self._get_session(db, session_id)
        return self._build_session_response(session)

    async def get_session_by_appointment(
        self,
        db: AsyncSession,
        appointment_id: UUID,
    ) -> Optional[QuestionnaireSessionResponse]:
        """Get session by appointment ID."""
        result = await db.execute(
            select(QuestionnaireSession)
            .options(selectinload(QuestionnaireSession.answers))
            .where(QuestionnaireSession.appointment_id == appointment_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return None
        return self._build_session_response(session)

    async def get_doctor_summary(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> Optional[DoctorSummaryResponse]:
        """Get the doctor-facing summary."""
        session = await self._get_session(db, session_id)
        if not session.doctor_summary:
            return None

        # Get patient name from appointment
        appointment = await self._get_appointment(db, session.appointment_id)

        # Build conversation log
        conversation_log = [
            {
                "question": a.question_text,
                "answer": a.answer_text or ", ".join(a.answer_selections or []),
            }
            for a in session.answers
        ]

        return DoctorSummaryResponse(
            session_id=session.id,
            appointment_id=session.appointment_id,
            patient_name=None,  # Will be populated by the route handler
            status=session.status.value,
            language=session.detected_language,
            urgency_level=session.urgency_level.value,
            summary=session.doctor_summary or {},
            conversation_log=conversation_log,
            created_at=session.created_at,
            completed_at=session.completed_at,
        )

    # ═══════════════════════════════════════════
    #  Internal Helpers
    # ═══════════════════════════════════════════

    async def _get_session(self, db: AsyncSession, session_id: UUID) -> QuestionnaireSession:
        """Load session with answers."""
        result = await db.execute(
            select(QuestionnaireSession)
            .options(selectinload(QuestionnaireSession.answers))
            .where(QuestionnaireSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError("Questionnaire session not found")
        return session

    async def _get_appointment(self, db: AsyncSession, appointment_id: UUID) -> Appointment:
        """Load appointment."""
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()
        if not appointment:
            raise ValueError("Appointment not found")
        return appointment

    async def _complete_session(
        self,
        db: AsyncSession,
        session: QuestionnaireSession,
    ) -> CompletionResponse:
        """Complete the session and generate the doctor summary."""
        await self._generate_and_store_summary(db, session)

        session.status = QuestionnaireStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        await db.commit()

        # Check if teleconsultation
        appointment = await self._get_appointment(db, session.appointment_id)
        is_teleconsult = appointment.consultation_type == "online"

        ui_strings = get_ui_strings(session.detected_language)
        message = ui_strings["completion_teleconsult"] if is_teleconsult else ui_strings["completion_inperson"]

        return CompletionResponse(
            session_id=session.id,
            appointment_id=session.appointment_id,
            status="completed",
            message=message,
            is_teleconsultation=is_teleconsult,
            consultation_room_url=f"https://{settings.JITSI_DOMAIN}/{appointment.video_call_room_id}" if is_teleconsult and appointment.video_call_room_id else None,
            urgency_level=session.urgency_level.value,
        )

    async def _generate_and_store_summary(
        self,
        db: AsyncSession,
        session: QuestionnaireSession,
    ):
        """Generate and store the doctor summary."""
        conversation_log = self._build_conversation_history(session.answers)
        rag_context = await rag_service.retrieve_context(session.initial_symptoms, top_k=3)

        summary = await ai_service.generate_doctor_summary(
            initial_symptoms=session.initial_symptoms,
            conversation_log=conversation_log,
            language=session.detected_language,
            status=session.status.value if session.status else "in_progress",
            rag_context=rag_context,
        )

        session.doctor_summary = summary

    def _build_conversation_history(self, answers: list) -> str:
        """Build formatted conversation history from answers."""
        if not answers:
            return ""

        lines = []
        for a in sorted(answers, key=lambda x: x.question_index):
            answer_text = a.answer_text or ", ".join(a.answer_selections or [])
            lines.append(f"Q{a.question_index + 1}: {a.question_text}")
            lines.append(f"A{a.question_index + 1}: {answer_text}")
            lines.append("")

        return "\n".join(lines)

    def _build_session_response(
        self, session: QuestionnaireSession
    ) -> QuestionnaireSessionResponse:
        """Build session response from DB model."""
        answers = [
            AnswerRecord(
                question_index=a.question_index,
                question_text=a.question_text,
                question_type=a.question_type,
                question_options=[
                    QuestionOption(**opt) for opt in (a.question_options or [])
                ],
                answer_text=a.answer_text,
                answer_selections=a.answer_selections or [],
                created_at=a.created_at,
            )
            for a in sorted(session.answers, key=lambda x: x.question_index)
        ]

        ui_strings = get_ui_strings(session.detected_language)

        return QuestionnaireSessionResponse(
            id=session.id,
            appointment_id=session.appointment_id,
            patient_id=session.patient_id,
            doctor_id=session.doctor_id,
            detected_language=session.detected_language,
            status=session.status.value,
            current_question_index=session.current_question_index,
            max_questions=session.max_questions,
            initial_symptoms=session.initial_symptoms,
            urgency_level=session.urgency_level.value,
            urgency_note=session.urgency_note,
            answers=answers,
            created_at=session.created_at,
            updated_at=session.updated_at,
            completed_at=session.completed_at,
            ui_strings=ui_strings,
        )


# Singleton
questionnaire_service = QuestionnaireService()
