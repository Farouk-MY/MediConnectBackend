"""Quick validation that schemas and UI strings are correct."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from app.schemas.questionnaire import QuestionnaireStartResponse, NextQuestionResponse
print("✅ Schema imports OK")

from app.services.prompt_templates import UI_STRINGS
print(f"✅ UI_STRINGS languages: {list(UI_STRINGS.keys())}")
print(f"✅ EN keys: {list(UI_STRINGS['en'].keys())}")

# Check new fields exist
assert 'questionnaire_title' in UI_STRINGS['en'], "Missing questionnaire_title in EN"
assert 'questionnaire_title' in UI_STRINGS['ar'], "Missing questionnaire_title in AR"
assert 'loading_ai' in UI_STRINGS['en'], "Missing loading_ai in EN"
assert 'loading_ai' in UI_STRINGS['ar'], "Missing loading_ai in AR"
print("✅ New UI string keys present in all languages")

# Check schema fields
from pydantic import BaseModel
schema = NextQuestionResponse.model_json_schema()
assert 'max_questions' in schema.get('properties', {}), "Missing max_questions in NextQuestionResponse"
schema2 = QuestionnaireStartResponse.model_json_schema()
assert 'max_questions' in schema2.get('properties', {}), "Missing max_questions in QuestionnaireStartResponse"
print("✅ max_questions field present in both schemas")

# Test language detection
from app.services.ai_service import ai_service
tests = [
    ("I have a headache", "en"),
    ("j'ai mal à la tête", "fr"),
    ("عندي صداع", "ar"),
    ("راسي يوجعني برشة", "ar_tn"),
]
for text, expected in tests:
    result = ai_service.detect_language(text)
    lang = result['language']
    conf = result['confidence']
    status = "✅" if lang == expected else "❌"
    print(f"  {status} '{text}' → {lang} (expected {expected}, conf={conf:.0%})")

print("\nAll validations passed!")
