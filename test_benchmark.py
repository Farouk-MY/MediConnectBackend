"""Test the Ollama batch question generation end-to-end."""
import asyncio
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

from app.services.ai_service import ai_service


async def test():
    print("=" * 60)
    print("Testing Ollama with gemma4:e4b")
    print("=" * 60)

    # Step 1: Quick health check
    health = await ai_service.health_check()
    print(f"\nHealth: {health}")

    # Step 2: Simple LLM call
    print("\n--- Test 1: Simple LLM call ---")
    start = time.time()
    try:
        result = await ai_service._call_llm(
            messages=[
                {"role": "system", "content": "Respond with JSON only: {\"status\": \"ok\"}"},
                {"role": "user", "content": "Hello"},
            ],
            json_mode=True,
            temperature=0.1,
            max_tokens=50,
        )
        elapsed = time.time() - start
        print(f"OK in {elapsed:.1f}s: {result[:200]}")
        print(f"Provider: {ai_service._active_provider}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"FAILED in {elapsed:.1f}s: {e}")

    # Step 3: Batch question generation
    print("\n--- Test 2: Batch question generation ---")
    start = time.time()
    try:
        result = await ai_service.generate_all_questions(
            initial_symptoms="I have a headache since 2 days",
            language="en",
            rag_context="Check onset, severity, associated symptoms.",
            max_questions=5,
        )
        elapsed = time.time() - start
        print(f"OK in {elapsed:.1f}s")
        print(f"Questions: {len(result['questions'])}")
        print(f"Urgency: {result['urgency_level']}")
        for i, q in enumerate(result["questions"]):
            area = q.get("clinical_area", "?")
            print(f"  Q{i+1} [{area}]: {q['question_text'][:80]}")
            opts = [o["label"] for o in q.get("options", [])]
            print(f"       Options: {opts}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"FAILED in {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(test())
