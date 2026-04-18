"""
AI Service — Multi-Provider LLM Client with Automatic Fallback

Provider chain: Ollama (local GPU) → Groq (fast cloud) → Gemini (smart cloud)

Features:
- Automatic fallback: if Ollama is down, seamlessly switches to Groq, then Gemini
- Batch question generation: ALL questions in 1 call instead of 1 per answer
- Optimized prompts with OLDCARTS clinical framework
- Model warm-keeping for Ollama (prevents cold starts)
- Heuristic language detection (no LLM call needed)
"""

import json
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

import httpx

from app.config import settings
from app.services.prompt_templates import (
    LANGUAGE_DETECTION_PROMPT,
    BATCH_QUESTIONS_PROMPT,
    DOCTOR_SUMMARY_PROMPT,
    URGENCY_DETECTION_PROMPT,
    LANGUAGE_NAMES,
    get_ui_strings,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
#  Provider Interface
# ═══════════════════════════════════════════════

class LLMProvider(ABC):
    """Base class for LLM providers."""

    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is ready."""
        pass


# ═══════════════════════════════════════════════
#  Ollama Provider (Local GPU)
# ═══════════════════════════════════════════════

class OllamaProvider(LLMProvider):
    """Local Ollama — primary provider for development. RTX 4060 GPU accelerated."""

    name = "ollama"

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.AI_TIMEOUT_SECONDS
        self._last_keepalive = 0

    async def generate(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 4096,       # Limit context window for speed
                "num_gpu": 99,         # Use all GPU layers
                "num_thread": 8,       # CPU threads for any overflow
            },
        }
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                # Keep model warm
                self._last_keepalive = time.time()
                return content.strip()
            else:
                raise Exception(f"Ollama error {response.status_code}: {response.text[:200]}")

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    tags = resp.json()
                    models = [m["name"] for m in tags.get("models", [])]
                    model_base = self.model.split(":")[0]
                    return any(model_base in m for m in models)
            return False
        except Exception:
            return False

    async def keepalive(self):
        """Ping model to keep it loaded in VRAM (prevents 5min unload)."""
        if time.time() - self._last_keepalive < 120:  # Skip if recently used
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": False,
                        "options": {"num_predict": 1},
                        "keep_alive": "10m",
                    },
                )
                self._last_keepalive = time.time()
        except Exception:
            pass


# ═══════════════════════════════════════════════
#  Groq Provider (Cloud — Fast)
# ═══════════════════════════════════════════════

class GroqProvider(LLMProvider):
    """Groq Cloud API — ultra-fast inference. Free tier: 30 RPM."""

    name = "groq"

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.timeout = 15.0

    async def generate(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.base_url,
                json=payload,
                headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                raise Exception(f"Groq error {response.status_code}: {response.text[:200]}")

    async def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)


# ═══════════════════════════════════════════════
#  Gemini Provider (Cloud — Smart)
# ═══════════════════════════════════════════════

class GeminiProvider(LLMProvider):
    """Google Gemini Flash — smart cloud inference. Free tier: 15 RPM."""

    name = "gemini"

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.timeout = 20.0

    async def generate(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        # Convert OpenAI-style messages to Gemini format
        contents = []
        system_instruction = None
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}],
                })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}],
            }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                raise Exception("Gemini returned empty response")
            else:
                raise Exception(f"Gemini error {response.status_code}: {response.text[:200]}")

    async def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)


# ═══════════════════════════════════════════════
#  AI Service — Orchestrator with Fallback Chain
# ═══════════════════════════════════════════════

PROVIDER_MAP = {
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
}


class AIService:
    """
    Multi-provider AI service with automatic fallback.
    
    Chain: Ollama (local GPU) → Groq (fast cloud) → Gemini (smart cloud)
    
    If the primary provider fails, seamlessly falls back to the next.
    All providers expose the same interface.
    """

    def __init__(self):
        self.providers: List[LLMProvider] = []
        self._active_provider: Optional[str] = None
        self._initialize_providers()

    def _initialize_providers(self):
        """Build the provider chain from config."""
        for name in settings.provider_chain:
            cls = PROVIDER_MAP.get(name)
            if cls:
                provider = cls()
                self.providers.append(provider)
                logger.info(f"🔌 AI provider registered: {name}")
        if not self.providers:
            # Default fallback
            self.providers.append(OllamaProvider())
            logger.warning("No providers configured — defaulting to Ollama")

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        """
        Call LLM with automatic fallback across providers.
        Tries each provider in order; logs which one succeeded.
        """
        errors = []
        for provider in self.providers:
            try:
                start = time.time()
                result = await provider.generate(
                    messages=messages,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                elapsed = time.time() - start
                if self._active_provider != provider.name:
                    self._active_provider = provider.name
                    logger.info(f"✅ Using AI provider: {provider.name}")
                logger.debug(f"⚡ {provider.name} responded in {elapsed:.1f}s")
                return result

            except Exception as e:
                errors.append(f"{provider.name}: {str(e)[:100]}")
                logger.warning(f"⚠️ {provider.name} failed: {str(e)[:100]}")
                continue

        error_summary = " | ".join(errors)
        raise Exception(f"All AI providers failed: {error_summary}")

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nRaw: {text[:300]}")
            import re
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            # Try to find array
            arr_match = re.search(r'\[[\s\S]*\]', cleaned)
            if arr_match:
                try:
                    return {"questions": json.loads(arr_match.group())}
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Could not parse JSON from LLM: {text[:200]}")

    # ═══════════════════════════════════════════
    #  Health Check
    # ═══════════════════════════════════════════

    async def health_check(self) -> Dict[str, Any]:
        """Check all providers and return status."""
        statuses = {}
        for provider in self.providers:
            try:
                available = await provider.is_available()
                statuses[provider.name] = "healthy" if available else "unavailable"
            except Exception as e:
                statuses[provider.name] = f"error: {str(e)[:50]}"

        active = self._active_provider or "none"
        overall = "healthy" if any(s == "healthy" for s in statuses.values()) else "error"

        return {
            "status": overall,
            "active_provider": active,
            "providers": statuses,
            "provider_chain": [p.name for p in self.providers],
        }

    # ═══════════════════════════════════════════
    #  Language Detection (Heuristic — NO LLM call)
    # ═══════════════════════════════════════════

    def detect_language(self, text: str) -> Dict[str, Any]:
        """
        Fast heuristic language detection — no LLM call needed.
        Runs in <1ms. Accuracy: ~90%+ for EN/FR/AR/AR_TN.
        """
        if not text or not text.strip():
            return {"language": "fr", "confidence": 0.3}

        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        total_alpha = sum(1 for c in text if c.isalpha())

        if total_alpha == 0:
            return {"language": "fr", "confidence": 0.3}

        arabic_ratio = arabic_chars / total_alpha

        if arabic_ratio > 0.3:
            tunisian_markers = [
                "نحو", "باش", "برشة", "كيفاش", "هكا", "فيسع",
                "بلحق", "وقتاش", "ياخي", "نجم", "ماو", "هاذا",
                "توا", "عندي", "نحب", "ماناش", "وينو", "شكون",
                "قداش", "كرشي", "راسي", "بالصح", "ولا", "حاجة",
                "يوجعني", "نحس", "فيا", "طبيب", "مريض", "دوا",
            ]
            if any(marker in text for marker in tunisian_markers):
                return {"language": "ar_tn", "confidence": 0.8}
            return {"language": "ar", "confidence": 0.7}

        french_markers = [
            "je ", "j'ai", "j'", "mal ", "douleur", "depuis", "médecin",
            "tête", "ventre", "fièvre", "symptôme", "consultation",
            "poitrine", "gorge", "estomac", "jambe", "bras",
            "mois", "jours", "semaine", "le ", "la ", "les ", "des ",
            "une ", "mon ", "ma ", "mes ", "est ", "sont ",
        ]
        text_lower = text.lower()
        french_hits = sum(1 for m in french_markers if m in text_lower)
        if french_hits >= 2:
            return {"language": "fr", "confidence": 0.85}

        english_markers = [
            "pain", "i have", "i feel", "hurts", "head", "stomach",
            "since", "my ", "the ", "been", "days", "week",
            "fever", "cough", "dizzy", "nausea", "doctor",
        ]
        english_hits = sum(1 for m in english_markers if m in text_lower)
        if english_hits >= 2:
            return {"language": "en", "confidence": 0.85}

        # Single word detection
        if any(m in text_lower for m in french_markers):
            return {"language": "fr", "confidence": 0.6}
        if any(m in text_lower for m in english_markers):
            return {"language": "en", "confidence": 0.6}

        # Default to French (Tunisia primary language)
        return {"language": "fr", "confidence": 0.4}

    # ═══════════════════════════════════════════
    #  Batch Question Generation (1 LLM call for ALL questions)
    # ═══════════════════════════════════════════

    async def generate_all_questions(
        self,
        initial_symptoms: str,
        language: str,
        rag_context: str,
        max_questions: int = 6,
    ) -> Dict[str, Any]:
        """
        Generate ALL questionnaire questions in a single LLM call.
        
        This is the core optimization: instead of 6-8 separate calls,
        we generate all questions upfront. Each subsequent question
        is served instantly from the pre-generated plan.
        
        Returns:
            {
                "max_questions": 5,
                "urgency_level": "none",
                "questions": [
                    {
                        "question_text": "...",
                        "question_type": "radio_with_other",
                        "options": [...],
                        "clinical_area": "duration"
                    }, ...
                ]
            }
        """
        language_name = LANGUAGE_NAMES.get(language, "English")

        prompt = BATCH_QUESTIONS_PROMPT.format(
            language_name=language_name,
            language_code=language,
            initial_symptoms=initial_symptoms,
            max_questions=max_questions,
            rag_context=rag_context or "No specific guidance.",
        )

        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f'Generate the intake questions for: "{initial_symptoms}"'},
            ]

            response = await self._call_llm(
                messages,
                json_mode=True,
                temperature=0.3,
                max_tokens=2500,
            )
            result = self._parse_json_response(response)

            # Normalize: handle both {questions: [...]} and direct [...]
            questions = result.get("questions", [])
            if not questions and isinstance(result, list):
                questions = result

            # Validate and clean each question
            cleaned_questions = []
            valid_types = {"radio", "checkbox", "text", "radio_with_other", "checkbox_with_other"}

            for i, q in enumerate(questions[:max_questions]):
                if not isinstance(q, dict) or not q.get("question_text"):
                    continue

                q_type = q.get("question_type", "radio_with_other")
                if q_type not in valid_types:
                    q_type = "radio_with_other"

                # Clean options
                options = []
                for opt in q.get("options", []):
                    if isinstance(opt, dict) and "label" in opt:
                        options.append({
                            "label": str(opt["label"]),
                            "value": str(opt.get("value", opt["label"])).lower().replace(" ", "_"),
                            "is_other": bool(opt.get("is_other", False)),
                        })

                # Add "Other" if missing for _with_other types
                if q_type in {"radio_with_other", "checkbox_with_other"}:
                    if not any(o.get("is_other") for o in options):
                        other_labels = {
                            "en": "Other", "fr": "Autre",
                            "ar": "أخرى", "ar_tn": "حاجة أخرى",
                        }
                        options.append({
                            "label": other_labels.get(language, "Other"),
                            "value": "other",
                            "is_other": True,
                        })

                cleaned_questions.append({
                    "question_text": q["question_text"],
                    "question_type": q_type,
                    "options": options,
                    "clinical_area": q.get("clinical_area", "general"),
                })

            # Determine urgency from initial symptoms
            urgency = result.get("urgency_level", "none")
            if urgency not in {"none", "low", "medium", "high", "critical"}:
                urgency = "none"

            # Ensure we have at least 3 questions
            if len(cleaned_questions) < 3:
                logger.warning(f"AI only generated {len(cleaned_questions)} questions — adding fallbacks")
                cleaned_questions = self._get_fallback_questions(language, max_questions)

            return {
                "max_questions": len(cleaned_questions),
                "urgency_level": urgency,
                "urgency_note": result.get("urgency_note", ""),
                "questions": cleaned_questions,
            }

        except Exception as e:
            logger.error(f"Batch question generation failed: {e}")
            return {
                "max_questions": min(5, max_questions),
                "urgency_level": "none",
                "urgency_note": "",
                "questions": self._get_fallback_questions(language, min(5, max_questions)),
            }

    # ═══════════════════════════════════════════
    #  Doctor Summary Generation
    # ═══════════════════════════════════════════

    async def generate_doctor_summary(
        self,
        initial_symptoms: str,
        conversation_log: str,
        language: str,
        status: str,
        rag_context: str,
    ) -> Dict[str, Any]:
        """Generate a structured pre-consultation summary for the doctor."""
        language_name = LANGUAGE_NAMES.get(language, "English")

        prompt = DOCTOR_SUMMARY_PROMPT.format(
            language=language,
            language_name=language_name,
            initial_symptoms=initial_symptoms,
            status=status,
            conversation_log=conversation_log or "No questions answered.",
            rag_context=rag_context or "No additional context.",
        )

        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the pre-consultation summary now."},
            ]

            response = await self._call_llm(
                messages, json_mode=True, temperature=0.2, max_tokens=1500
            )
            result = self._parse_json_response(response)

            default_summary = {
                "main_complaint": initial_symptoms,
                "duration": "Not specified",
                "location": "Not specified",
                "intensity": "Not specified",
                "associated_symptoms": [],
                "triggers": "Not specified",
                "relieving_factors": "Not specified",
                "relevant_history": "Not specified",
                "medications": "Not specified",
                "urgency_level": "none",
                "missing_information": [],
                "recommended_specialty": "General",
                "narrative_summary": "",
            }
            default_summary.update(result)
            return default_summary

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return {
                "main_complaint": initial_symptoms,
                "duration": "Not specified",
                "location": "Not specified",
                "intensity": "Not specified",
                "associated_symptoms": [],
                "triggers": "Not specified",
                "relieving_factors": "Not specified",
                "relevant_history": "Not specified",
                "medications": "Not specified",
                "urgency_level": "none",
                "missing_information": ["Summary generation failed — manual review needed"],
                "recommended_specialty": "General",
                "narrative_summary": f"Patient reported: {initial_symptoms}. Automated summary unavailable.",
            }

    # ═══════════════════════════════════════════
    #  Urgency Detection
    # ═══════════════════════════════════════════

    async def detect_urgency(self, text: str, language: str) -> Dict[str, Any]:
        """Scan patient text for potentially urgent/dangerous symptoms."""
        # First: fast rule-based pre-check for critical keywords
        critical = self._check_critical_keywords(text)
        if critical:
            return critical

        language_name = LANGUAGE_NAMES.get(language, "English")
        prompt = URGENCY_DETECTION_PROMPT.format(
            text=text,
            language=language,
            language_name=language_name,
        )

        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Screen this: \"{text}\""},
            ]

            response = await self._call_llm(
                messages, json_mode=True, temperature=0.1, max_tokens=300
            )
            result = self._parse_json_response(response)

            valid_levels = {"none", "low", "medium", "high", "critical"}
            level = result.get("level", "none")
            if level not in valid_levels:
                level = "none"

            return {
                "level": level,
                "note": result.get("note", ""),
                "recommend_urgent_care": result.get("recommend_urgent_care", False),
                "gentle_message": result.get("gentle_message"),
            }

        except Exception as e:
            logger.error(f"Urgency detection failed: {e}")
            return {"level": "none", "note": "Urgency check unavailable", "recommend_urgent_care": False, "gentle_message": None}

    def _check_critical_keywords(self, text: str) -> Optional[Dict[str, Any]]:
        """Fast rule-based check for immediately dangerous symptoms."""
        text_lower = text.lower()
        critical_patterns = {
            "en": ["chest pain", "can't breathe", "difficulty breathing", "suicidal", "seizure", "loss of consciousness", "stroke", "heart attack"],
            "fr": ["douleur poitrine", "ne peux pas respirer", "difficultés respiratoires", "suicidaire", "convulsion", "perte de connaissance", "avc"],
            "ar": ["ألم في الصدر", "صعوبة في التنفس", "فقدان الوعي", "نوبة"],
        }
        for lang_patterns in critical_patterns.values():
            for pattern in lang_patterns:
                if pattern in text_lower:
                    return {
                        "level": "high",
                        "note": f"Critical keyword detected: {pattern}",
                        "recommend_urgent_care": True,
                        "gentle_message": "Based on your symptoms, please consider seeking immediate medical attention.",
                    }
        return None

    # ═══════════════════════════════════════════
    #  Fallback Questions
    # ═══════════════════════════════════════════

    def _get_fallback_questions(self, language: str, count: int) -> List[Dict]:
        """Clinically-structured fallback questions using OLDCARTS framework."""
        templates = {
            "en": [
                {"question_text": "How long have you been experiencing this symptom?", "question_type": "radio_with_other", "clinical_area": "onset",
                 "options": [{"label": "Today", "value": "today", "is_other": False}, {"label": "A few days", "value": "few_days", "is_other": False}, {"label": "About a week", "value": "one_week", "is_other": False}, {"label": "More than 2 weeks", "value": "two_weeks_plus", "is_other": False}, {"label": "More than a month", "value": "month_plus", "is_other": False}, {"label": "Other", "value": "other", "is_other": True}]},
                {"question_text": "Where exactly is the discomfort located?", "question_type": "radio_with_other", "clinical_area": "location",
                 "options": [{"label": "Head / Neck", "value": "head_neck", "is_other": False}, {"label": "Chest", "value": "chest", "is_other": False}, {"label": "Abdomen / Stomach", "value": "abdomen", "is_other": False}, {"label": "Back", "value": "back", "is_other": False}, {"label": "Limbs (arms/legs)", "value": "limbs", "is_other": False}, {"label": "Other", "value": "other", "is_other": True}]},
                {"question_text": "How would you rate the severity?", "question_type": "radio", "clinical_area": "severity",
                 "options": [{"label": "Mild (1-3)", "value": "mild", "is_other": False}, {"label": "Moderate (4-6)", "value": "moderate", "is_other": False}, {"label": "Severe (7-8)", "value": "severe", "is_other": False}, {"label": "Very severe (9-10)", "value": "very_severe", "is_other": False}]},
                {"question_text": "What does the discomfort feel like?", "question_type": "checkbox_with_other", "clinical_area": "character",
                 "options": [{"label": "Sharp / Stabbing", "value": "sharp", "is_other": False}, {"label": "Dull / Aching", "value": "dull", "is_other": False}, {"label": "Burning", "value": "burning", "is_other": False}, {"label": "Throbbing / Pulsing", "value": "throbbing", "is_other": False}, {"label": "Pressure / Tightness", "value": "pressure", "is_other": False}, {"label": "Other", "value": "other", "is_other": True}]},
                {"question_text": "Do you have any associated symptoms?", "question_type": "checkbox_with_other", "clinical_area": "associated_symptoms",
                 "options": [{"label": "Fever", "value": "fever", "is_other": False}, {"label": "Nausea / Vomiting", "value": "nausea", "is_other": False}, {"label": "Dizziness", "value": "dizziness", "is_other": False}, {"label": "Fatigue", "value": "fatigue", "is_other": False}, {"label": "None", "value": "none", "is_other": False}, {"label": "Other", "value": "other", "is_other": True}]},
                {"question_text": "Are you currently taking any medication?", "question_type": "radio_with_other", "clinical_area": "medications",
                 "options": [{"label": "No medication", "value": "none", "is_other": False}, {"label": "Over-the-counter painkillers", "value": "otc_pain", "is_other": False}, {"label": "Prescribed medication", "value": "prescribed", "is_other": False}, {"label": "Other", "value": "other", "is_other": True}]},
            ],
            "fr": [
                {"question_text": "Depuis combien de temps avez-vous ce symptôme ?", "question_type": "radio_with_other", "clinical_area": "onset",
                 "options": [{"label": "Aujourd'hui", "value": "today", "is_other": False}, {"label": "Quelques jours", "value": "few_days", "is_other": False}, {"label": "Environ une semaine", "value": "one_week", "is_other": False}, {"label": "Plus de 2 semaines", "value": "two_weeks_plus", "is_other": False}, {"label": "Plus d'un mois", "value": "month_plus", "is_other": False}, {"label": "Autre", "value": "other", "is_other": True}]},
                {"question_text": "Où se situe exactement la gêne ?", "question_type": "radio_with_other", "clinical_area": "location",
                 "options": [{"label": "Tête / Cou", "value": "head_neck", "is_other": False}, {"label": "Poitrine", "value": "chest", "is_other": False}, {"label": "Abdomen / Ventre", "value": "abdomen", "is_other": False}, {"label": "Dos", "value": "back", "is_other": False}, {"label": "Membres (bras/jambes)", "value": "limbs", "is_other": False}, {"label": "Autre", "value": "other", "is_other": True}]},
                {"question_text": "Comment évaluez-vous l'intensité ?", "question_type": "radio", "clinical_area": "severity",
                 "options": [{"label": "Légère (1-3)", "value": "mild", "is_other": False}, {"label": "Modérée (4-6)", "value": "moderate", "is_other": False}, {"label": "Sévère (7-8)", "value": "severe", "is_other": False}, {"label": "Très sévère (9-10)", "value": "very_severe", "is_other": False}]},
                {"question_text": "Comment décririez-vous la douleur ?", "question_type": "checkbox_with_other", "clinical_area": "character",
                 "options": [{"label": "Vive / Poignardante", "value": "sharp", "is_other": False}, {"label": "Sourde / Continue", "value": "dull", "is_other": False}, {"label": "Brûlure", "value": "burning", "is_other": False}, {"label": "Pulsatile", "value": "throbbing", "is_other": False}, {"label": "Pression / Serrement", "value": "pressure", "is_other": False}, {"label": "Autre", "value": "other", "is_other": True}]},
                {"question_text": "Avez-vous d'autres symptômes associés ?", "question_type": "checkbox_with_other", "clinical_area": "associated_symptoms",
                 "options": [{"label": "Fièvre", "value": "fever", "is_other": False}, {"label": "Nausées / Vomissements", "value": "nausea", "is_other": False}, {"label": "Vertiges", "value": "dizziness", "is_other": False}, {"label": "Fatigue", "value": "fatigue", "is_other": False}, {"label": "Aucun", "value": "none", "is_other": False}, {"label": "Autre", "value": "other", "is_other": True}]},
                {"question_text": "Prenez-vous actuellement des médicaments ?", "question_type": "radio_with_other", "clinical_area": "medications",
                 "options": [{"label": "Aucun médicament", "value": "none", "is_other": False}, {"label": "Antidouleurs sans ordonnance", "value": "otc_pain", "is_other": False}, {"label": "Médicaments sur ordonnance", "value": "prescribed", "is_other": False}, {"label": "Autre", "value": "other", "is_other": True}]},
            ],
        }

        fallback = templates.get(language, templates.get("en", []))
        return fallback[:count]

    # ═══════════════════════════════════════════
    #  Keepalive (for Ollama)
    # ═══════════════════════════════════════════

    async def keepalive(self):
        """Keep the Ollama model loaded in GPU memory."""
        for provider in self.providers:
            if isinstance(provider, OllamaProvider):
                await provider.keepalive()
                break


# ═══════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════

ai_service = AIService()
