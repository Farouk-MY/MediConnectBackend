"""
AI Pre-Diagnosis Smart Questionnaire — Optimized Prompt Templates

Key optimizations:
- BATCH_QUESTIONS_PROMPT: generates ALL questions in 1 call (replaces per-question generation)
- OLDCARTS clinical framework: Onset, Location, Duration, Character, Aggravating, Relieving, Timing, Severity
- 40-50% shorter prompts for faster inference
- Explicit JSON schemas for reliable parsing

IMPORTANT: These prompts NEVER provide diagnosis. They only collect information.
"""

# ═══════════════════════════════════════════════
#  Multilingual UI Strings
# ═══════════════════════════════════════════════

UI_STRINGS = {
    "en": {
        "disclaimer": "This questionnaire helps your doctor prepare for your visit. It does not provide a medical diagnosis.",
        "skip_confirm_title": "Skip Questionnaire?",
        "skip_confirm_message": "Are you sure you want to skip? Your doctor will have fewer details about your symptoms.",
        "skip_confirm_yes": "Yes, Skip",
        "skip_confirm_no": "Continue",
        "inactivity_reminder": "Are you still there? Your progress has been saved.",
        "inactivity_timeout": "We've saved your answers automatically. You can continue later or proceed to your appointment.",
        "completion_message": "Thank you! Your responses have been shared with your doctor.",
        "completion_teleconsult": "Connecting you to your doctor now...",
        "completion_inperson": "Your doctor will review your responses before your visit.",
        "initial_prompt": "Please describe your main symptom or reason for this visit.",
        "submit_button": "Next",
        "skip_button": "Skip Questionnaire",
        "other_placeholder": "Please specify...",
        "loading_question": "Preparing your next question...",
        "error_retry": "Something went wrong. Please try again.",
        "urgency_warning": "Based on your symptoms, we recommend seeking immediate medical attention. Please contact emergency services or visit the nearest emergency room.",
        "back_button": "Back",
        "progress_label": "Question {current} of {total}",
        "questionnaire_title": "AI Questionnaire",
        "loading_ai": "AI is preparing your questions...",
    },
    "fr": {
        "disclaimer": "Ce questionnaire aide votre médecin à préparer votre consultation. Il ne fournit pas de diagnostic médical.",
        "skip_confirm_title": "Passer le questionnaire ?",
        "skip_confirm_message": "Êtes-vous sûr de vouloir passer ? Votre médecin aura moins de détails sur vos symptômes.",
        "skip_confirm_yes": "Oui, passer",
        "skip_confirm_no": "Continuer",
        "inactivity_reminder": "Êtes-vous toujours là ? Votre progression a été sauvegardée.",
        "inactivity_timeout": "Vos réponses ont été sauvegardées automatiquement. Vous pouvez continuer plus tard.",
        "completion_message": "Merci ! Vos réponses ont été partagées avec votre médecin.",
        "completion_teleconsult": "Connexion avec votre médecin en cours...",
        "completion_inperson": "Votre médecin consultera vos réponses avant votre visite.",
        "initial_prompt": "Veuillez décrire votre symptôme principal ou la raison de votre visite.",
        "submit_button": "Suivant",
        "skip_button": "Passer le questionnaire",
        "other_placeholder": "Veuillez préciser...",
        "loading_question": "Préparation de votre prochaine question...",
        "error_retry": "Une erreur est survenue. Veuillez réessayer.",
        "urgency_warning": "D'après vos symptômes, nous vous recommandons de consulter immédiatement un médecin.",
        "back_button": "Retour",
        "progress_label": "Question {current} sur {total}",
        "questionnaire_title": "Questionnaire IA",
        "loading_ai": "L'IA prépare vos questions...",
    },
    "ar": {
        "disclaimer": "هذا الاستبيان يساعد طبيبك في التحضير لزيارتك. لا يقدم تشخيصاً طبياً.",
        "skip_confirm_title": "تخطي الاستبيان؟",
        "skip_confirm_message": "هل أنت متأكد من التخطي؟ سيكون لدى طبيبك تفاصيل أقل عن أعراضك.",
        "skip_confirm_yes": "نعم، تخطي",
        "skip_confirm_no": "متابعة",
        "inactivity_reminder": "هل ما زلت هنا؟ تم حفظ تقدمك.",
        "inactivity_timeout": "تم حفظ إجاباتك تلقائياً. يمكنك المتابعة لاحقاً.",
        "completion_message": "شكراً لك! تمت مشاركة إجاباتك مع طبيبك.",
        "completion_teleconsult": "جاري الاتصال بطبيبك الآن...",
        "completion_inperson": "سيراجع طبيبك إجاباتك قبل موعدك.",
        "initial_prompt": "يرجى وصف العرض الرئيسي أو سبب زيارتك.",
        "submit_button": "التالي",
        "skip_button": "تخطي الاستبيان",
        "other_placeholder": "يرجى التحديد...",
        "loading_question": "جاري تحضير سؤالك التالي...",
        "error_retry": "حدث خطأ. يرجى المحاولة مرة أخرى.",
        "urgency_warning": "بناءً على أعراضك، ننصحك بطلب رعاية طبية فورية.",
        "back_button": "رجوع",
        "progress_label": "السؤال {current} من {total}",
        "questionnaire_title": "استبيان ذكي",
        "loading_ai": "الذكاء الاصطناعي يحضر أسئلتك...",
    },
    "ar_tn": {
        "disclaimer": "هالاستبيان باش يعاون الطبيب يتحضر للزيارة متاعك. ما يعطيش تشخيص طبي.",
        "skip_confirm_title": "تحب تنقز الاستبيان؟",
        "skip_confirm_message": "متأكد تحب تنقز؟ الطبيب ما يكونش عندو تفاصيل برشة على الأعراض متاعك.",
        "skip_confirm_yes": "إيه، نقز",
        "skip_confirm_no": "كمل",
        "inactivity_reminder": "مازلت هنا؟ تم حفظ التقدم متاعك.",
        "inactivity_timeout": "حفظنا الأجوبة متاعك. تنجم تكمل بعد أو تمشي للموعد.",
        "completion_message": "يعيشك! الأجوبة متاعك وصلت للطبيب.",
        "completion_teleconsult": "نحو نوصلوك بالطبيب توا...",
        "completion_inperson": "الطبيب باش يقرا الأجوبة متاعك قبل ما يقابلك.",
        "initial_prompt": "اوصف العرض الرئيسي ولا شنو اللي جابك.",
        "submit_button": "إمشي",
        "skip_button": "نقز الاستبيان",
        "other_placeholder": "فسر أكثر...",
        "loading_question": "نحو نحضرلك سؤال جديد...",
        "error_retry": "صار مشكل. عاود حاول.",
        "urgency_warning": "على حسب الأعراض متاعك، ننصحك تمشي للطوارئ بالسيف.",
        "back_button": "ارجع",
        "progress_label": "السؤال {current} من {total}",
        "questionnaire_title": "استبيان ذكي",
        "loading_ai": "الذكاء الاصطناعي يحضرلك الأسئلة...",
    },
}


def get_ui_strings(language: str) -> dict:
    """Get UI strings for the detected language, fallback to English."""
    return UI_STRINGS.get(language, UI_STRINGS["en"])


LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "ar": "Standard Arabic",
    "ar_tn": "Tunisian Arabic (Derja)",
}


# ═══════════════════════════════════════════════
#  Language Detection Prompt (kept for reference, rarely used)
# ═══════════════════════════════════════════════

LANGUAGE_DETECTION_PROMPT = """Detect the language. Options: "en", "fr", "ar", "ar_tn" (Tunisian Derja).
Tunisian markers: نحو، باش، برشة، كيفاش، توا، عندي، وقتاش
Respond JSON: {{"language": "en", "confidence": 0.95}}"""


# ═══════════════════════════════════════════════
#  Batch Question Generation Prompt (CORE — replaces per-question generation)
# ═══════════════════════════════════════════════

BATCH_QUESTIONS_PROMPT = """You are a medical intake assistant. Generate ALL intake questions for a patient in a single response.

CLINICAL FRAMEWORK (OLDCARTS):
O=Onset (When did it start?)
L=Location (Where exactly?)
D=Duration (How long? Constant or intermittent?)
C=Character (What does it feel like? Sharp, dull, burning?)
A=Aggravating factors (What makes it worse?)
R=Relieving factors (What helps?)
T=Timing (When does it happen? Pattern?)
S=Severity (How bad? 1-10 scale)

Also consider: associated symptoms, medications, medical history.

RULES:
1. Generate 3-{max_questions} questions based on symptom complexity
2. URGENT symptoms (chest pain, breathing difficulty) → 3-4 questions only
3. VAGUE complaints → 5-{max_questions} questions for thorough assessment
4. Use simple everyday language — patient-friendly
5. Each question: max 2 sentences
6. EVERY radio/checkbox question MUST have 4-6 options. NEVER leave options empty.
7. Options MUST match the question topic
8. NEVER diagnose or give medical opinions
9. Skip irrelevant OLDCARTS areas for the given symptoms
10. Always include an "Other" option with is_other=true for radio_with_other/checkbox_with_other types
11. Prefer radio_with_other type for most questions. Use text type ONLY for open-ended questions.

LANGUAGE: Write ALL questions and options in {language_name} ({language_code}).

PATIENT COMPLAINT: "{initial_symptoms}"

MEDICAL CONTEXT:
{rag_context}

Respond with JSON:
{{"urgency_level": "none", "urgency_note": "", "questions": [{{"question_text": "Question in {language_name}", "question_type": "radio_with_other", "options": [{{"label": "Option text", "value": "option_key", "is_other": false}}, {{"label": "Other", "value": "other", "is_other": true}}], "clinical_area": "onset"}}]}}

Valid question_type: radio, checkbox, text, radio_with_other, checkbox_with_other
Valid clinical_area: onset, location, duration, character, severity, aggravating, relieving, timing, associated_symptoms, medications, history, general
ONLY text type may have options=[]. All other types MUST have 4-6 options.
urgency_level: none, low, medium, high, critical"""


# ═══════════════════════════════════════════════
#  Doctor Summary Generation Prompt
# ═══════════════════════════════════════════════

DOCTOR_SUMMARY_PROMPT = """You are a medical documentation assistant. Generate a pre-consultation summary from the patient's questionnaire.

This summary is for the DOCTOR before the appointment. Rules:
1. Be concise and clinically structured
2. Only use what the patient reported — no speculation
3. Highlight missing information
4. Flag urgency level
5. Be objective and factual
6. NEVER add diagnosis or differential

PATIENT DATA:
- Language: {language}
- Initial complaint: "{initial_symptoms}"
- Status: {status}

CONVERSATION:
{conversation_log}

MEDICAL CONTEXT:
{rag_context}

Respond with JSON only:
{{"main_complaint": "Primary symptom", "duration": "How long or Not specified", "location": "Body area or Not specified", "intensity": "Severity or Not specified", "associated_symptoms": ["symptom1", "symptom2"], "triggers": "What makes worse or Not specified", "relieving_factors": "What helps or Not specified", "relevant_history": "History or Not specified", "medications": "Medications or Not specified", "urgency_level": "none", "missing_information": ["info1"], "recommended_specialty": "General", "narrative_summary": "2-3 sentence summary in {language_name}"}}"""


# ═══════════════════════════════════════════════
#  Urgency Detection Prompt
# ═══════════════════════════════════════════════

URGENCY_DETECTION_PROMPT = """You are a symptom safety screener. Flag dangerous symptoms only.

RED FLAGS: severe chest pain + shortness of breath, sudden worst-ever headache, stroke signs (numbness/confusion/vision loss), severe bleeding, loss of consciousness, severe allergic reaction, suicidal thoughts, seizures, high fever (>40°C) + confusion.

PATIENT TEXT: "{text}"
LANGUAGE: {language}

Respond JSON:
{{"level": "none", "note": "Brief note", "recommend_urgent_care": false, "gentle_message": null}}

Levels: none, low, medium, high, critical
gentle_message: If level >= medium, write a kind message in {language_name} recommending care. If none/low, set null.
Do NOT over-flag common symptoms."""


# ═══════════════════════════════════════════════
#  Legacy prompts (kept for compatibility)
# ═══════════════════════════════════════════════

NEXT_QUESTION_PROMPT = BATCH_QUESTIONS_PROMPT  # Redirected — batch is now the default

QUESTIONNAIRE_PLANNER_PROMPT = BATCH_QUESTIONS_PROMPT  # Merged into batch prompt

LANGUAGE_INSTRUCTIONS = {
    "en": "Write naturally in English.",
    "fr": "Écrivez naturellement en français.",
    "ar": "اكتب بالعربية الفصحى البسيطة.",
    "ar_tn": "اكتب بالتونسي (الدارجة). مثال: 'وين توجعك؟' بدل 'أين يؤلمك؟'",
}

ANSWER_NORMALIZATION_PROMPT = """Normalize the patient's answer into clean text.
Language: {language_name}
Question: "{question}"
Answer: "{answer}"
Selections: {selections}
Respond with ONLY one clean sentence. No JSON."""
